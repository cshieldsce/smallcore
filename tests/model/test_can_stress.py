"""How far Protocol Engine v2 stretches for classical CAN with programs only.

Nothing in the ISA, the model or the RTL changes: every program is written
by experiments/can_stress/gen.py from parameters (DLC, clocks a bit, loop,
checks), and n = 8 with DLC 1 is stage 6A and 6C word for word. The benches
are test_can.py's (Bus, Frame, stuffed, frame_bits, frame_host,
stalled_host), test_can_rx.py's Transmitter and test_can_combined.py's
Rival, run_tx and the host byte layouts. Failures are results: a test that
pins a failure asserts its failure mode, and says why in its docstring.

docs/can-stress.md is the report these tests are the evidence for."""

import importlib.util
import random
from fractions import Fraction
from pathlib import Path

import pytest

from cpu import CPU, assemble, decode, load_isa
from test_can import GAP, Bus, Frame, bits_to_int, cells, frame_bits, frame_names, stalled_host, stuffed, frame_host
from test_can import CRC_BITS, crc15, int_bits, header_bits
from test_can_combined import POLY, Rival, arb_bytes, run_tx, unopposed_bytes
from test_can_rx import Transmitter

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("can_stress_gen", ROOT / "experiments" / "can_stress" / "gen.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

BIT = 8
TX_SAMPLE = 3  # the level 6A's own SHIFT_IN takes: the bus through the third clock
RX_SAMPLE = 6  # a receiver on the bus: the sixth clock of eight (75%)
LIMIT = 256  # words a program may have
ISA = load_isa()
RNG = random.Random(0xCA17)


def program(source):
    return gen.patched(source) if "# PATCH" in source else assemble(source)


def rx_frame(sample=RX_SAMPLE, bit=BIT, ack=True):
    return Frame(sample=sample, bit=bit, ack=ack)


def payloads(dlc, count=4, rng=RNG):
    """Adversarial first, then random: all dominant, all recessive, alternating, the max-stuff nibbles."""
    fixed = [[0x00] * dlc, [0xFF] * dlc, [0x55] * dlc, [0xAA] * dlc, [0x0F, 0xF0] * 4]
    out = [p[:dlc] for p in fixed]
    out += [[rng.randrange(256) for _ in range(dlc)] for _ in range(count)]
    return out


def stuff_count(ident, data):
    return len(stuffed(frame_bits(ident, data))) - len(frame_bits(ident, data))


def tx_ok(src, ident, data, n=BIT, cycles=None):
    """The transmitter from `src` alone on the bus with a receiver that acks: the frame bit for bit, each bit
    held its n clocks, the receiver's CRC right and acked."""
    rx = rx_frame(sample=max(1, round(0.75 * n)), bit=n)
    words = program(src) if isinstance(src, str) else src
    r = run_tx(words, unopposed_bytes(ident, data), [rx], cycles=cycles or 400 + 160 * n)
    bits = stuffed(frame_bits(ident, data))
    exact = cells(r.line, r.line.index(0), len(bits), n) == bits
    got = rx.received[0] if rx.received else None
    return exact and got is not None and (got.ident, got.data, got.crc_ok, got.acked) == (ident, tuple(data), True, True)


# --- the multi-core bus: two programs on one wire ------------------------------------------------


class Core:
    """A model core as a bus node: its pad on the bus, open-drain once it CONFIGs, a host at its FIFOs that
    queues `feed` as room appears (4 deep) and pops everything at once into `received`."""

    def __init__(self, words, feed=(), depth=4, start=0):
        self.cpu = CPU(words, gpio_in=1)
        self.queue, self.depth, self.received, self.start, self.t = list(feed), depth, [], start, -1
        self.drove = []  # the cycles it pulled the bus dominant

    def update(self, line):
        cpu = self.cpu
        self.t += 1
        if self.t < self.start:  # not powered yet: the pad let go
            return None
        cpu.gpio_in[0] = line
        if self.queue and len(cpu.tx_fifo) < self.depth:
            cpu.tx_fifo.append(self.queue.pop(0))
        if not cpu.halted:
            cpu.step()
        while cpu.rx_fifo:
            self.received.append(cpu.rx_fifo.pop(0))
        drive = 0 if cpu.gpio_oe[0] and cpu.gpio[0] == 0 else None
        if drive == 0:
            self.drove.append(self.t)
        return drive


def wire(nodes, cycles):
    """Every node sees the bus as it stood at the end of the cycle before: a wired AND."""
    line, lines = 1, []
    for _ in range(cycles):
        drives = [node.update(line) for node in nodes]
        line = 0 if 0 in drives else 1
        lines.append(line)
    return lines


# --- 1. DLC 0..8: one program per DLC, one word apart ------------------------------------------------


def test_one_transmitter_per_dlc_one_word_apart():
    """6A for DLC 0 to 8: 152 words each, and each differs from DLC 1's in
    exactly one word, the body's REPEAT count (2 + DLC). Nothing lets the
    host set a count, so a length is a program: nine programs, or nine ROM
    slots, for one transmitter."""
    base = assemble(gen.tx(1))
    for dlc in range(9):
        words = assemble(gen.tx(dlc))
        diff = [i for i, (a, b) in enumerate(zip(words, base)) if a != b]
        assert len(words) == 152 and len(diff) == (0 if dlc == 1 else 1), dlc
        if diff:
            assert decode(words[diff[0]], ISA).op == "REPEAT" and decode(words[diff[0]], ISA).delay == 1 + dlc


@pytest.mark.parametrize("dlc", range(9))
def test_every_dlc_with_adversarial_and_random_payloads(dlc):
    """Per DLC: all-dominant, all-recessive, alternating and max-stuff payloads and four random ones, each
    under four identifiers (0x000, 0x7FF and two random): bit for bit on the bus, CRC right, acked."""
    idents = [0x000, 0x7FF, RNG.randrange(2048), RNG.randrange(2048)]
    src = gen.tx(dlc)
    words = assemble(src)
    for data in payloads(dlc):
        for ident in idents:
            assert tx_ok(words, ident, data), (dlc, hex(ident), data)


MAX_STUFF = (0x7BE, [0x00] + [0x0F] * 7)  # 21 stuff bits: a greedy search over every identifier, byte by byte


def max_stuff_frames():
    """Frames with the most stuff bits the search finds for DLC 8, one with a stuff bit after CRC[0], the last
    stuffed bit, and one with stuff bits inside the CRC field."""
    rng = random.Random(5)
    best, crc_last, crc_inside = None, None, None
    candidates = [(i, [b] * 8) for i in (0x000, 0x7FF, 0x0F0, 0x70F) for b in (0x00, 0xFF, 0x0F, 0xF0, 0x87, 0x78, 0xE1, 0x1E)]
    candidates += [(rng.randrange(2048), [rng.choice((0x00, 0xFF, 0x0F, 0xF0, 0x87, 0x78, 0xC3, 0x3C, 0xE1, 0x1E))
                                          for _ in range(8)]) for _ in range(3000)]
    for ident, data in candidates:
        n = stuff_count(ident, data)
        if best is None or n > best[0]:
            best = (n, ident, data)
        names = frame_names(ident, data)
        crc_at = names.index("crc14")
        tail = names[crc_at : names.index("crcdel")]
        if crc_last is None and tail[-1] == "stuff":
            crc_last = (ident, data)
        if crc_inside is None and tail.count("stuff") >= 3:
            crc_inside = (ident, data)
    return (stuff_count(*MAX_STUFF), *MAX_STUFF), crc_last, crc_inside


def test_stuffing_extremes():
    """The most-stuffed DLC 8 frame the search finds, a frame whose last stuffed bit is a stuff bit after
    CRC[0], and one with three stuff bits in the CRC field: 6A sends each bit for bit and the receiver acks.
    The bound for 98 free bits is 24 stuff bits ((98 - 1) // 4); RTR, IDE, r0, the DLC and the CRC are not
    free, and the greedy search found 21: 119 bits on the bus for 98."""
    (n, ident, data), crc_last, crc_inside = max_stuff_frames()
    assert n == 21 and crc_last and crc_inside
    for ident_, data_ in ((ident, data), crc_last, crc_inside):
        assert tx_ok(gen.tx(len(data_)), ident_, data_), (hex(ident_), data_)


# --- 2. the receiver that follows the DLC ----------------------------------------------------------------


def rx_run(words, bits, at=10, cycles=None, host=None, rx_depth=4, drain=True, bit=BIT):
    cpu = CPU(words, gpio_in=1, tx_data=list(POLY), rx_depth=rx_depth)
    tx = Transmitter(bits, at, bit, len(bits) - GAP - 2)
    r = Bus(None, [], [tx], cpu=cpu, host=host, drain=drain).go(cycles or at + (len(bits) + 4) * bit + 200).result()
    return r, tx


def on_bus(ident, data, crc=None):
    return stuffed(frame_bits(ident, data, crc)) + [1, 1, 1] + [1] * GAP


@pytest.mark.parametrize("dlc", range(9))
def test_one_receiver_for_every_dlc(dlc):
    """can_rx_dlc.asm, 237 words: bit 0 of the first 34 + 8 DLC bytes is the destuffed stream, then the
    residue 0, 0; acked. The DLC decides the length in the program: a tree of SKIP 0 cells on the four DLC
    bits (a stuff bit after one says its value by the run's level) into a chain of eight-bit loops."""
    words = assemble(gen.rx_dlc())
    assert len(words) == 237
    for data in payloads(dlc, count=2):
        for ident in (0x000, 0x7FF, RNG.randrange(2048)):
            r, tx = rx_run(words, on_bus(ident, data))
            stream = frame_bits(ident, data)
            assert [b & 1 for b in r.received[: len(stream)]] == stream, (dlc, hex(ident), data)
            assert r.received[len(stream) :] == [0, 0] and tx.acked and r.cpu.halted


def test_a_dlc_above_eight_is_eight_bytes():
    """DLC 9 to 15 carry eight bytes: the DLC3 = 1 branch ignores the other three bits."""
    words = assemble(gen.rx_dlc())
    for dlc in (9, 12, 15):
        bits = header_bits(0x123) + [0, 0, 0] + int_bits(dlc, 4) + [b for byte in range(8) for b in int_bits(byte * 37 & 0xFF, 8)]
        bits += int_bits(crc15(bits), CRC_BITS)
        r, tx = rx_run(words, stuffed(bits) + [1, 1, 1] + [1] * GAP)
        assert [b & 1 for b in r.received[: len(bits)]] == bits and r.received[len(bits) :] == [0, 0], dlc


def remote_frame(ident, dlc):
    bits = header_bits(ident) + [1, 0, 0] + int_bits(dlc, 4)
    return bits + int_bits(crc15(bits), CRC_BITS)


def test_remote_frames_do_not_fit_beside_the_dlc_tree():
    """A remote frame (RTR 1) has a DLC and no data. can_rx_dlc.asm reads it as a data frame and takes
    the CRC and the fixed form for data: the residue is wrong and the frame lost. The fix in program is
    one more tree cell on RTR and a path of 21 bits (IDE, r0, the DLC, the CRC) to the fixed form; built,
    it passes 256 words and the assembler refuses it. Missing: program words (or a count from data)."""
    words = assemble(gen.rx_dlc())
    bits = remote_frame(0x2A5, 4)
    r, tx = rx_run(words, stuffed(bits) + [1, 1, 1] + [1] * GAP, cycles=3000)
    assert [b & 1 for b in r.received[: len(bits)]] == bits  # the header and the CRC arrive, then
    assert len(r.received) == len(bits) + 32 + 2 and r.received[-2:] != [0, 0]  # 32 "data" bits of idle bus, a residue
    assert tx.acked is False  # and the remote frame's ACK slot passed unanswered
    source = gen.rx_dlc_rtr()
    count = sum(1 for line in source.splitlines() if line.strip() and not line.strip().startswith("#"))
    assert count == 272, count
    with pytest.raises(SyntaxError):
        assemble(source)


# --- 3. back-to-back frames, the intermission, bus idle --------------------------------------------------


def sofs(lines):
    """The cycles the bus fell after at least eleven bits (88 clocks) of recessive, or from the start."""
    out, run = [], 10 ** 6
    for i, level in enumerate(lines):
        if level == 0 and run >= 11 * BIT:
            out.append(i)
        run = run + 1 if level else 0
    return out


def test_back_to_back_frames_with_the_three_bit_intermission():
    """can_tx_loop.asm, 151 words: three frames queued at once go out back to back, each received and
    acked, the host reading one ACK byte a frame. Between the ACK delimiter and the next SOF the bus is
    recessive for EOF and the intermission, ten bits, plus three clocks (the idle sample, the PULL, the SOF's SHIFT_OUT)."""
    frames = [(0x123, [0x11]), (0x7FF, [0xFF]), (0x000, [0x00])]
    host_bytes = POLY + [b for ident, data in frames for b in unopposed_bytes(ident, data)[2:]]
    rx = rx_frame()
    r = run_tx(assemble(gen.tx(1, loop=True)), host_bytes, [rx], cycles=3 * 130 * BIT)
    assert [(f.ident, f.data, f.crc_ok, f.acked) for f in rx.received] == [(i, tuple(d), True, True) for i, d in frames]
    assert [b & 1 for b in r.received] == [0, 0, 0]
    starts = sofs(r.line)
    assert len(starts) == 3
    for (ident, data), sof in zip(frames, starts):
        end = sof + (len(stuffed(frame_bits(ident, data))) + 3) * BIT  # the ACK delimiter's end
        nxt = next((s for s in starts if s > sof), None)
        if nxt:
            assert nxt - end == 10 * BIT + 3, nxt - end


def two_frames(first, second, space=3):
    """A bench transmitter's bits for two frames, `space` intermission bits between them (3: back to
    back); only the second's ACK slot is watched."""
    a = stuffed(frame_bits(*first)) + [1, 1, 1] + [1] * 7 + [1] * space
    b = stuffed(frame_bits(*second)) + [1, 1, 1] + [1] * GAP
    return a + b, len(a) + len(b) - GAP - 2


def test_a_looping_receiver_takes_back_to_back_frames():
    """6C going round (can_rx_loop_idle.asm, 48 words) against two frames three intermission bits apart:
    both streams, both residues 0, the second acked. The loop is back at the SOF's WAIT in the
    intermission's third bit: with 6C's ten-bit gap it would be four clocks late for this SOF."""
    words = assemble(gen.rx(42, loop=True, idle=True))
    first, second = (0x5A3, [0x5A]), (0x07C, [0x00])
    bits, slot = two_frames(first, second)
    cpu = CPU(words, gpio_in=1, tx_data=list(POLY))
    tx = Transmitter(bits, 200, BIT, slot)
    r = Bus(None, [], [tx], cpu=cpu).go(200 + (len(bits) + 4) * BIT).result()
    a, b = frame_bits(*first), frame_bits(*second)
    assert [x & 1 for x in r.received[:42]] == a and r.received[42:44] == [0, 0]
    assert [x & 1 for x in r.received[44:86]] == b and r.received[86:88] == [0, 0] and tx.acked


def joined_late(words, start):
    """The receiver powered at `start`, inside a frame: then a second frame after the intermission."""
    first, second = (0x2F0, [0xF0]), (0x5A3, [0x5A])
    bits, slot = two_frames(first, second)
    rx = Core(words, POLY, start=start)
    tx = Transmitter(bits, 10, BIT, slot)
    wire([tx, rx], 10 + (len(bits) + 4) * BIT)
    return rx.received, frame_bits(*second), tx


def test_bus_integration_needs_eleven_recessive_bits():
    """A receiver switched on in the middle of a frame. With the idle wait (eleven recessive samples, 12
    words) it ignores the rest of that frame and takes the next whole. Without it, 6C going round syncs on
    the first falling edge it sees, inside the frame, and the next frame's stream is not what reaches the
    host: kept as the failure the idle wait is for."""
    got, want, tx = joined_late(assemble(gen.rx(42, loop=True, idle=True)), 10 + 20 * BIT)
    assert [x & 1 for x in got[:42]] == want and got[42:44] == [0, 0] and tx.acked
    got, want, tx = joined_late(assemble(gen.rx(42, loop=True)), 10 + 20 * BIT)
    assert [x & 1 for x in got[:42]] != want


def test_two_cores_on_one_bus():
    """The looping transmitter and the looping receiver, both model cores, one wire: three frames, the
    receiver's host reads 44 bytes each, the streams and residues right; the transmitter's host reads
    three ACK bytes that say acked, the ACK the receiver core's."""
    frames = [(0x100, [0x01]), (0x0F0, [0x0F]), (0x7FE, [0xFE])]
    feed = POLY + [b for ident, data in frames for b in unopposed_bytes(ident, data)[2:]]
    tx = Core(assemble(gen.tx(1, loop=True)), feed, start=100)
    rx = Core(assemble(gen.rx(42, loop=True, idle=True)), POLY)
    wire([tx, rx], 100 + 3 * 80 * BIT)
    for k, (ident, data) in enumerate(frames):
        chunk = rx.received[44 * k : 44 * k + 44]
        assert [x & 1 for x in chunk[:42]] == frame_bits(ident, data) and chunk[42:] == [0, 0], k
    assert [b & 1 for b in tx.received] == [0, 0, 0]


class SlotHost(Core):
    """A transmitter whose host changes the program between frames: when the core halts, acked and through
    the intermission (a restart at the ACK byte would start the next frame inside EOF), it restarts the core
    under the next frame's DLC program and queues the polynomial (a restart clears it) and the frame."""

    def __init__(self, frames, start=0):
        self.frames = list(frames)
        ident, data = self.frames.pop(0)
        super().__init__(assemble(gen.tx(len(data))), unopposed_bytes(ident, data), start=start)
        self.restarts = 0

    def update(self, line):
        drive = super().update(line)
        if self.cpu.halted and self.frames:  # acked and through the intermission: the next slot
            ident, data = self.frames.pop(0)
            self.cpu.restart(assemble(gen.tx(len(data))))
            self.queue += unopposed_bytes(ident, data)
            self.restarts += 1
        return drive


def test_mixed_dlcs_back_to_back_by_changing_programs():
    """The one receiver for every DLC, going round, against a transmitter whose host swaps the DLC program
    (a restart, the ROM slot on the chip) after every frame: DLC 0, 8, 3, 1, every stream and residue
    right, every frame acked. The DLC is the host's to choose on the transmit side, a program per length;
    on the receive side one program follows the DLC on the wire."""
    frames = [(0x001, []), (0x7F0, [0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0xFF, 0x0F, 0xF0]), (0x3C3, [1, 2, 3]), (0x555, [0xAA])]
    tx = SlotHost(frames, start=100)
    rx = Core(assemble(gen.rx_dlc(loop=True)), POLY)
    wire([tx, rx], 100 + 4 * 150 * BIT)
    at = 0
    for ident, data in frames:
        stream = frame_bits(ident, data)
        chunk = rx.received[at : at + len(stream) + 2]
        assert [x & 1 for x in chunk[: len(stream)]] == stream and chunk[len(stream) :] == [0, 0], (hex(ident), len(data))
        at += len(stream) + 2
    assert [b & 1 for b in tx.received] == [0, 0, 0, 0] and tx.restarts == 3


# --- 4. arbitration: lose at every identifier bit, retry in the program ------------------------------------


ARB_IDENTS = (0x7FF, 0x5A3, 0x555, 0x2AA, 0x400, 0x001)  # 0x7FF: a loss on each of the eleven identifier bits


@pytest.mark.parametrize("ident", ARB_IDENTS, ids=lambda i: f"{i:03x}")
def test_lose_on_every_recessive_identifier_bit_then_retry(ident):
    """can_tx_arb_retry: 6B with the loss handled in the program. Against a rival that differs first on
    each of the identifier's recessive bits, dominant there: the rival's frame goes through whole, then
    the program waits out eleven recessive bits and arbitrates again from the byte still in shift_reg
    (the header is SETs), acc shifted clear on a spare pin; its frame goes through second, CRC right,
    acked. The host queued the frame once and reads two bytes: the loss, the ACK."""
    words = assemble(gen.arb_retry(ident))
    for i in [i for i in range(11) if (ident >> i) & 1]:
        other = ident & ~(1 << i)
        rx, rival = rx_frame(), Rival(other, [0x33])
        r = run_tx(words, arb_bytes([0x5A]), [rival, rx], cycles=2 * 110 * BIT + 200)
        assert [(f.ident, f.crc_ok, f.acked) for f in rx.received] == [(other, True, True), (ident, True, True)], (hex(ident), i)
        assert rx.received[1].data == (0x5A,) and len(r.received) == 2 and r.received[1] & 1 == 0 and r.cpu.halted


def test_the_retry_costs_fifteen_words_and_every_identifier_fits():
    """The retry is the lost path's PUSH, a two-word clear of acc, the twelve-word idle wait and a JMP, and
    a NOP for the label, 15 words on every identifier sampled: 6B's 206 to 228 (test_can_combined, all
    2048) become 221 to 243, DLC 1; the
    DLC is a REPEAT count and header bits, 239 for 0x7FF at DLC 8. Still one program per identifier and DLC."""
    sample = list(range(0, 2048, 61)) + [0x000, 0x7FF]
    assert all(len(assemble(gen.arb_retry(i))) - len(assemble(gen.combined().tx_arbitration(i, write=False))) == 15 for i in sample)
    assert (len(assemble(gen.arb_retry(0x000))), len(assemble(gen.arb_retry(0x7FF)))) == (225, 243)
    assert len(assemble(gen.arb_retry(0x7FF, dlc=8))) == 239  # DLC 1000 for 0001: other header stuff bits


def test_a_node_that_loses_cannot_also_receive_the_frame():
    """Counted, not built: in CAN the loser receives the winner's frame and acks it. Here the loser's
    acc holds the CRC of the bus so far and in_shift_reg the raw history, so the state would carry over;
    what does not fit is the program: 6B for one identifier beside the DLC-following receiver, less the
    six set-up words they share, is well past 256 words, before the entry points a loss at each of the
    eleven identifier bits would need. Missing: program words. arb_retry idles through the winner's frame."""
    arb = len(assemble(gen.combined().tx_arbitration(0x5A3, write=False)))
    rx = len(assemble(gen.rx_dlc()))
    assert (arb, rx) == (214, 237) and arb + rx - 6 > LIMIT


# --- 5. late host and FIFO pressure ----------------------------------------------------------------------


def serviced_tx(words, host_bytes, every, nodes, cycles, first=20):
    """A host that queues the polynomial at once, then from cycle `first` comes to the TX FIFO every
    `every` cycles and fills it to four with the frame's bytes."""
    poly, queue = list(host_bytes[:2]), list(host_bytes[2:])

    def host(cpu, received):
        if poly:
            cpu.tx_fifo.append(poly.pop(0))
        if cpu.cycle >= first and (cpu.cycle - first) % every == 0:
            while queue and len(cpu.tx_fifo) < 4:
                cpu.tx_fifo.append(queue.pop(0))

    cpu = CPU(words, gpio_in=1)
    return Bus(None, [], nodes, host=host, cpu=cpu).go(cycles).result()


def test_transmitter_host_service_interval():
    """DLC 8, 6A, 11 frame bytes through the 4-deep TX FIFO. A host that fills the FIFO every P cycles
    keeps the frame free of stalls up to P = 218 clocks, 27 bit times, for a frame without stuff bits:
    the four bytes one visit leaves cover the SOF's three bits and three bytes. At 219 a PULL finds the
    FIFO empty inside the frame and the bit under it stretches. Stuff bits give the host time: 242 for
    the most stuffed frame, 250 for all-dominant. On average a byte per eight bits: 125 kB/s at 1 Mbit/s."""
    words = assemble(gen.tx(8))
    got = {}
    for ident, data, every in ((0x123, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88], 218), (0x7BE, [0x00] + [0x0F] * 7, 242)):
        bits = stuffed(frame_bits(ident, data))
        for p in (every, every + 1):
            r = serviced_tx(words, unopposed_bytes(ident, data), p, [rx_frame()], 2000)
            sof = r.line.index(0)
            got[(ident, p)] = not any(r.stalls[sof : sof + len(bits) * BIT])
    assert got == {(0x123, 218): True, (0x123, 219): False, (0x7BE, 242): True, (0x7BE, 243): False}


def test_one_late_cycle_at_a_pull_breaks_the_bit():
    """The stall contract, re-confirmed at DLC 8 on the last data byte's PULL: late by one cycle and the
    bit under the PULL is nine clocks; a receiver sampling on the sixth clock from the SOF still reads
    the frame right up to five cycles late and loses it from six. Nothing in the frame can absorb a late
    host: there is no resynchronisation in any receiver here either."""
    ident, data = 0x123, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
    host_bytes = unopposed_bytes(ident, data)
    k = len(host_bytes) - 1  # the last data byte
    words = assemble(gen.tx(8))
    fine = {}
    for late in (1, 5, 6):
        rx = rx_frame()
        r = Bus(None, [], [rx], host=stalled_host(host_bytes, k, late), cpu=CPU(words, gpio_in=1)).go(1600).result()
        bits = stuffed(frame_bits(ident, data))
        with pytest.raises(AssertionError):
            cells(r.line, r.line.index(0), len(bits), BIT)
        fine[late] = bool(rx.received) and rx.received[0].crc_ok and rx.received[0].data == tuple(data)
    assert fine == {1: True, 5: True, 6: False}


def serviced_rx(words, bits, every, rx_depth=4):
    """A host that comes to the RX FIFO every `every` cycles and empties it."""
    got = []

    def host(cpu, received):
        if cpu.cycle % every == 0:
            got.extend(cpu.rx_fifo)
            cpu.rx_fifo.clear()

    r, tx = rx_run(words, bits, host=host, drain=False, rx_depth=rx_depth)
    got.extend(r.cpu.rx_fifo)
    return r, tx, got


def test_receiver_host_service_interval():
    """The receiver hands the host a byte a data bit: at 1 Mbit/s a megabyte a second. can_rx_dlc.asm at
    DLC 8 with a host that empties the 4-deep RX FIFO every P cycles: fine up to P = 32 clocks, four bit
    times, and a stall inside the frame from 33, the stream wrong. The host's bound is a visit every four
    bit times for the whole frame."""
    words = assemble(gen.rx_dlc())
    ident, data = 0x123, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
    stream = frame_bits(ident, data)
    ok = {}
    for every in (24, 32, 33, 40):
        r, tx, got = serviced_rx(words, on_bus(ident, data), every)
        ok[every] = [x & 1 for x in got[: len(stream)]] == stream and got[len(stream) :] == [0, 0] and not any(r.stalls[20:])
    assert ok == {24: True, 32: True, 33: False, 40: False}


# --- 6. errors ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dlc", (0, 1, 8))
def test_a_wrong_crc_is_the_hosts_to_see_and_is_acked_anyway(dlc):
    """can_rx_dlc.asm, a transmitter with a wrong CRC: the residue the host reads is not 0, 0, and the ACK
    slot was pulled all the same. Re-confirms 6C's wall for every length: nothing takes acc to the pc in
    the eight clocks of the CRC delimiter. Missing: a decision on the accumulator."""
    words = assemble(gen.rx_dlc())
    data = [0xA5] * dlc
    right = bits_to_int(frame_bits(0x321, data)[-CRC_BITS:])
    for wrong in (right ^ 1, right ^ 0x4000):
        r, tx = rx_run(words, on_bus(0x321, data, crc=wrong))
        n = len(frame_bits(0x321, data))
        assert r.received[n : n + 2] != [0, 0] and tx.acked is True


class Forcer:
    """Not a node: pulls the bus dominant for the cycles in [start, end)."""

    def __init__(self, start, end):
        self.start, self.end, self.i = start, end, -1

    def update(self, line):
        self.i += 1
        return 0 if self.start <= self.i < self.end else None


def test_a_transmitter_cannot_see_a_bit_error_and_its_crc_hides_it():
    """6A computes the CRC and the stuffing from the bus, not from what it meant to send: the only view of
    a sent bit it has. A node that forces one recessive data bit dominant for its whole bit: the
    transmitter goes on, stuffs by what the bus showed and sends the CRC of what the bus showed, so the
    receiver reads a valid frame with the wrong byte, CRC right, and acks it; the transmitter's host
    reads 'acked'. In CAN the transmitter's bit monitoring catches this: the bit it sent beside the bit
    on the bus. Missing: a third stream (sent bit, bus history, CRC), the arbitration wall again."""
    ident, data = 0x5A3, [0xFF]
    words = assemble(gen.tx(1))
    clean = run_tx(words, unopposed_bytes(ident, data), [rx_frame()])
    sof = clean.line.index(0)
    k = frame_names(ident, data).index("d0.3")
    rx = rx_frame()
    r = run_tx(words, unopposed_bytes(ident, data), [Forcer(sof + k * BIT, sof + (k + 1) * BIT), rx])
    got = rx.received[0]
    assert got.data == (0xF7,) and got.crc_ok and got.acked and r.received[-1] & 1 == 0


class Aborting(Transmitter):
    """A bench transmitter that stops, as CAN's must, when it sees dominant on a recessive bit it sent
    outside the ACK slot: an error flag from someone."""

    def update(self, line):
        k, phase = divmod(self.i + 1 - self.at, self.bit)
        if 0 <= k < len(self.bits) and phase == self.sample and self.bits[k] == 1 and line == 0 and k != self.slot:
            self.bits = self.bits[:k]
        return super().update(line)


def flag_at(lines, start):
    """The first run of at least 48 dominant cycles from `start`: (first cycle, length)."""
    i = start
    while i < len(lines):
        if lines[i] == 0:
            j = i
            while j < len(lines) and lines[j] == 0:
                j += 1
            if j - i >= 6 * BIT:
                return i, j - i
            i = j
        i += 1
    return None


def first_drive(core):
    """The first stretch of cycles the core pulled the bus: (first cycle, length)."""
    start = core.drove[0]
    n = 1
    while n < len(core.drove) and core.drove[n] == start + n:
        n += 1
    return start, n


def error_then_good(words, bad_bits, bad_slot, good_at=None):
    """A frame with an error from one bench transmitter, then a good one from another."""
    ident, data = 0x0F3, [0x3C]
    good = on_bus(ident, data)
    t1 = Aborting(bad_bits, 120, BIT, bad_slot)
    good_at = good_at or 120 + (len(bad_bits) + 30) * BIT
    t2 = Transmitter(good, good_at, BIT, len(good) - GAP - 2)
    rx = Core(words, POLY)
    lines = wire([t1, t2, rx], good_at + (len(good) + 4) * BIT)
    return rx, lines, t1, t2, frame_bits(ident, data)


def unstuffed_at(ident, data, after):
    """The frame on the bus with its first stuff bit past bus bit `after` left out: the bus bits, and the
    index of the bit that takes the stuff bit's place, the sixth of its run."""
    names = frame_names(ident, data)
    bits = stuffed(frame_bits(ident, data))
    k = next(i for i, name in enumerate(names) if name == "stuff" and i > after)
    return bits[:k] + bits[k + 1 :] + [1, 1, 1] + [1] * GAP, k


@pytest.mark.parametrize("ident, data, after", ((0x7FF, [0xFF], 0), (0x5A3, [0x00], 20)), ids=("recessive-early", "dominant-late"))
def test_a_stuff_error_answered_with_an_error_flag(ident, data, after):
    """can_rx_check.asm: in the stuff path the newest two samples equal is a sixth bit of the run: a stuff
    error. The JMP to the error flag leaves a REPEAT body, which the assembler refuses; patched in, the
    hardware does it. A transmitter that leaves a stuff bit out (a recessive run in the identifier, a
    dominant one in the data): the receiver pulls the bus dominant six bits from the first or second
    clock of the bit after the bad one, the transmitter aborts, the host reads the bytes so far and 0x00
    (eight dominant raw samples, which no frame shows), rc is drained with a two-word loop, acc shifted
    clear, and the next frame is received whole."""
    words = gen.patched(gen.rx(42, check=True))
    raw, bad = unstuffed_at(ident, data, after)
    rx, lines, t1, t2, good = error_then_good(words, raw, len(raw) - GAP - 2)
    start, length = first_drive(rx)
    assert start - (120 + (bad + 1) * BIT) in (1, 2) and length == 6 * BIT
    assert bad < len(t1.bits) <= bad + 7 and 0x00 in rx.received  # it stopped on its first recessive under the flag
    after_ = rx.received[rx.received.index(0x00) + 1 :]
    assert [x & 1 for x in after_[:42]] == good and after_[42:44] == [0, 0] and t2.acked


@pytest.mark.parametrize("ident, data, after, fine", ((0x7FF, [0xFF], 0, True), (0x5A3, [0x00], 20, False)),
                         ids=("early", "late"))
def test_without_the_rc_drain_a_late_error_loses_the_next_frame(ident, data, after, fine):
    """The same program without the two-word drain. The early error leaves the body in its seventh run,
    rc 26, and the 16-run loop that shifts acc clear absorbs it: 26 shifts, acc clear, the next frame
    fine, by luck. The late one leaves it in run 24, rc 9: nine shifts, acc not clear, and the next
    frame's residue is wrong. Kept as the failure the assembler's rule is for: an early exit from a
    counted loop works on the hardware only if the program cleans up the counter it cannot read."""
    words = gen.patched(gen.rx(42, check=True, drain=False))
    raw, bad = unstuffed_at(ident, data, after)
    rx, lines, t1, t2, good = error_then_good(words, raw, len(raw) - GAP - 2)
    after_ = rx.received[rx.received.index(0x00) + 1 :]
    assert [x & 1 for x in after_[:42]] == good
    assert (after_[42:44] == [0, 0]) is fine


def test_a_form_error_in_the_crc_delimiter_answered_with_an_error_flag():
    """The CRC delimiter is straight-line code: SKIP 0, 1 over a JMP to the error flag, no rule broken, no
    cycle added. A transmitter whose CRC delimiter is dominant: the flag starts one clock into the ACK
    slot, the host reads the 42 stream bytes then 0x00 and no residue, and the next frame is whole."""
    words = gen.patched(gen.rx(42, check=True))
    ident, data = 0x5A3, [0x5A]
    bits = stuffed(frame_bits(ident, data)) + [0, 1, 1] + [1] * GAP
    rx, lines, t1, t2, good = error_then_good(words, bits, len(bits) - GAP - 2)
    start, length = first_drive(rx)
    assert start - (120 + (len(bits) - GAP - 2) * BIT) == 1 and length == 6 * BIT
    assert [x & 1 for x in rx.received[:42]] == frame_bits(ident, data) and rx.received[42] == 0x00
    after = rx.received[43:]
    assert [x & 1 for x in after[:42]] == good and after[42:44] == [0, 0] and t2.acked


def test_a_missing_ack_answered_with_an_error_flag():
    """can_tx_ackflag.asm, 170 words: nobody acks, so from the ACK delimiter's second clock the
    transmitter sends six dominant bits, waits eleven recessive, hands the host 0xFF and sends the frame
    again from the host's next bytes; the receiver acks the second time."""
    ident, data = 0x246, [0x81]
    frame = unopposed_bytes(ident, data)
    rx = Frame(sample=RX_SAMPLE, bit=BIT, ack=[False, True])
    r = run_tx(assemble(gen.tx(1, loop=True, ackflag=True)), frame + frame[2:], [rx], cycles=2 * 130 * BIT)
    sof = r.line.index(0)
    delim = sof + (len(stuffed(frame_bits(ident, data))) + 2) * BIT
    start, length = flag_at(r.line, sof)
    assert start - delim == 1 and length == 6 * BIT
    assert [(f.ident, f.crc_ok, f.acked) for f in rx.received] == [(ident, True, False), (ident, True, True)]
    assert r.received[0] == 0xFF and r.received[1] & 1 == 0


# --- 7. clock rates: bit times of n clocks ----------------------------------------------------------------


RATES = {(mhz, kbit): mhz * 1000 // kbit for mhz in (10, 25, 40, 50) for kbit in (125, 250, 500, 1000)}


def words_at(n):
    """(TX words or None when refused, RX words for DLC 8) at n clocks a bit."""
    try:
        t = len(assemble(gen.tx(8, n)))
    except SyntaxError:
        t = None
    return t, len(assemble(gen.rx(98, n)))


def test_every_rate_is_a_whole_number_of_clocks():
    """10, 25, 40 and 50 MHz against 125k, 250k, 500k and 1 Mbit/s: every pairing is a whole number of
    clocks a bit, 10 to 400, so the fractional-bit error is 0 at every one; the bit time must be a
    whole number of clocks, 8 at least, since the cell is 8."""
    assert all(mhz * 1000 % kbit == 0 for mhz, kbit in RATES)
    assert sorted(set(RATES.values())) == [10, 20, 25, 40, 50, 80, 100, 160, 200, 320, 400]


TX_MAX_N = 133


def test_words_against_the_bit_time():
    """Delays hold 32 clocks a word and a cell sits in a REPEAT body, which cannot hold another loop, so a
    long bit is paid in NOP words, per path of every distinct cell. The transmitter (ten cells, three
    paths each) passes 256 words beyond TX_MAX_N clocks a bit; the receiver (one cell a body) fits to 400."""
    table = {n: words_at(n) for n in (8, 10, 25, 40, 50, 80, 100, 160, 200, 320, 400)}
    assert table == WORDS_AT
    fits = [n for n in range(8, 161) if words_at(n)[0] is not None]
    assert max(fits) == TX_MAX_N


WORDS_AT = {8: (152, 55), 10: (162, 55), 25: (162, 55), 40: (166, 74), 50: (197, 75), 80: (201, 90), 100: (235, 98),
            160: (None, 122), 200: (None, 153), 320: (None, 201), 400: (None, 248)}


@pytest.mark.parametrize("n", (10, 25, 50, 100))
def test_frames_at_realistic_bit_times(n):
    """The transmitter and the receiver generated for n clocks a bit carry a DLC 8 frame at that bit time:
    1 Mbit/s at 10, 25 and 50 MHz, 250 kbit/s at 25 MHz."""
    ident, data = 0x6B5, [0x00, 0xFF, 0x55, 0xAA, 0x0F, 0xF0, 0x12, 0xED]
    assert tx_ok(gen.tx(8, n), ident, data, n=n, cycles=150 * n + 400)
    words = assemble(gen.rx(98, n))
    cpu = CPU(words, gpio_in=1, tx_data=list(POLY))
    bits = on_bus(ident, data)
    tx = Transmitter(bits, 10, n, len(bits) - GAP - 2, sample=max(1, round(0.75 * n)))
    r = Bus(None, [], [tx], cpu=cpu).go(10 + (len(bits) + 4) * n + 40).result()
    assert [x & 1 for x in r.received[:98]] == frame_bits(ident, data) and r.received[98:] == [0, 0] and tx.acked


def test_the_receiver_at_125k_on_50_mhz():
    """400 clocks a bit, the longest rate here: the receiver fits, 248 words, and takes the frame."""
    ident, data = 0x6B5, [0x00, 0xFF, 0x55, 0xAA, 0x0F, 0xF0, 0x12, 0xED]
    words = assemble(gen.rx(98, 400))
    cpu = CPU(words, gpio_in=1, tx_data=list(POLY))
    bits = on_bus(ident, data)
    tx = Transmitter(bits, 10, 400, len(bits) - GAP - 2, sample=300)
    r = Bus(None, [], [tx], cpu=cpu).go(10 + (len(bits) + 4) * 400 + 40).result()
    assert len(words) == 248 and [x & 1 for x in r.received[:98]] == frame_bits(ident, data) and tx.acked


class Drifting:
    """A bench transmitter whose bit is `period` clocks, a Fraction: bit k covers the clocks from
    floor(at + k * period). Its clock is off from the receiver's by period / n - 1."""

    def __init__(self, bits, at, period):
        self.bits, self.at, self.period, self.i = bits, at, Fraction(period), -1

    def update(self, line):
        self.i += 1
        t = self.i - self.at
        if t < 0:
            return None
        k = int(t / self.period)
        return 0 if k < len(self.bits) and self.bits[k] == 0 else None


def drift_ok(words, bits, n, ppm, want):
    cpu = CPU(words, gpio_in=1, tx_data=list(POLY))
    tx = Drifting(bits, 10, Fraction(n) * (1 + Fraction(ppm, 10 ** 6)))
    r = Bus(None, [], [tx], cpu=cpu).go(10 + (len(bits) + 4) * n * 2).result()
    return [x & 1 for x in r.received[: len(want)]] == want and r.received[len(want) : len(want) + 2] == [0, 0]


def tolerance(words, n, bits, want, step=250):
    """The largest clock error, in ppm, slow and fast, at which the receiver still takes the frame."""
    out = []
    for sign in (1, -1):
        ppm = 0
        while drift_ok(words, bits, n, sign * (ppm + step), want):
            ppm += step
        out.append(ppm)
    return tuple(out)


TOLERANCE = {8: (6500, 2500), 25: (7500, 2250)}  # ppm a transmitter may be slow, fast


def test_no_resynchronisation_bounds_the_clock_error():
    """Every receiver here syncs on the SOF's edge and never again: WAIT has no timeout, so a receiver
    cannot wait for an edge that may not come, and a sample cannot be moved by an edge seen. Against a
    transmitter whose clock is off, a DLC 8 frame is taken only while the drift over the whole frame stays
    inside the sample's margin. Missing: a wait with a timeout, or edge-relative timing."""
    ident, data = 0x123, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
    bits, want = on_bus(ident, data), frame_bits(ident, data)
    got = {n: tolerance(assemble(gen.rx(98, n)), n, bits, want) for n in (8, 25)}
    assert got == TOLERANCE


# --- 8. by the numbers --------------------------------------------------------------------------------


def test_the_stress_programs_by_the_numbers():
    """The words of every program in docs/can-stress.md's table, 8 clocks a bit unless named."""
    sizes = {
        "tx dlc 0..8": len(assemble(gen.tx(8))),
        "tx loop": len(assemble(gen.tx(1, loop=True))),
        "tx ackflag": len(assemble(gen.tx(1, loop=True, ackflag=True))),
        "rx dlc 1": len(assemble(gen.rx(42))),
        "rx dlc 8": len(assemble(gen.rx(98))),
        "rx loop idle": len(assemble(gen.rx(42, loop=True, idle=True))),
        "rx any dlc": len(assemble(gen.rx_dlc())),
        "rx check": len(gen.patched(gen.rx(42, check=True))),
        "arb retry 5a3": len(assemble(gen.arb_retry(0x5A3))),
    }
    assert sizes == {"tx dlc 0..8": 152, "tx loop": 151, "tx ackflag": 170, "rx dlc 1": 35, "rx dlc 8": 55,
                     "rx loop idle": 48, "rx any dlc": 237, "rx check": 76, "arb retry 5a3": 229}
