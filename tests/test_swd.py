"""SWD host checks, staged the way SPI and I2C were: the smallest piece of the
protocol first, and the core is assumed able until a piece proves otherwise.
Stage 1, programs/swd_request.asm: the host owns SWDIO and clocks the 8-bit
request out, LSB first, and nothing else. No turnaround, no ACK, no data, no
parity from the core: the host composes the whole request byte. The bench is
the target: it samples SWDIO on every rising edge of SWCLK and reads what it
saw as a request packet, start, stop and park bits and the parity included."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
REQUEST = PROGRAMS / "swd_request.asm"
SWDIO, SWCLK = 0, 1  # gpio pins the program drives: SWDIO is the shift pin
HIGH = 4  # cycles SWCLK is high per bit, and low
BIT = 2 * HIGH


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
    swdio: list  # one level per cycle, as the host drove it
    swclk: list
    cpu: CPU


def run(byte):
    """Run the program to its end with `byte` waiting in the TX FIFO."""
    cpu = CPU(load_program(REQUEST), tx_data=[byte])
    cpu.run()
    return Run(cpu.pin_trace(SWDIO), cpu.pin_trace(SWCLK), cpu)


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def sampled(swdio, swclk):
    """What the target shifts in: SWDIO on every rising edge of SWCLK, in order."""
    return [swdio[e] for e in rising_edges(swclk)]


def show(wave, r):
    wave.add("swclk", r.swclk, group="host drives")
    wave.add("swdio", r.swdio, group="host drives")
    labels = ["-"] * len(r.swdio)
    for name, edge in zip(FIELDS, rising_edges(r.swclk)):
        labels[edge] = name
    wave.add("target samples", labels)


@pytest.fixture(params=REQUESTS, ids=lambda r: f"{'ap' if r[0] else 'dp'}_{'read' if r[1] else 'write'}_a{r[2]:02b}")
def packet(request):
    return Packet(*request.param)


def test_target_samples_the_request_lsb_first(packet, wave):
    """Every request a host can make reaches the target field for field: the
    eight samples are the byte's bits from bit 0 up, and decode back to the
    APnDP, RnW and A[3:2] the host asked for. Most requests are not
    palindromes, so MSB first would fail the start, stop or parity check."""
    byte = request(*packet)
    r = run(byte)
    show(wave, r)
    bits = sampled(r.swdio, r.swclk)
    assert bits == wire_bits(byte)
    assert target_decode(bits) == packet


def test_dp_write_to_a01_is_0xa9_on_the_wire():
    """One request by hand. A DP write to A[3:2] = 01: Start 1, APnDP 0, RnW 0,
    A2 1, A3 0, parity 1, Stop 0, Park 1 is 1 0 0 1 0 1 0 1 on the wire, the
    byte 0xA9 = 1010_1001 read from bit 0. Backwards it is 1 0 1 0 1 0 0 1: a
    bit-order slip cannot pass."""
    assert request(0, 0, 0b01) == 0xA9
    assert sampled(*run(0xA9)[:2]) == [1, 0, 0, 1, 0, 1, 0, 1]


def test_swclk_rises_eight_times_and_idles_low():
    """One rising edge per request bit and no other: SWCLK is low before the
    first bit, low again after the last, and stays there."""
    r = run(0xA9)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    assert len(ups) == 8, f"SWCLK rose at {ups}"
    assert len(downs) == 8 and all(u < d for u, d in zip(ups, downs)), "each rise has its fall"
    assert r.swclk[0] == 0, "SWCLK idle low before the request"
    assert set(r.swclk[downs[-1]:]) == {0}, "SWCLK idle low after the request"


def test_swdio_idles_high_and_is_left_high():
    """The host owns SWDIO throughout. It is high before the request (the start
    bit is a 1, so the line does not move for it), and after the park bit the
    host leaves it high: the place the turnaround will go."""
    r = run(0xA9)
    first, last = rising_edges(r.swclk)[0], rising_edges(r.swclk)[-1]
    assert set(r.swdio[:first]) == {1}, "SWDIO high up to the start bit's sample"
    assert set(r.swdio[last:]) == {1}, "SWDIO high from the park bit on"
    assert r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio_oe[SWCLK] == 1, "both pins driven at the end"


def test_host_drives_swdio_every_cycle():
    """No turnaround yet: gpio_oe[SWDIO] is 1 on every cycle of the run. The
    test stage 2 will have to change."""
    cpu = CPU(load_program(REQUEST), tx_data=[0xA9])
    while not cpu.halted:
        assert cpu.gpio_oe[SWDIO] == 1 and cpu.gpio_oe[SWCLK] == 1
        cpu.step()
    assert cpu.gpio_oe[SWDIO] == 1


@pytest.mark.parametrize("byte", (0xA9, request(1, 1, 0b11), request(0, 1, 0b00)), ids=lambda b: f"{b:#04x}")
def test_each_bit_is_on_swdio_through_the_low_half_and_the_rising_edge(byte):
    """The target samples on the rise, so the bit must be there before it and
    hold through it: on SWDIO for the 4 low cycles before its rising edge and
    the cycle of the edge. Bits are 8 cycles apart, 4 low, 4 high."""
    r = run(byte)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    assert [b - a for a, b in zip(ups, ups[1:])] == [BIT] * 7
    assert [d - u for u, d in zip(ups, downs)] == [HIGH] * 8, "high half"
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
    cpu = CPU(load_program(REQUEST))
    cpu.run_cycles(20)
    assert cpu.stalled and cpu.gpio[SWCLK] == 0 and cpu.gpio[SWDIO] == 1
    cpu.tx_fifo.append(0xA9)
    cpu.run()
    assert sampled(cpu.pin_trace(SWDIO), cpu.pin_trace(SWCLK)) == wire_bits(0xA9)


def test_program_is_two_words_per_bit_lsb_first():
    """Stage 1 costs the core nothing new: SPI's two words per bit, SHIFT_OUT
    with the clock low and SET with it high, LSB first as the core resets."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(REQUEST)]
    assert len(words) == 2 + 8 * 2 + 2  # clock low, pull; 8 x (shift + clock low, clock high); clock low, line high
    assert not any(w.op == "CONFIG" for w in words), "the reset configuration is the SWD one"
    shifts = [w for w in words if w.op == "SHIFT_OUT"]
    assert len(shifts) == 8 and all(w.side == (SWCLK, 0) for w in shifts)
