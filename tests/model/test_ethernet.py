"""10BASE-T on Protocol Engine v2, programs only (experiments/ethernet/, gen.py
writes them). Nothing in the ISA, the model or the RTL changes. The report is
docs/ethernet-10baset.md.

Staged smallest first:

  1. Manchester TX of a fixed byte, the waveform checked at the pin;
  2. the clock: 10 Mb/s is 100 ns a bit, C = f / 10 MHz clocks a bit; each
     transmitter and receiver shape is tried at 20..100 MHz and the edge
     error measured;
  3. preamble and SFD, from the program and from the host;
  4. a whole frame streamed from the host FIFO, 64 and 1518 bytes, the host
     bounded by a 4-deep FIFO;
  5. the frame's end (TP_IDL, TX_EN low) and normal link pulses when idle;
  6. CRC-32: the host's FCS; what the core would need;
  7. receive: fixed sampling after one WAIT, and re-aligning on every
     mid-bit edge, over a sweep of phase and of frequency offset;
  8. collision detection and carrier sense.

Conventions. IEEE 802.3 Manchester: a 0 is high then low, a 1 low then high,
the second half is the bit; bytes LSB first. TX pins: gpio 0 TD, gpio 2
TX_EN (a line driver's enable: TX_EN low is the idle wire), gpio_in 1 RD,
the squelched receive pair, 0 while quiet. The on-core encoder puts TD on
gpio 3 and uses pad 0 as scratch. RX programs listen on gpio_in 0.

The bench is the pads: every cycle gpio_in[k] is gpio[k] where the pad is
driven (the chip's pad readback) and the outside world where it is let go.
A pin trace entry k is the level from clock edge k to k + 1. A receiver's
line is a continuous-time waveform sampled at the clock edges: gpio_in 0
before cycle k is the level at time k (in clocks), a transition at time e
seen from the first k >= e.
"""

import importlib.util
import math
import zlib
from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, assemble, load_isa, load_program

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = ROOT / "experiments" / "ethernet"
_spec = importlib.util.spec_from_file_location("ethernet_gen", HERE / "gen.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

ISA = load_isa()
TD, RD, TX_EN, TD_R = gen.TD, gen.RD, gen.TX_EN, gen.TD_R
DEPTH = 4  # the RTL's FIFOs, both
PREAMBLE = [0x55] * 7 + [0xD5]
END = 0xFF  # the host's end marker: a first bit cell of two highs
RESIDUE = 0x2144DF1C  # zlib.crc32 over a frame with its FCS appended, when the FCS is right


def program(name):
    return load_program(HERE / f"{name}.asm", ISA)


def lsb_bits(data):
    return [(byte >> i) & 1 for byte in data for i in range(8)]


def from_bits(bits):
    return [sum(b << i for i, b in enumerate(bits[k:k + 8])) for k in range(0, len(bits) - 7, 8)]


def manchester(bits):
    return [h for b in bits for h in (1 - b, b)]


def host_encode(data):
    """Data bytes as the host's half-bit bytes: two per data byte, bit 2i of a
    host byte the first half of data bit i, bit 2i + 1 its second half."""
    halves = manchester(lsb_bits(data))
    return [sum(h << i for i, h in enumerate(halves[k:k + 8])) for k in range(0, len(halves), 8)]


def fcs(data):
    return list(zlib.crc32(bytes(data)).to_bytes(4, "little"))


def frame(n, seed=1):
    """An n-byte Ethernet frame with the FCS the host computed: destination,
    source, EtherType, a payload of a fixed pseudo-random pattern."""
    body = [0xFF] * 6 + [0x02, 0x00, 0x5E, 0x10, 0x00, 0x01] + [0x88, 0xB5]
    x = seed
    while len(body) < n - 4:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        body.append((x >> 16) & 0xFF)
    return body + fcs(body)


def tx_host_bytes(data):
    """What the host queues for eth_tx_*: preamble, SFD and the frame encoded,
    then the end marker."""
    return host_encode(PREAMBLE + data) + [END]


# ---------------------------------------------------------------------------
# the transmit bench


class Tx(NamedTuple):
    td: list  # TD per cycle
    en: list  # TX_EN per cycle
    stalls: list  # per cycle: was the core stalled
    status: list  # bytes the host popped
    cpu: CPU
    pushes: list  # the cycle of every host push
    pcs: list  # per cycle: the pc as the cycle began


def label(name, which):
    """The address of `which:` in experiments/ethernet/<name>.asm."""
    address = 0
    for line in (HERE / f"{name}.asm").read_text().splitlines():
        code = line.split("#", 1)[0].strip()
        if ":" in code:
            here, code = code.split(":", 1)
            if here.strip() == which:
                return address
            code = code.strip()
        if code:
            address += 1
    raise KeyError(which)


def run_tx(prog, host_bytes, cycles, td=TD, depth=DEPTH, sleep=None, rd=None):
    """`prog` with a host that keeps the TX FIFO topped up to `depth` from
    `host_bytes`, except for `sleep` = (start, length) cycles, and pops the RX
    FIFO at once. The pads read back; RD (gpio_in 1) is `rd(cycle)` or 0."""
    cpu = CPU(prog, gpio_in=0, isa=ISA)
    queue = list(host_bytes)
    tds, ens, stalls, status, pushes, pcs = [], [], [], [], [], []

    def pads():
        for k in range(4):
            cpu.gpio_in[k] = cpu.gpio[k] if cpu.gpio_oe[k] else 0
        if not cpu.gpio_oe[RD]:
            cpu.gpio_in[RD] = rd(cpu.cycle) if rd else 0

    pads()
    for _ in range(cycles):
        if cpu.halted:
            break
        asleep = sleep and sleep[0] <= cpu.cycle < sleep[0] + sleep[1]
        while not asleep and queue and len(cpu.tx_fifo) < depth:
            cpu.tx_fifo.append(queue.pop(0))
            pushes.append(cpu.cycle)
        pcs.append(cpu.pc)
        cpu.step()
        pads()
        tds.append(cpu.gpio[td])
        ens.append(cpu.gpio[TX_EN])
        stalls.append(cpu.stalled)
        while cpu.rx_fifo:
            status.append(cpu.rx_fifo.pop(0))
    return Tx(tds, ens, stalls, status, cpu, pushes, pcs)


class Wave(NamedTuple):
    bits: list  # decoded, from bit 0 until the first cell that is not a bit
    errors: list  # ns, each TD edge while TX_EN is high against a 50 ns grid on bit 0's mid-bit edge
    start: int  # the cycle TX_EN rose
    stop: int  # the cycle TX_EN fell, or None
    anchor: float  # ns, bit 0's mid-bit edge
    tail: int  # clocks TD stayed high after the last bit's mid-bit, before TX_EN fell


def analyse(td, en, mhz, which=0):
    """Frame `which` on the pins, one TX_EN-high stretch: decode it on the ideal
    10 Mb/s grid anchored at bit 0's mid-bit edge, the first TD edge after
    TX_EN rises, and measure every TD edge against the 50 ns grid."""
    tc = 1000 / mhz
    rises = [k for k in range(1, len(en)) if en[k] and not en[k - 1]]  # the reset level is not a frame
    start = rises[which]
    stop = next((k for k in range(start, len(en)) if not en[k]), None)
    end = stop if stop is not None else len(en)
    edges = [k for k in range(start + 1, end) if td[k] != td[k - 1]]
    anchor = edges[0] * tc

    def level(t):
        return td[math.floor(t / tc + 1e-9)]

    bits = []
    j = 0
    while True:
        t1, t2 = anchor + 100 * j - 25, anchor + 100 * j + 25
        if t2 >= end * tc:
            break
        a, b = level(t1), level(t2)
        if a == b:
            break
        bits.append(b)
        j += 1
    errors = [((k * tc - anchor + 25) % 50) - 25 for k in edges]
    last_mid = anchor + 100 * (len(bits) - 1)
    tail = round((end * tc - last_mid) / tc) if bits and bits[-1] == 1 else None
    return Wave(bits, errors, start, stop, anchor, tail)


def frame_bytes(bits):
    """The bytes after the preamble and SFD in a decoded bit stream, which must
    start with them whole; None if it does not."""
    if bits[:64] != lsb_bits(PREAMBLE):
        return None
    return from_bits(bits[64:])


def cycles_for(nbytes, c):
    return (len(PREAMBLE) + nbytes + 4) * 8 * c + 400


# ---------------------------------------------------------------------------
# the generator and the committed programs


NAMES = (
    ["eth_tx_fixed", "eth_tx_preamble", "eth_nlp"]
    + [f"eth_tx_{m}" for m in gen.TX_CLOCKS]
    + [f"eth_txr_{m}" for m in gen.TXR_CLOCKS]
    + [f"eth_rx_fixed_{m}" for m in gen.RX_CLOCKS]
    + [f"eth_rx_track_{m}" for m in gen.TRACK_CLOCKS]
)


def generated(name):
    if name == "eth_tx_fixed":
        return gen.tx_fixed(write=False)
    if name == "eth_tx_preamble":
        return gen.tx_preamble(write=False)
    if name == "eth_nlp":
        return gen.nlp(write=False)
    kind, mhz = name.rsplit("_", 1)
    return {"eth_tx": gen.tx_host, "eth_txr": gen.tx_raw, "eth_rx_fixed": gen.rx_fixed, "eth_rx_track": gen.rx_track}[kind](
        int(mhz), write=False)


@pytest.mark.parametrize("name", NAMES)
def test_the_committed_programs_are_the_generators(name):
    """Every .asm under experiments/ethernet/ is what gen.py writes today, and
    fits one program's 256 words."""
    assert (HERE / f"{name}.asm").read_text() == generated(name)
    assert len(program(name)) <= 256


# ---------------------------------------------------------------------------
# the receive bench


def rx_levels(bits, c, phase=0.0, ppm=0.0, idle=40, tp_idl=3):
    """The line a receiver sees, one level per clock: quiet (0) for `idle` +
    `phase` clocks, then `bits` Manchester-encoded with half-bits of c / 2
    clocks on the transmitter's clock, `ppm` fast (+) or slow (-) against
    the core's, then TP_IDL high for `tp_idl` bit times and quiet again. The
    level before cycle k is the line at time k."""
    th = (c / 2) / (1 + ppm * 1e-6)
    t0 = idle + phase
    halves = manchester(bits) + [1] * (2 * tp_idl)
    n = math.ceil(t0 + len(halves) * th) + 8 * c
    levels = []
    for k in range(n):
        i = math.floor((k - t0) / th) if k >= t0 else -1
        levels.append(halves[i] if 0 <= i < len(halves) else 0)
    return levels


class Rx(NamedTuple):
    received: list  # bytes the host popped
    stalls: list  # cycles the core stalled on a PUSH
    cpu: CPU


def run_rx(prog, levels, extra=200, sleep=None):
    """`prog` with `levels` on pad 0, let go by the program, and a host that
    pops the RX FIFO at once except for `sleep` = (start, length)."""
    cpu = CPU(prog, gpio_in=0, isa=ISA)
    received, stalls = [], []
    for k in range(len(levels) + extra):
        if cpu.halted:
            break
        cpu.gpio_in[0] = cpu.gpio[0] if cpu.gpio_oe[0] else (levels[k] if k < len(levels) else 0)
        cpu.step()
        if cpu.stalled and len(cpu.rx_fifo) >= cpu.rx_depth:
            stalls.append(k)
        asleep = sleep and sleep[0] <= k < sleep[0] + sleep[1]
        while cpu.rx_fifo and not asleep:
            received.append(cpu.rx_fifo.pop(0))
    return Rx(received, stalls, cpu)


def good(received, data, inverted=False):
    """How many bytes of `data` came through in order from the first."""
    got = [b ^ 0xFF for b in received] if inverted else received
    n = 0
    while n < len(data) and n < len(got) and got[n] == data[n]:
        n += 1
    return n


def receive(kind, mhz, data, phase=0.0, ppm=0.0, **kw):
    c = mhz // 10
    levels = rx_levels(lsb_bits(PREAMBLE + data), c, phase, ppm)
    r = run_rx(program(f"eth_rx_{kind}_{mhz}"), levels, **kw)
    return good(r.received, data, kind == "track"), r


# ---------------------------------------------------------------------------
# 1. Manchester TX of a fixed byte


@pytest.mark.parametrize("byte", (0xA5, 0x00, 0xFF))
def test_a_fixed_byte_is_ieee_manchester_at_the_pin(byte):
    """eth_tx_fixed at 40 MHz: TX_EN rises with bit 0's first half and TD
    carries 16 half-bits of exactly 2 clocks, a 0 high then low, a 1 low
    then high, LSB first; then TD stays high 12 clocks (TP_IDL, 300 ns)
    after the last half-bit and TX_EN falls; the program halts."""
    prog = assemble(gen.tx_fixed(byte, write=False), ISA)
    t = run_tx(prog, [], 200)
    assert t.cpu.halted
    start = t.en.index(1, 1)
    halves = manchester(lsb_bits([byte]))
    assert t.td[start:start + 32] == [h for h in halves for _ in range(2)]
    assert t.en[start:start + 44] == [1] * 44 and t.en[start + 44] == 0
    assert t.td[start + 32:start + 44] == [1] * 12
    w = analyse(t.td, t.en, 40)
    assert from_bits(w.bits) == [byte] and set(w.errors) == {0.0}


def test_the_convention_is_the_second_half_is_the_bit():
    """IEEE 802.3 against G.E. Thomas: in 0xA5, bit 0 is a 1 and goes out low
    then high; bit 1 is a 0 and goes out high then low."""
    t = run_tx(program("eth_tx_fixed"), [], 200)
    start = t.en.index(1, 1)
    assert t.td[start:start + 8] == [0, 0, 1, 1, 1, 1, 0, 0]


# ---------------------------------------------------------------------------
# 2. the clock: the host-encoded transmitter at every rate


TX_EDGE_ERROR = {40: 0, 50: 10, 60: 0, 80: 0, 100: 0}  # ns, the worst TD edge against the 50 ns grid


@pytest.mark.parametrize("mhz", sorted(TX_EDGE_ERROR))
def test_the_host_encoded_transmitter_at_each_clock(mhz):
    """eth_tx_<mhz>: a 64-byte frame goes out whole, preamble, SFD, data and
    the host's FCS, no stall while TX_EN is high, status 'sent'. The edges
    sit on the 50 ns grid at 40, 60, 80 and 100 MHz; at 50 MHz, 5 clocks a
    bit, the halves are 3 and 2 clocks and every bit boundary is 10 ns off
    (60 / 40 ns halves, 10 ns of duty distortion)."""
    data = frame(64)
    t = run_tx(program(f"eth_tx_{mhz}"), tx_host_bytes(data), cycles_for(64, mhz // 10))
    w = analyse(t.td, t.en, mhz)
    assert frame_bytes(w.bits) == data
    assert zlib.crc32(bytes(data)) == RESIDUE
    assert not any(t.stalls[w.start:w.stop])
    assert max(abs(e) for e in w.errors) == pytest.approx(TX_EDGE_ERROR[mhz], abs=1e-6)
    assert [s >> 7 for s in t.status] == [0]


def test_at_20_mhz_the_pull_and_the_jmp_have_no_clock():
    """eth_tx_20, one clock a half-bit: 8 SHIFT_OUTs, the PULL and the JMP
    are 10 clocks for 8 half-bits, so the 8th half-bit of every host byte
    lasts 3 clocks, 150 ns for 50: the stream runs at 8 Mb/s and the first
    host byte's S8 already breaks the decode. The record of why 20 MHz fails."""
    data = frame(64)
    host = tx_host_bytes(data)
    t = run_tx(program("eth_tx_20"), host, 400)
    start = t.en.index(1, 1)
    ideal = manchester(lsb_bits(PREAMBLE + data))  # one clock a half-bit
    got = t.td[start:start + 40]
    assert got[:8] == ideal[:8]  # S1..S7 right, and S8 starts on time
    assert got[7:10] == [ideal[7]] * 3  # S8 held through the JMP and the PULL
    assert got[10:18] == ideal[8:16]  # the next host byte right, two clocks late
    inside = [p for p in t.pushes if p > start]
    assert {b - a for a, b in zip(inside, inside[1:])} == {10}  # 10 clocks a host byte of 8 half-bits
    assert len(analyse(t.td, t.en, 20).bits) < 64  # not even the preamble decodes


TXR_EDGE_ERROR = {50: 10, 60: 0, 80: 0}


@pytest.mark.parametrize("mhz", sorted(TXR_EDGE_ERROR))
def test_manchester_from_raw_bytes_on_the_core(mhz):
    """eth_txr_<mhz>: the host sends plain bytes and the core encodes, the
    next bit read back through the scratch pad and a SKIP choosing the next
    block. 50 MHz fits with halves of 3 and 2 (the same 10 ns error as the
    host-encoded transmitter), 60 and 80 exactly. It has no end: the PULL
    after the last byte stalls in bit 7 with TX_EN high, so the last bit is
    never finished and the frame is broken."""
    data = PREAMBLE + frame(64)
    t = run_tx(program(f"eth_txr_{mhz}"), data, cycles_for(64, mhz // 10), td=TD_R)
    w = analyse(t.td, t.en, mhz)
    assert from_bits(w.bits) == data[:-1]  # every byte but the last
    assert len(w.bits) == 8 * len(data) - 1  # bit 7 of the last byte never gets its first half
    assert max(abs(e) for e in w.errors) == pytest.approx(TXR_EDGE_ERROR[mhz], abs=1e-6)
    assert w.stop is None and t.cpu.stalled  # TX_EN still high, the core on the PULL


def test_manchester_from_raw_bytes_at_40_mhz_is_one_clock_a_byte_short():
    """eth_txr_40: 4 clocks a bit is exactly SHIFT_OUT, SHIFT_IN, SKIP, JMP;
    bit 7's block needs the PULL as well, a fifth clock, so one first half a
    byte is 75 ns, 25 ns off the grid: 33 clocks a byte where 40 MHz has 32."""
    data = PREAMBLE + frame(64)
    t = run_tx(program("eth_txr_40"), data, cycles_for(64, 4), td=TD_R)
    w = analyse(t.td, t.en, 40)
    assert max(abs(e) for e in w.errors) == pytest.approx(25)
    assert len(w.bits) < 64


# ---------------------------------------------------------------------------
# 3. preamble and SFD


def test_preamble_and_sfd_from_the_program():
    """eth_tx_preamble: 7 x 0x55 and 0xD5, 64 bits, every edge on the grid,
    from 10 words: the 62 alternating bits are one REPEAT of a two-word pair."""
    t = run_tx(program("eth_tx_preamble"), [], 600)
    w = analyse(t.td, t.en, 40)
    assert w.bits == lsb_bits(PREAMBLE)
    assert set(w.errors) == {0.0}
    assert t.cpu.halted and len(program("eth_tx_preamble")) == 10


# ---------------------------------------------------------------------------
# 4. streaming a whole frame from the host


@pytest.mark.parametrize("n", (64, 1518))
def test_a_whole_frame_streams_without_a_gap(n):
    """eth_tx_40 with a host that keeps the 4-deep TX FIFO topped up: 64 and
    1518 bytes go out whole, every edge on the grid, the core never stalls
    while TX_EN is high. The host writes 2 bytes a data byte: one every
    16 clocks, 400 ns, 2.5 MB/s."""
    data = frame(n)
    t = run_tx(program("eth_tx_40"), tx_host_bytes(data), cycles_for(n, 4))
    w = analyse(t.td, t.en, 40)
    assert frame_bytes(w.bits) == data
    assert not any(t.stalls[w.start:w.stop])
    assert set(w.errors) == {0.0}
    inside = [p for p in t.pushes if w.start <= p < w.stop]
    gaps = {b - a for a, b in zip(inside, inside[1:])}
    assert gaps == {16}  # the host's steady rate inside the frame: a push every 16 clocks


def max_host_sleep(n=64, mhz=40):
    """The longest the host may stop pushing, from any cycle inside the frame,
    without a stall while TX_EN is high: the worst case over one host byte's
    16 starting clocks."""
    data = frame(n)
    host = tx_host_bytes(data)
    c = mhz // 10
    prog = program(f"eth_tx_{mhz}")
    best = None
    for offset in range(16):
        lo, hi = 0, 200
        while lo < hi:  # the longest sleep with no stall in the frame
            mid = (lo + hi + 1) // 2
            t = run_tx(prog, host, cycles_for(n, c), sleep=(400 + offset, mid))
            w = analyse(t.td, t.en, mhz)
            if any(t.stalls[w.start:w.stop]) or frame_bytes(w.bits) != data:
                hi = mid - 1
            else:
                lo = mid
        best = lo if best is None else min(best, lo)
    return best


def test_the_host_may_sleep_63_clocks_inside_a_frame():
    """With the FIFO topped up, the host may stop for 63 clocks at the worst
    moment, 1.575 us, 15 bit times: the sleep starts as a PULL takes a byte,
    three are left for the PULLs 16, 32 and 48 clocks on, and the one at 64
    needs the host back. At 64 the PULL stalls with TD held and the frame is
    broken: a late host is a broken frame, as in CAN."""
    assert max_host_sleep() == 63


# ---------------------------------------------------------------------------
# 5. the frame's end, and link pulses


def test_the_end_marker_is_tp_idl_then_idle():
    """The host's 0xFF after the FCS: its first cell, two highs, is no data
    bit; the program sees it two clocks in, holds TD high 300 ns from the
    end of the last bit (TP_IDL), drops TX_EN and pushes a status byte with
    bit 7 clear. The last bit of the FCS ends exactly where the frame's
    4-clock bits say it does."""
    data = frame(64)
    t = run_tx(program("eth_tx_40"), tx_host_bytes(data), cycles_for(64, 4))
    w = analyse(t.td, t.en, 40)
    last_end = w.start + 4 * 8 * (len(PREAMBLE) + len(data))
    assert t.td[last_end:w.stop] == [1] * 12 and w.stop - last_end == 12
    assert len(t.status) == 1 and t.status[0] >> 7 == 0


def test_back_to_back_frames_and_the_gap_between_them_is_the_hosts():
    """Two frames queued at once go out as two frames, each decoded whole,
    two 'sent' statuses. The gap the program leaves is GAP clocks: 802.3's
    9.6 us inter-frame gap is the host's to keep by queueing later (a
    program could time it only with unrolled RD samples: not built)."""
    a, b = frame(64, seed=1), frame(64, seed=2)
    t = run_tx(program("eth_tx_40"), tx_host_bytes(a) + tx_host_bytes(b), 2 * cycles_for(64, 4))
    first, second = analyse(t.td, t.en, 40, 0), analyse(t.td, t.en, 40, 1)
    assert frame_bytes(first.bits) == a and frame_bytes(second.bits) == b
    assert [x >> 7 for x in t.status] == [0, 0]
    assert second.start - first.stop == GAP


GAP = 14  # clocks TX_EN is low between two frames queued back to back
NLP_PERIOD = 639_581  # clocks from one link pulse's rise to the next


def test_normal_link_pulses_every_16_ms_while_idle():
    """eth_nlp at 40 MHz: TX_EN high for 4 clocks (100 ns) with TD high, then
    NLP_PERIOD clocks to the next, 16 ms, inside 802.3's 16 +- 8 ms: an inner
    REPEAT of 39 NOP [31] under a Johnson counter in in_shift_reg, 16
    states, kept through pad 3 read back."""
    cpu = CPU(program("eth_nlp"), gpio_in=0, isa=ISA)
    rises, en_prev, widths, width = [], 0, [], 0
    while len(rises) < 3:
        cpu.step()
        cpu.gpio_in[3] = cpu.gpio[3]
        en = cpu.gpio[TX_EN]
        if en:
            width += 1
            assert cpu.gpio[TD] == 1
        if en and not en_prev:
            rises.append(cpu.cycle)
        if en_prev and not en:
            widths.append(width)
            width = 0
        en_prev = en
    assert widths[:2] == [4, 4]
    assert rises[1] - rises[0] < NLP_PERIOD  # the first wait is 8 counter states from reset, not 16
    assert rises[2] - rises[1] == NLP_PERIOD
    assert 8 <= NLP_PERIOD / 40e3 <= 24


def test_one_repeat_waits_at_most_6_5_ms_at_40_mhz():
    """Without a counter kept in in_shift_reg, the longest wait a 256-word
    program has is one REPEAT of 255 NOP [31]: 261 152 clocks, 6.53 ms at
    40 MHz, short of the 8 ms the NLP interval allows at the least. REPEAT
    does not nest and counts to 32; the delay field holds 31."""
    prog = assemble("wait: NOP [31]\n" + "NOP [31]\n" * 254 + "REPEAT 32, wait\n", ISA)
    assert len(prog) == 256
    cpu = CPU(prog, isa=ISA)
    cpu.run(max_cycles=300_000)
    assert cpu.cycle == 261_152 and cpu.cycle / 40e3 < 8


def test_an_idle_transmitter_is_a_stalled_pull_and_sends_no_pulses():
    """eth_tx_40 with nothing queued waits on its PULL with every pin frozen:
    a program can wait for the host or count time, not both, since nothing
    asks the FIFO whether a byte is there without stalling on it. Link
    pulses between frames are the host's (a restart into eth_nlp) or a
    timer's outside."""
    t = run_tx(program("eth_tx_40"), [], 5000)
    assert all(t.stalls[10:]) and set(t.en[1:]) == {0}
    assert t.cpu.pc == label("eth_tx_40", "frame")


# ---------------------------------------------------------------------------
# 6. CRC-32


CRC32_POLY = 0x04C11DB7


def crc_direct(bits, poly, width, init=0):
    """The CRC register in the direct form, as ACC_CRC runs it: f = r[top] ^
    in, r <- (r << 1) ^ (f ? poly : 0)."""
    r, top, mask = init, width - 1, (1 << width) - 1
    for b in bits:
        f = (r >> top) & 1 ^ b
        r = ((r << 1) & mask) ^ (poly if f else 0)
    return r


def acc_crc(bits, poly):
    """The accumulator on the model: the polynomial loaded from the host, low
    byte first, then one ACC_CRC a bit on gpio_in 0, then ACC_PUSH twice."""
    src = "PULL\nACC_LOAD\nPULL\nACC_LOAD\n" + "ACC_CRC 0\n" * len(bits) + "ACC_PUSH\nACC_PUSH\n"
    cpu = CPU(assemble(src, ISA), gpio_in=0, tx_data=[poly & 0xFF, poly >> 8], isa=ISA)
    word = assemble("ACC_CRC 0", ISA)[0]
    feed = iter(bits)
    while not cpu.halted:
        if cpu.program[cpu.pc] == word and cpu.counter == 0:
            cpu.gpio_in[0] = next(feed)
        cpu.step()
    return cpu.rx_fifo[0] | cpu.rx_fifo[1] << 8


def test_the_fcs_is_the_hosts_and_reaches_the_wire_as_sent():
    """The host computes CRC-32 (zlib's, 802.3's) and sends it as the frame's
    last four bytes; the program sends them as data, so timing is untouched.
    The receiver's check on the decoded bytes is the residue. A wrong FCS
    goes out just as faithfully: the core checks nothing."""
    data = frame(64)
    bad = data[:-1] + [data[-1] ^ 0x01]
    for sent, right in ((data, True), (bad, False)):
        t = run_tx(program("eth_tx_40"), tx_host_bytes(sent), cycles_for(64, 4))
        got = frame_bytes(analyse(t.td, t.en, 40).bits)
        assert got == sent
        assert (zlib.crc32(bytes(got)) == RESIDUE) is right


def test_crc32_needs_32_bits_of_state_the_core_has_24():
    """The state a program both writes and reads: in_shift_reg, 8 bits, and
    acc, 16. poly is written only from host bytes (ACC_LOAD) and read by
    nothing but ACC_CRC's feedback. CRC-32's register is 32 bits."""
    import cpu as model

    assert model.ACC_BITS + 8 == 24 < 32


@pytest.mark.parametrize("seed", range(4))
def test_neither_half_of_crc32_is_a_16_bit_crc(seed):
    """The 2 x 16 question, measured: CRC-32's feedback f = r[31] ^ in taps
    both halves of the register (0x04C1 above, 0x1DB7 below), and the high
    half shifts r[15] in. The accumulator with either half as its polynomial
    computes a true 16-bit CRC (it matches the direct form of width 16), and
    it is neither half of CRC-32 over the same bits: each half needs a bit
    of the other every shift, and there is one accumulator."""
    x = seed * 7919 + 1
    bits = []
    for _ in range(48):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        bits.append((x >> 16) & 1)
    r32 = crc_direct(bits, CRC32_POLY, 32)
    for poly, half in ((CRC32_POLY >> 16, r32 >> 16), (CRC32_POLY & 0xFFFF, r32 & 0xFFFF)):
        got = acc_crc(bits, poly)
        assert got == crc_direct(bits, poly, 16)
        assert got != half


def test_the_40_mhz_loop_has_no_clock_for_a_crc():
    """Every clock of the 40 MHz loop issues a new word: 8 SHIFT_OUTs, the
    PULL, the JMP, two TD read-backs, the end check, two RD samples, the
    collision check, 16 clocks for 16 half-bits. Even a 16-bit CRC wants an
    ACC_CRC per data bit, 4 more clocks a host byte."""
    data = frame(64)
    t = run_tx(program("eth_tx_40"), tx_host_bytes(data), cycles_for(64, 4))
    w = analyse(t.td, t.en, 40)
    top, end = label("eth_tx_40", "top"), label("eth_tx_40", "end")
    steady = t.pcs[w.start + 200:w.start + 360]
    assert all(top <= pc < end for pc in steady)
    assert all(steady[k + 1] != steady[k] for k in range(len(steady) - 1))  # a new word every clock


# ---------------------------------------------------------------------------
# 8. collision detection and carrier sense


def collider(start, n=64, seed=9):
    """Another station's frame on RD from cycle `start`, clock-aligned."""
    levels = rx_levels(lsb_bits(PREAMBLE + frame(n, seed)), 4, idle=start)
    return lambda k: levels[k] if k < len(levels) else 0


COLLISION_LATENCY = 19  # clocks, at most over 64 start offsets, from the other station's first high on RD to the jam


@pytest.mark.parametrize("offset", range(0, 64, 5))
def test_a_collision_is_seen_jammed_reported_and_drained(offset):
    """A second station starts `offset` clocks after our TX_EN rises. Two RD
    samples 4 clocks apart each host byte cannot both miss a Manchester
    signal (its longest low is 4 clocks), so the program jumps to the jam
    within COLLISION_LATENCY clocks of the other station's first high: 32
    bits of 0, TP_IDL, TX_EN low, status bit 7 set; it drains our frame's
    remaining host bytes through the end marker with TX_EN low, then sends
    the next frame once RD is quiet."""
    ours, again = frame(64, seed=1), frame(64, seed=3)
    probe = run_tx(program("eth_tx_40"), tx_host_bytes(ours), 200)
    start = probe.en.index(1, 1)
    rd = collider(start + offset)
    t = run_tx(program("eth_tx_40"), tx_host_bytes(ours) + tx_host_bytes(again), 12000, rd=rd)
    first_high = next(k for k in range(20000) if rd(k))
    jam = t.pcs.index(label("eth_tx_40", "collide"))
    assert 0 < jam - first_high <= COLLISION_LATENCY
    assert t.td[jam:jam + 128] == [1, 1, 0, 0] * 32  # 32 bits of 0
    assert [x >> 7 for x in t.status] == [1, 0]
    retry = analyse(t.td, t.en, 40, 1)
    assert frame_bytes(retry.bits) == again
    assert retry.start > max(k for k in range(20000) if rd(k))  # carrier sense: not while the other frame lasts


def test_carrier_sense_defers_while_rd_is_busy():
    """RD busy when the frame is queued: TX_EN stays low until the other frame
    has ended and RD has been quiet for the sense window, then the frame
    goes out whole."""
    rd = collider(0)
    busy_until = max(k for k in range(20000) if rd(k))
    data = frame(64)
    t = run_tx(program("eth_tx_40"), tx_host_bytes(data), 8000, rd=rd)
    w = analyse(t.td, t.en, 40)
    assert w.start > busy_until
    assert frame_bytes(w.bits) == data and [x >> 7 for x in t.status] == [0]


# ---------------------------------------------------------------------------
# 7. receive


PHASES = [k / 16 for k in range(16)]  # the transmitter's start, in fractions of a core clock


def phase_map(kind, mhz, data, ppm=0.0):
    """'.' for each phase at which the whole frame came through, 'x' if not."""
    return "".join("." if receive(kind, mhz, data, ph, ppm)[0] == len(data) else "x" for ph in PHASES)


@pytest.mark.parametrize("mhz", gen.RX_CLOCKS)
def test_fixed_sampling_receives_a_frame_at_every_phase_when_the_clocks_agree(mhz):
    """Idealized RX: the transmitter on the core's frequency, its start swept
    over 16 phases of a clock. eth_rx_fixed: WAIT 0, 0 then WAIT 0, 1 finds a
    preamble rise, the mid-bit of a 1, within a clock of it; every later bit
    is sampled one clock after where its mid-bit edge should be, the SFD is
    the first 1 1 (SKIP_RUN 2, 1), and 64 bytes come through at every phase.
    12 words."""
    assert phase_map("fixed", mhz, frame(64)) == "." * 16


FIXED_64_AT_40 = {100: ".xxx............", 200: ".xxxxxxx........", -100: "." * 16, -200: "." * 16}


@pytest.mark.parametrize("ppm", sorted(FIXED_64_AT_40))
def test_fixed_sampling_at_40_mhz_has_a_phase_window_once_the_clocks_differ(ppm):
    """Even 64 bytes (576 bits) at 40 MHz lose phases to a fast transmitter:
    the sample sits one clock after the edge, as late as 2 clocks at the
    worst phase in a 2-clock half-bit, and 100 ppm moves it 0.23 clocks by
    the FCS. A slow transmitter moves it the safe way over 64 bytes."""
    assert phase_map("fixed", 40, frame(64), ppm) == FIXED_64_AT_40[ppm]


FIXED_1518 = {  # the bytes that came through, at phase 0: none of them is the frame
    (40, 100): 304, (40, -100): 617, (50, 100): 242, (50, -100): 367, (60, 100): 408, (60, -100): 408,
    (80, 100): 461, (80, -100): 304, (100, 100): 492, (100, -100): 242,
}


@pytest.mark.parametrize("mhz,ppm", sorted(FIXED_1518))
def test_fixed_sampling_loses_a_1518_byte_frame_to_100_ppm_at_any_clock(mhz, ppm):
    """100 ppm over a 1518-byte frame (12 208 bits with the preamble) is 1.2
    bit times of drift; a fixed sample point has a quarter bit either way, so
    no clock and no phase saves it (the sweep over 8 phases in
    docs/ethernet-10baset.md: 11 to 617 bytes). The failure is kept: the
    receiver needs to re-align, not a faster clock."""
    n, _ = receive("fixed", mhz, frame(1518), 0.0, ppm)
    assert n == FIXED_1518[(mhz, ppm)] < 1518


def track_margins(c, a):
    """The re-aligning receiver's two margins at its worst phase, in clocks:
    the first-half sample after the bit boundary (a - C / 2), and the fall
    path's WAIT before the next mid-bit edge (C - a - 3: SHIFT_IN, SKIP, the
    JMP, then the WAIT)."""
    return a - c / 2, c - a - 3


def test_re_aligning_on_every_edge_needs_9_clocks_a_bit():
    """Both margins must be above zero, or a phase that walks through the
    bad spot under drift (it walks through every phase in a long frame)
    loses the bit: the smallest C with an a that gives both is 9, 90 MHz.
    6 is the smallest with both at zero (phase-locked only); 4 has none. One
    clock of it is the JMP on the path that does not skip: with a branch
    that lands on the next edge from either side the fall path's WAIT would
    be up a clock sooner and 8 would do."""
    def best(c, jmp=1):
        return max(min(a - c / 2, c - a - 2 - jmp) for a in range(c))

    assert [c for c in range(4, 12) if best(c) > 0][0] == 9
    assert [c for c in range(4, 12) if best(c) >= 0][0] == 6
    assert [c for c in range(4, 12) if best(c, jmp=0) > 0][0] == 7
    assert track_margins(9, gen.track_offset(9)) == (0.5, 1)
    assert track_margins(10, gen.track_offset(10)) == (1, 1)
    assert track_margins(8, gen.track_offset(8)) == (0, 1) and track_margins(8, 5) == (1, 0)
    assert track_margins(6, gen.track_offset(6)) == (0, 0)


def test_re_aligning_at_50_mhz_works_at_7_phases_in_16():
    """eth_rx_track_50, 5 clocks a bit: the first-half sample 2 clocks after
    the edge is past the boundary (2.5 clocks on) only when the edge fell
    late enough in its clock: 7 phases of 16 with the clocks equal."""
    assert phase_map("track", 50, frame(64)) == ".xxxxxxxx......."


def zeros_frame(n=1518):
    """Runs of 0 bits: the payload all 0x00, every mid-bit edge a fall."""
    body = [0xFF] * 6 + [0x02, 0x00, 0x5E, 0x10, 0x00, 0x01, 0x88, 0xB5] + [0x00] * (n - 18)
    return body + fcs(body)


@pytest.mark.parametrize("mhz", (90, 100))
@pytest.mark.parametrize("ppm", (100, -100, 200, -200))
@pytest.mark.parametrize("payload", ("random", "zeros"))
def test_re_aligning_at_90_and_100_mhz_holds_a_1518_byte_frame(mhz, ppm, payload):
    """eth_rx_track_90 and _100: every mid-bit edge re-aligns the next sample,
    so a 1518-byte frame comes through with the transmitter 100 or 200 ppm
    off either way, at two phases, with a random payload and with 1500 zero
    bytes (every edge a fall, the late path). 58 words; the byte is the
    data's complement, the host inverts it."""
    data = frame(1518) if payload == "random" else zeros_frame()
    for phase in (0.0, 0.5):
        n, r = receive("track", mhz, data, phase, ppm)
        assert n == 1518
        assert r.received[0] == data[0] ^ 0xFF  # inverted on the core


LOST = {  # a zero margin, and the frame lost at phase 0
    ("eth_rx_track_80", "random", -100): 304,  # the sample on the boundary: a slow transmitter
    ("eth_rx_track_80_a5", "zeros", 100): 460,  # the fall path's WAIT on the edge: a fast one, runs of 0
    ("eth_rx_track_60", "zeros", 100): 617,  # both margins zero
    ("eth_rx_track_60", "random", -100): 1033,
}


@pytest.mark.parametrize("name,payload,ppm", sorted(LOST))
def test_re_aligning_at_60_and_80_mhz_loses_lock_on_a_zero_margin(name, payload, ppm):
    """The failures kept. At 80 MHz a = 4 puts the first-half sample on the
    boundary at the worst phase, and a slow transmitter walks the phase onto
    it; a = 5 puts the fall path's WAIT on the next edge, and a fast
    transmitter's early falls, in a run of 0 bits, find the WAIT late, which
    then issues on a level that is already there and never catches up. The
    same program keeps a random payload, whose rises re-align it."""
    data = frame(1518) if payload == "random" else zeros_frame()
    mhz = int(name.split("_")[3])
    levels = rx_levels(lsb_bits(PREAMBLE + data), mhz // 10, 0.0, ppm)
    r = run_rx(program(name), levels)
    assert good(r.received, data, inverted=True) == LOST[(name, payload, ppm)] < 1518
    if name == "eth_rx_track_80_a5":
        r = run_rx(program(name), rx_levels(lsb_bits(PREAMBLE + frame(1518)), 8, 0.0, ppm))
        assert good(r.received, frame(1518), inverted=True) == 1518


RX_SLEEP = {"eth_rx_fixed_40": 128, "eth_rx_track_90": 222}  # clocks the host may stop popping, worst case


@pytest.mark.parametrize("name", sorted(RX_SLEEP))
def test_the_receiving_host_may_sleep_about_three_bytes(name):
    """A byte every 8 bits through a 4-deep RX FIFO: a PUSH that finds it full
    stalls the receiver mid-frame, which then samples late. The host may
    stop popping for RX_SLEEP clocks from its worst moment: 3.2 us at 40
    MHz, 2.5 us at 90 MHz; the host pops 1.25 MB/s all through the frame."""
    mhz = int(name.split("_")[-1])
    inverted = "track" in name
    data = frame(64)
    levels = rx_levels(lsb_bits(PREAMBLE + data), mhz // 10)
    worst = None
    for offset in range(0, 8 * (mhz // 10), 3):
        for sleep, ok in ((RX_SLEEP[name], True), (RX_SLEEP[name] + 1, None)):
            r = run_rx(program(name), levels, sleep=(1500 + offset, sleep))
            fine = good(r.received, data, inverted) == 64 and not r.stalls
            if ok:
                assert fine
            elif not fine:
                worst = offset
    assert worst is not None  # one clock more breaks it at some offset


def test_the_receiver_does_not_see_the_frame_end():
    """The frame ends when the carrier goes quiet, and no instruction waits
    for "no edge for a while": eth_rx_fixed_40 goes on sampling the quiet
    line and pushing bytes, TP_IDL's ones and then zeros, forever;
    eth_rx_track_90 stalls in a WAIT for a mid-bit edge that never comes,
    mid-byte, and takes the next frame's preamble as data. Both are for one
    frame: the host must restart them, and learn the length from the frame."""
    data = frame(64)
    r = run_rx(program("eth_rx_fixed_40"), rx_levels(lsb_bits(PREAMBLE + data), 4), extra=400)
    assert r.received[:64] == data and len(r.received) > 64 and r.received[-4:] == [0] * 4
    one = lsb_bits(PREAMBLE + data)
    levels = rx_levels(one, 9) + [0] * 870 + rx_levels(one, 9, idle=0)  # 9.6 us quiet between two frames
    r = run_rx(program("eth_rx_track_90"), levels)
    assert good(r.received, data, inverted=True) == 64
    assert good(r.received[64:], data, inverted=True) == 0  # the second frame is garbage


# ---------------------------------------------------------------------------
# by the numbers


WORDS = {
    "eth_tx_fixed": 20, "eth_tx_preamble": 10, "eth_tx_20": 11, "eth_tx_40": 48, "eth_tx_50": 48,
    "eth_tx_100": 48, "eth_txr_40": 94, "eth_txr_50": 94, "eth_txr_60": 94, "eth_nlp": 51,
    "eth_rx_fixed_40": 12, "eth_rx_track_50": 53, "eth_rx_track_60": 57, "eth_rx_track_90": 58,
}


def test_ethernet_by_the_numbers():
    """The words each program takes, for docs/ethernet-10baset.md: the whole
    host-encoded transmitter, carrier sense, end marker, TP_IDL, collision,
    jam and drain, is 48; the on-core encoder 94, two blocks per bit
    position; the re-aligning receiver 58, a cell per bit and a fall block
    per bit. Nothing is near 256."""
    assert {name: len(program(name)) for name in WORDS} == WORDS


def test_carrier_sense_samples_must_be_a_half_bit_apart():
    """The first carrier sense took RD four times 3 clocks apart, and let a
    frame out into a busy wire (the collision test at offsets 20 and 50
    caught it): a 4-clock low run, a 0 then a 1, holds two samples 3 apart,
    and the other two can land in 2-clock lows. A high run is never shorter
    than a half-bit, 2 clocks, so samples 2 apart always see one."""
    rd = collider(0)
    busy = range(0, max(k for k in range(20000) if rd(k)) - 12)
    assert any(not any(rd(t + 3 * i) for i in range(4)) for t in busy)
    assert all(any(rd(t + 2 * i) for i in range(4)) for t in busy)
