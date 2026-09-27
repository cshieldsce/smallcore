"""SWD host checks, staged the way SPI and I2C were: the smallest piece of the
protocol first, and the core is assumed able until a piece proves otherwise.
programs/swd_request.asm grows one stage at a time:

  1. the request: the host owns SWDIO and clocks the 8-bit request out, LSB
     first, the host having composed the byte, parity and all;
  2. the turnaround: after the park bit the host lets go of SWDIO for one
     clock, so the target can take the line.

No ACK, no data yet. The bench is the wire and the target. The wire is SWDIO
resolved every cycle from the pad (gpio and gpio_oe) and a pull-up; the
target samples it on every rising edge of SWCLK and reads what it saw as a
request packet, start, stop and park bits and the parity included."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
REQUEST = PROGRAMS / "swd_request.asm"
SWDIO, SWCLK = 0, 1  # the same pin numbers on gpio (the pad) and gpio_in (the wire): SWDIO is the shift pin
HIGH = 4  # cycles SWCLK is high per bit, and low
BIT = 2 * HIGH
CLOCKS = 8 + 1  # rises of SWCLK: the request's eight and the turnaround's


def request(apndp, rnw, a):
    """The 8-bit SWD request as the host writes it into the TX FIFO, bit 0 first
    on the wire: Start 1, APnDP, RnW, A2, A3, the parity of those four, Stop 0,
    Park 1. `a` is A[3:2], the register address the target sees, 0..3."""
    a2, a3 = a & 1, a >> 1
    parity = apndp ^ rnw ^ a2 ^ a3
    return 1 | apndp << 1 | rnw << 2 | a2 << 3 | a3 << 4 | parity << 5 | 0 << 6 | 1 << 7


def wire_bits(byte):
    """The order the bits of `byte` appear on the wire: LSB first."""
    return [(byte >> i) & 1 for i in range(8)]


class Packet(NamedTuple):
    apndp: int
    rnw: int
    a: int  # A[3:2]


FIELDS = ("start", "apndp", "rnw", "a2", "a3", "par", "stop", "park")


def target_decode(bits):
    """What a target makes of eight bits sampled on eight rising edges of SWCLK:
    a request for a register, or a protocol error. Every fixed bit and the
    parity are checked, so a bit-order slip or a dropped bit fails here."""
    assert len(bits) == 8, f"{len(bits)} bits, not 8"
    start, apndp, rnw, a2, a3, parity, stop, park = bits
    assert start == 1, "no start bit"
    assert stop == 0, "no stop bit"
    assert park == 1, "no park bit"
    assert parity == apndp ^ rnw ^ a2 ^ a3, "parity error"
    return Packet(apndp, rnw, a2 | a3 << 1)


REQUESTS = [(apndp, rnw, a) for apndp in (0, 1) for rnw in (0, 1) for a in range(4)]  # every request there is


class Run(NamedTuple):
    swdio: list  # the wire, one level per cycle: the pad while it drives, else the pull-up
    swclk: list  # one level per cycle, as the host drove it
    owned: list  # one per cycle: was the pad driving SWDIO
    cpu: CPU


def run(byte):
    """Run the program to its end with `byte` waiting in the TX FIFO, the wire
    resolved after every cycle and fed back to gpio_in for the next."""
    cpu = CPU(load_program(REQUEST), gpio_in=1, tx_data=[byte])
    swdio, owned = [], []
    while not cpu.halted:
        cpu.step()
        driving = cpu.gpio_oe[SWDIO] == 1
        level = cpu.gpio[SWDIO] if driving else 1
        cpu.gpio_in[SWDIO] = level
        swdio.append(level)
        owned.append(driving)
    return Run(swdio, cpu.pin_trace(SWCLK), owned, cpu)


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def sampled(swdio, swclk):
    """What the target sees: SWDIO on every rising edge of SWCLK, in order. The
    first eight are the request, the ninth is the turnaround's."""
    return [swdio[e] for e in rising_edges(swclk)]


def show(wave, r):
    wave.add("swclk", r.swclk, group="host drives")
    wave.add("swdio", r.swdio, group="wire")
    wave.add("host owns", [int(o) for o in r.owned], group="wire")
    labels = ["-"] * len(r.swdio)
    for name, edge in zip(FIELDS + ("trn",), rising_edges(r.swclk)):
        labels[edge] = name
    wave.add("target samples", labels)


@pytest.fixture(params=REQUESTS, ids=lambda r: f"{'ap' if r[0] else 'dp'}_{'read' if r[1] else 'write'}_a{r[2]:02b}")
def packet(request):
    return Packet(*request.param)


# --- stage 1: the request ------------------------------------------------------


def test_target_samples_the_request_lsb_first(packet, wave):
    """Every request a host can make reaches the target field for field: the
    eight samples are the byte's bits from bit 0 up, and decode back to the
    APnDP, RnW and A[3:2] the host asked for. Most requests are not
    palindromes, so MSB first would fail the start, stop or parity check."""
    byte = request(*packet)
    r = run(byte)
    show(wave, r)
    bits = sampled(r.swdio, r.swclk)[:8]
    assert bits == wire_bits(byte)
    assert target_decode(bits) == packet


def test_dp_write_to_a01_is_0xa9_on_the_wire():
    """One request by hand. A DP write to A[3:2] = 01: Start 1, APnDP 0, RnW 0,
    A2 1, A3 0, parity 1, Stop 0, Park 1 is 1 0 0 1 0 1 0 1 on the wire, the
    byte 0xA9 = 1010_1001 read from bit 0. Backwards it is 1 0 1 0 1 0 0 1: a
    bit-order slip cannot pass."""
    assert request(0, 0, 0b01) == 0xA9
    assert sampled(*run(0xA9)[:2])[:8] == [1, 0, 0, 1, 0, 1, 0, 1]


def test_swclk_rises_once_per_bit_and_once_for_the_turnaround_then_idles_low():
    """Nine rising edges, eight for the request and one for the turnaround, and
    no other: SWCLK is low before the first, low again after the last, and
    stays there."""
    r = run(0xA9)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    assert len(ups) == CLOCKS, f"SWCLK rose at {ups}"
    assert len(downs) == CLOCKS and all(u < d for u, d in zip(ups, downs)), "each rise has its fall"
    assert r.swclk[0] == 0, "SWCLK idle low before the request"
    assert set(r.swclk[downs[-1]:]) == {0}, "SWCLK idle low after the turnaround"


@pytest.mark.parametrize("byte", (0xA9, request(1, 1, 0b11), request(0, 1, 0b00)), ids=lambda b: f"{b:#04x}")
def test_each_bit_is_on_swdio_through_the_low_half_and_the_rising_edge(byte):
    """The target samples on the rise, so the bit must be there before it and
    hold through it: on SWDIO for the 4 low cycles before its rising edge and
    the cycle of the edge. Bits are 8 cycles apart, 4 low, 4 high, and the
    turnaround clock keeps the beat."""
    r = run(byte)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    assert [b - a for a, b in zip(ups, ups[1:])] == [BIT] * (CLOCKS - 1)
    assert [d - u for u, d in zip(ups, downs)] == [HIGH] * CLOCKS, "high half"
    for i, (bit, up) in enumerate(zip(wire_bits(byte), ups)):
        assert r.swdio[up - HIGH:up + 1] == [bit] * (HIGH + 1), f"bit {i} ({FIELDS[i]}) on the wire"
        if i:
            assert (r.swclk[up - HIGH - 1], r.swclk[up - HIGH]) == (1, 0), f"bit {i}: the clock did not drop as the bit landed"


def test_swdio_is_stable_while_swclk_is_high():
    r = run(0xA9)
    for i in range(1, len(r.swdio)):
        if r.swclk[i] == 1:
            assert r.swdio[i] == r.swdio[i - 1], f"SWDIO changed at cycle {i} with SWCLK high"


def test_program_waits_for_the_request_with_the_line_idle():
    """Nothing happens until the host writes a request: the program stalls on
    its PULL with SWCLK low and SWDIO high, then sends the byte that arrives."""
    cpu = CPU(load_program(REQUEST), gpio_in=1)
    cpu.run_cycles(20)
    assert cpu.stalled and cpu.gpio[SWCLK] == 0 and cpu.gpio[SWDIO] == 1 and cpu.gpio_oe[SWDIO] == 1
    cpu.tx_fifo.append(0xA9)
    cpu.run()
    assert [cpu.pin_trace(SWDIO)[e] for e in rising_edges(cpu.pin_trace(SWCLK))][:8] == wire_bits(0xA9)


# --- stage 2: the turnaround ---------------------------------------------------


def test_host_owns_swdio_through_the_park_bit_and_lets_go_as_that_clock_falls(wave):
    """The host drives SWDIO on every cycle of the request, through the park
    bit's rising edge and its high half, and lets go on the edge that drops
    SWCLK after it: from there the pad is not driving, and it stays that way.
    The line reads high meanwhile, from the pull-up, so a bench that only
    watched levels could not tell: `owned` is gpio_oe."""
    r = run(0xA9)
    show(wave, r)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    release = downs[7]  # the clock after the park bit drops
    assert release == ups[7] + HIGH
    assert all(r.owned[:release]), "the host let go before the park bit was clocked"
    assert not any(r.owned[release:]), "the host took the line back"
    assert set(r.swdio[release:]) == {1}, "the pull-up holds the line high while nobody drives"


def test_turnaround_is_one_clock_with_nobody_driving():
    """The ninth rising edge of SWCLK is the turnaround's: the host is not
    driving on the cycles around it, and it is the last clock the host gives
    before it halts, SWCLK back at idle."""
    r = run(0xA9)
    ups = rising_edges(r.swclk)
    trn = ups[8]
    assert not any(r.owned[trn - HIGH:trn + HIGH]), "the host drove SWDIO around the turnaround clock"
    assert r.swdio[trn] == 1
    assert len(ups) == 9 and r.cpu.gpio[SWCLK] == 0 and r.cpu.gpio_oe[SWDIO] == 0


def test_letting_go_is_open_drain_with_a_one_the_park_bit_left():
    """How the host lets go: one CONFIG word makes SWDIO open-drain, and the 1
    the park bit left on gpio[0] is what an open-drain pin does not drive. The
    same word drops SWCLK. Nothing is written to the pin itself."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(REQUEST)]
    od01 = isa["config"]["open_drain01"]["field"]
    (release,) = [i for i, w in enumerate(words) if w.op == "CONFIG"]
    assert words[release].args == (od01, 1) and words[release].side == (SWCLK, 0)
    assert words[release - 1].op == "SET" and words[release - 1].args == (SWCLK, 1), "right after the park bit's clock"
    assert not any(w.op == "SET" and w.args[0] == SWDIO for w in words), "no SET on SWDIO: SHIFT_OUT and the pad mode do it all"


def test_program_is_two_words_per_bit_lsb_first_plus_the_turnaround():
    """Two words per bit, SHIFT_OUT with the clock low and SET with it high, as
    in SPI; no CONFIG shift_dir because the reset configuration, LSB first, is
    SWD's. The turnaround adds two words, let go and clock, and one returns
    the clock to idle."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(REQUEST)]
    assert len(words) == 2 + 8 * 2 + 3  # clock low, pull; 8 x (shift + clock low, clock high); let go + clock low, clock high, clock low
    shift_dir = isa["config"]["shift_dir"]["field"]
    assert not any(w.op == "CONFIG" and w.args[0] == shift_dir for w in words)
    shifts = [w for w in words if w.op == "SHIFT_OUT"]
    assert len(shifts) == 8 and all(w.side == (SWCLK, 0) for w in shifts)
