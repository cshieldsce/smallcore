"""The combined CAN programs: the run test and the accumulator on the whole
frame, the payoff test for both (experiments/combined/, gen.py writes them).
256 words and 8 clocks a bit is the bar.

  6A  can_tx_combined.asm: the data frame unopposed, the pad on the bus, the
      stuffing the run test's, the CRC the accumulator's: the host writes no
      CRC
  6B  can_tx_arb_<ident>.asm: 6A with arbitration. The sent bit beside the
      bus bit and the last five bus bits do not fit in the one register SKIP
      and the run test read, so the identifier is in the program: the
      header's bits and stuff bits are the assembler's, a recessive one
      checks the bus. One program per identifier and DLC
  6C  can_rx_crc.asm: the receiver with three streams for two places, the
      raw history in in_shift_reg, the CRC in acc, the data one bit a byte
      through the FIFO; the ACK pulled whatever the CRC says

The bench is tests/model/test_can.py's Bus with its Frame receiver, a Rival that
stuffs and withdraws the way a node must, and tests/model/test_can_rx.py's
transmitter for the receiver."""

import importlib.util
from pathlib import Path

import pytest

from cpu import CPU, assemble, load_program
from test_can import (  # noqa: E402
    GAP, IDENT, Bus, Frame, Glitch, bits_to_int, cells, frame_bits, frame_host, frame_names, header_bits, stuffed,
)
from test_can_rx import AT, Transmitter, run_rx  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = ROOT / "experiments" / "combined"
_spec = importlib.util.spec_from_file_location("combined_gen", HERE / "gen.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

BIT = 8
SAMPLE = 3  # the clock whose level the transmitters take: the SHIFT_IN on the fourth, 37.5%
POLY = [0x32, 0x8B]  # 0x4599 left-aligned, low byte first
VECTORS = ((0x5A3, 0x5A), (0x7FF, 0xFF), (0x000, 0x00), (0x07C, 0x00), (0x555, 0xAA), (0x123, 0x01))
TX = HERE / "can_tx_combined.asm"
RX = HERE / "can_rx_crc.asm"
ARBITRATION = 12  # SOF, ID[10:0]: the field a lost node leaves on; RTR is the thirteenth, the same for every data frame


def unopposed_bytes(ident, data):
    """6A's host bytes: the polynomial, then the stream without the CRC cut as stage 5A cuts it."""
    bits = frame_bits(ident, data)[:-15]
    padded = bits[:3] + [0] * 5 + bits[3:]
    padded += [0] * (-len(padded) % 8)
    return POLY + [bits_to_int(padded[i : i + 8]) for i in range(0, len(padded), 8)]


def arb_bytes(data):
    """6B's host bytes: the polynomial, then the data a bit late, {d0[7], 0000000}, {d0[6:0], d1[7]}, ..."""
    bits = [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]
    padded = bits[:1] + [0] * 7 + bits[1:] + [0]
    return POLY + [bits_to_int(padded[i : i + 8]) for i in range(0, len(padded), 8)]


def arb_program(ident, dlc=1):
    return assemble(gen.tx_arbitration(ident, dlc, write=False))


class Rival:
    """A second transmitter, ideal: it syncs on the SOF's falling edge and
    drives its whole stuffed frame from there, a bit every BIT clocks, a 0
    driven and a 1 let go, the ACK slot let go; on the SAMPLEth clock of
    each bit of its arbitration field it compares, and a recessive bit seen
    dominant is lost: `lost` is the bus bit, and it drives nothing more."""

    def __init__(self, ident, data):
        self.bits = stuffed(frame_bits(ident, data)) + [1, 1, 1] + [1] * GAP
        names = frame_names(ident, data)
        self.arbitration = names.index("rtr")  # the stuffed index of RTR: the bits before it decide
        self.line, self.clock, self.lost = 1, None, None

    def update(self, line):
        if self.clock is None and line == 0 and self.line == 1:
            self.clock = 0
        elif self.clock is not None:
            self.clock += 1
        self.line = line
        if self.clock is None:
            return None
        k, phase = divmod(self.clock, BIT)
        if phase == SAMPLE and k < self.arbitration and self.lost is None and self.bits[k] == 1 and line == 0:
            self.lost = k
        if self.lost is None and k < len(self.bits) and self.bits[k] == 0:
            return 0
        return None


def run_tx(program, host_bytes, nodes, cycles=3000):
    """The program on the bus with `nodes` for `cycles`, the bus going on
    after the core halts, the pad let go, so a frame the core lost to ends."""
    cpu = CPU(program if isinstance(program, list) else load_program(program), gpio_in=1)
    bus = Bus(None, [], nodes, host=frame_host(host_bytes), cpu=cpu).go(cycles)
    while len(bus.lines) < cycles:
        assert cpu.gpio_oe[0] == 0, "halted with the bus driven"
        drives = [node.update(bus.line) for node in bus.nodes]
        bus.line = 0 if 0 in drives else 1
        bus.lines.append(bus.line)
        bus.owned.append(False)
        bus.txds.append(1)
        bus.driven.append(drives)
        bus.stalls.append(False)
    return bus.result()


def receiver():
    return Frame(sample=SAMPLE, bit=BIT)


def the_frame(r, ident, data):
    """The stuffed stream on the bus from the SOF, bit for bit, each bit held its eight clocks."""
    bits = stuffed(frame_bits(ident, data))
    return cells(r.line, r.line.index(0), len(bits), BIT) == bits


# --- 6A: unopposed ----------------------------------------------------------------------------


@pytest.mark.parametrize("ident, data", VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_the_core_computes_the_crc_the_frame_carries(ident, data):
    """The frame on the bus bit for bit, every bit eight clocks, the CRC in
    it the one the core computed from the bits it sent: the receiver finds
    it right and acks, the host's byte says acked in bit 0, acc is clear,
    the program halted."""
    rx = receiver()
    r = run_tx(TX, unopposed_bytes(ident, [data]), [rx])
    assert the_frame(r, ident, [data])
    got = rx.received[0]
    assert (got.ident, got.data, got.crc_ok, got.acked) == (ident, (data,), True, True)
    assert r.received[-1] & 1 == 0 and r.cpu.acc == 0 and r.cpu.halted


def test_frames_across_the_range():
    """The walking ones and zeros of the identifier with three payloads and every 97th identifier."""
    walking = [1 << i for i in range(11)] + [(1 << 11) - 1 - (1 << i) for i in range(11)]
    for ident, data in [(i, d) for i in walking for d in (0x00, 0xFF, 0x55)] + [(i, i & 0xFF) for i in range(0, 1 << 11, 97)]:
        rx = receiver()
        r = run_tx(TX, unopposed_bytes(ident, [data]), [rx])
        assert the_frame(r, ident, [data]) and rx.received[0].crc_ok and rx.received[0].acked, f"{ident:03x} {data:02x}"


def test_not_acked_the_frame_goes_again_with_the_polynomial_kept():
    """No receiver acks: the host reads 1 in bit 0, queues the frame's bytes
    again, not the polynomial, and the same frame goes out a second time,
    its CRC right: acc was clear, the polynomial kept."""
    ident, data = IDENT, [0x5A]
    bytes_ = unopposed_bytes(ident, data)
    queue = list(bytes_)
    state = {"again": False}

    def host(cpu, received):
        if received and received[0] & 1 and not state["again"]:
            state["again"] = True
            queue.extend(bytes_[2:])
        if queue and len(cpu.tx_fifo) < 4:
            cpu.tx_fifo.append(queue.pop(0))

    rx = Frame(sample=SAMPLE, bit=BIT, ack=[False, True])
    cpu = CPU(load_program(TX), gpio_in=1)
    r = Bus(None, [], [rx], host=host, cpu=cpu).go(3000).result()
    assert [(f.ident, f.crc_ok, f.acked) for f in rx.received] == [(ident, True, False), (ident, True, True)]
    assert [b & 1 for b in r.received] == [1, 0] and r.cpu.halted


def test_the_transmitter_reads_the_second_clock_for_the_crc_and_the_third_for_stuffing():
    """A probe on a recessive data bit whose four before it are mixed, at each
    of its eight clocks. Only two clocks matter. A pulse on the second is
    the level ACC_CRC on the third takes: the bits on the bus are the
    frame's up to the CRC, and the CRC is wrong. A pulse on the third is the
    level the SHIFT_IN on the fourth takes into the stuffing's history: the
    frame breaks. On the first clock the CRC once read a bus still
    settling, and a rival a clock behind broke the winner's CRC."""
    ident, data = IDENT, [0x5A]
    bits = stuffed(frame_bits(ident, data))
    k = next(k for k in range(14, 25) if bits[k] == 1 and len(set(bits[k - 4 : k])) == 2)
    base = run_tx(TX, unopposed_bytes(ident, data), [receiver()])
    sof = base.line.index(0)
    head = frame_names(ident, data).index("crc14")  # the bus bits before the CRC
    broken = []
    for p in range(BIT):
        r = run_tx(TX, unopposed_bytes(ident, data), [receiver(), Glitch(sof + k * BIT + p)])
        got = r.nodes[0].received
        if not (got and got[0].crc_ok):
            broken.append(p + 1)
        if p == 1:
            assert [r.line[sof + j * BIT + 7] for j in range(head)] == bits[:head] and got and not got[0].crc_ok
    assert broken == [2, 3]


def test_the_unopposed_transmitter_by_the_numbers():
    """152 words, 64 distinct, for stage 5A's 233 at 16 clocks a bit and a
    host-computed CRC; 8 clocks a bit throughout; the host writes 2 bytes
    once and 3 + DLC a frame for 5 + DLC."""
    words = load_program(TX)
    assert (len(words), len(set(words))) == (152, 64)
    assert len(unopposed_bytes(IDENT, [0x5A])) - 2 == 4


# --- 6B: arbitration ----------------------------------------------------------------------------


@pytest.mark.parametrize("ident, data", VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_unopposed_the_arbitrating_transmitter_sends_the_frame(ident, data):
    """6B for the identifier, alone on the bus: the same frame as 6A's, bit
    for bit, the CRC right, acked, one byte to the host."""
    rx = receiver()
    r = run_tx(arb_program(ident), arb_bytes([data]), [rx])
    assert the_frame(r, ident, [data])
    assert rx.received[0].crc_ok and rx.received[0].acked and len(r.received) == 1 and r.cpu.halted


def rivals(ident):
    """For each recessive bit of the identifier, the identifier that differs
    from it first there, dominant: the rival that wins on that bit; and the
    identifiers that lose to it on each dominant bit."""
    lower = [ident & ~(1 << i) for i in range(11) if (ident >> i) & 1]
    higher = [ident | (1 << i) for i in range(11) if not (ident >> i) & 1]
    return lower, higher


@pytest.mark.parametrize("ident", (0x5A3, 0x7FF, 0x555, 0x07C), ids=lambda i: f"{i:03x}")
def test_a_lower_rival_wins_on_each_recessive_bit(ident):
    """A rival that differs first on one of the identifier's recessive bits,
    dominant there: the transmitter lets go on that bit and drives nothing
    after it, the rival's frame goes through whole to the receiver, CRC
    right, and the host reads the two bytes that say lost."""
    lower, _ = rivals(ident)
    for other in lower:
        rx, rival = receiver(), Rival(other, [0x33])
        r = run_tx(arb_program(ident), arb_bytes([0x5A]), [rival, rx])
        assert rival.lost is None and [(f.ident, f.crc_ok) for f in rx.received] == [(other, True)], f"{ident:03x} against {other:03x}"
        assert len(r.received) == 2 and r.cpu.halted
        sof = r.line.index(0)
        first = next(k for k in range(12) if header_bits(ident)[k] != header_bits(other)[k])
        j = len(stuffed(header_bits(ident)[: first + 1])) - 1  # the bus bit: the prefix's stuff bits before it
        assert not any(r.owned[sof + j * BIT :]), f"{ident:03x} against {other:03x}: let go on bus bit {j} for good"


@pytest.mark.parametrize("ident", (0x5A3, 0x000, 0x555, 0x07C), ids=lambda i: f"{i:03x}")
def test_a_higher_rival_loses_on_each_dominant_bit(ident):
    """A rival that differs first on one of the identifier's dominant bits,
    recessive there: it withdraws on that bit, and the transmitter's frame
    goes through whole, acked."""
    _, higher = rivals(ident)
    for other in higher:
        rx, rival = receiver(), Rival(other, [0x33])
        r = run_tx(arb_program(ident), arb_bytes([0x5A]), [rival, rx])
        assert rival.lost is not None, f"{ident:03x} against {other:03x}"
        assert [(f.ident, f.crc_ok, f.acked) for f in rx.received] == [(ident, True, True)] and len(r.received) == 1


def test_one_program_per_identifier_fits_for_every_identifier():
    """The identifier in the program costs the header written out: a
    recessive bit five words, a dominant three, a stuff bit two or four.
    Every one of the 2048 identifiers with DLC 1 fits in 256 words: 210 for
    0x000 to 228 for 0x7FF."""
    sizes = [len(arb_program(ident)) for ident in range(1 << 11)]
    assert (min(sizes), max(sizes)) == (206, 228), (min(sizes), max(sizes))
    assert (sizes[0x000], sizes[0x5A3], sizes[0x7FF]) == (210, 214, 228)


# --- 6C: the receiver --------------------------------------------------------------------------


def rx_run(ident, data, crc=None, host=None, drain=True):
    cpu = CPU(load_program(RX), gpio_in=1, tx_data=list(POLY))
    if crc is None:
        return run_rx(None, ident, [data], cpu=cpu, host=host, drain=drain)
    bits = stuffed(frame_bits(ident, [data], crc=crc)) + [1, 1, 1] + [1] * GAP
    tx = Transmitter(bits, AT, BIT, len(bits) - GAP - 2)
    return Bus(None, [], [tx], cpu=cpu).go(AT + (len(bits) + 4) * BIT + 40).result(), tx


@pytest.mark.parametrize("ident, data", VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_the_receiver_checks_the_crc_in_the_core(ident, data):
    """Bit 0 of the first 42 bytes is the destuffed stream; the two after
    it, the CRC residue, are 0 and 0: the CRC matched; the ACK pulled; no
    stall; halted."""
    r, tx = rx_run(ident, data)
    assert [b & 1 for b in r.received[:42]] == frame_bits(ident, [data])
    assert r.received[42:] == [0, 0] and tx.acked and not any(r.stalls[AT + 1 :]) and r.cpu.halted


def test_a_wrong_crc_leaves_a_residue_and_is_acked_anyway():
    """A transmitter that sends a wrong CRC: the residue the host reads is
    not 0, and the ACK slot was pulled all the same. A receiver acks only a
    frame whose CRC matched, and this one cannot: the residue is in acc,
    and the only way from acc to the pc is a pin and a sample a bit,
    fifteen of them, where the CRC delimiter leaves eight clocks."""
    right = frame_bits(IDENT, [0x5A])[-15:]
    for wrong in (bits_to_int(right) ^ 1, bits_to_int(right) ^ 0x4000, 0x1234):
        r, tx = rx_run(IDENT, 0x5A, crc=wrong)
        assert r.received[42:] != [0, 0] and tx.acked is True, hex(wrong)


def test_the_receiver_by_the_numbers():
    """35 words, 25 distinct; 8 clocks a bit; 44 pops a frame, and the host
    still bound to four bit times, the FIFO a bit a byte."""
    words = load_program(RX)
    assert (len(words), len(set(words))) == (35, 25)
    first = AT + 6 + 2  # the first PUSH: the sample, the CRC, then the PUSH
    for sleep, fine in ((4, True), (5, False)):
        def host(cpu, received, sleep=sleep):
            if cpu.cycle >= first + sleep * BIT and cpu.rx_fifo:
                received.append(cpu.rx_fifo.pop(0))
        r, _ = rx_run(IDENT, 0x5A, host=host, drain=False)
        ok = not any(r.stalls[AT + 1 :]) and [b & 1 for b in r.received[:42]] == frame_bits(IDENT, [0x5A])
        assert ok == fine, f"asleep {sleep} bit times"
