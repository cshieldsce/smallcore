"""SPI mode 0 master transmit checks, run against both bit orders. The `frame`
fixture is the only place that knows which gpio pin is which; every check
watches the three pins like a slave would: CS frames the transfer, MOSI is
sampled on each rising edge of SCLK. The two programs are the same words apart
from their CONFIG_SHIFT, so the slave must see the same byte in opposite order."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
LSB, MSB = PROGRAMS / "spi_tx_lsb.asm", PROGRAMS / "spi_tx_msb.asm"
MOSI, SCLK, CS = 0, 1, 2  # gpio pins the programs drive
BYTES = (0x00, 0x01, 0x55, 0x80, 0xA3, 0xFF)


def run(program, tx_data):
    """Run a program to its end: (mosi, sclk, cs) traces, one level per cycle."""
    cpu = CPU(load_program(program), tx_data=tx_data)
    cpu.run()
    return cpu.pin_trace(MOSI), cpu.pin_trace(SCLK), cpu.pin_trace(CS)


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def sampled(mosi, sclk):
    """What a mode 0 slave shifts in: MOSI on every rising edge of SCLK, in order."""
    return [mosi[e] for e in rising_edges(sclk)]


def wire_bits(byte, msb_first):
    """The order the bits of `byte` should appear on the wire."""
    bits = [(byte >> i) & 1 for i in range(8)]
    return bits[::-1] if msb_first else bits


class Frame(NamedTuple):
    byte: int
    msb_first: bool
    mosi: list
    sclk: list
    cs: list
    start: int  # cycle CS falls
    end: int  # cycle CS rises again


@pytest.fixture(params=(LSB, MSB), ids=lambda p: p.stem.removeprefix("spi_tx_"))
def program(request):
    return request.param


@pytest.fixture(params=BYTES, ids=lambda b: f"{b:#04x}")
def frame(request, program):
    byte = request.param
    mosi, sclk, cs = run(program, [byte])
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    return Frame(byte, program is MSB, mosi, sclk, cs, start, end)


def test_cs_frames_exactly_eight_clocks(frame, wave):
    wave.add("cs", frame.cs, group="spi")
    wave.add("sclk", frame.sclk, group="spi")
    wave.add("mosi", frame.mosi, group="spi")
    edges = rising_edges(frame.sclk)
    labels = ["-"] * len(frame.mosi)
    for i, edge in enumerate(edges):
        labels[edge] = f"d{7 - i if frame.msb_first else i}"
    wave.add("sample", labels)

    assert frame.start < frame.end
    assert frame.cs[frame.start:frame.end] == [0] * (frame.end - frame.start), "CS stays low through the frame"
    assert frame.cs[frame.end:] == [1] * (len(frame.cs) - frame.end), "CS stays high after the frame"
    assert len(edges) == 8 and all(frame.start < e < frame.end for e in edges)


def test_clock_idles_low_outside_the_frame(frame):
    sclk, start, end = frame.sclk, frame.start, frame.end
    assert sclk[start] == 0 and sclk[end - 1] == 0, "clock low when CS moves"
    assert set(sclk[end:]) == {0}, "clock idle low after the frame"
    assert not any(e >= end for e in rising_edges(sclk) + falling_edges(sclk))


def test_mosi_is_stable_while_the_clock_is_high(frame):
    for i in range(frame.start + 1, frame.end):
        if frame.sclk[i] == 1:
            assert frame.mosi[i] == frame.mosi[i - 1], f"MOSI changed at cycle {i} with SCLK high"


def test_mosi_settles_before_each_rising_edge(frame):
    for edge in rising_edges(frame.sclk):
        assert frame.mosi[edge - 1] == frame.mosi[edge], f"MOSI still moving on the sampling edge at cycle {edge}"


def test_slave_samples_the_supplied_byte_in_the_programs_bit_order(frame):
    assert sampled(frame.mosi, frame.sclk) == wire_bits(frame.byte, frame.msb_first)


def test_0xa3_on_the_wire_lsb_first_then_msb_first():
    """0xA3 = 1010 0011. Sampled on the rising edges, the LSB-first program
    clocks out 1 1 0 0 0 1 0 1 and the MSB-first program 1 0 1 0 0 0 1 1."""
    assert sampled(*run(LSB, [0xA3])[:2]) == [1, 1, 0, 0, 0, 1, 0, 1]
    assert sampled(*run(MSB, [0xA3])[:2]) == [1, 0, 1, 0, 0, 0, 1, 1]


@pytest.mark.parametrize("byte", BYTES, ids=lambda b: f"{b:#04x}")
def test_msb_program_puts_the_lsb_programs_bits_on_the_wire_backwards(byte):
    lsb, msb = sampled(*run(LSB, [byte])[:2]), sampled(*run(MSB, [byte])[:2])
    assert msb == lsb[::-1]
    assert (msb == lsb) == (wire_bits(byte, False) == wire_bits(byte, True)), "only palindromes look the same"


def test_programs_differ_only_in_the_config_shift_operand():
    """Bit order is configuration: the transfer itself is word for word the same."""
    isa = load_isa()
    lsb, msb = load_program(LSB), load_program(MSB)
    assert len(lsb) == len(msb)
    (i,) = [i for i, (a, b) in enumerate(zip(lsb, msb)) if a != b]
    assert decode(lsb[i], isa).op == decode(msb[i], isa).op == "CONFIG_SHIFT"
    assert (decode(lsb[i], isa).args, decode(msb[i], isa).args) == ((0,), (1,))


def test_program_is_two_instructions_per_bit(program):
    words = load_program(program)
    assert len(words) == 4 + 8 * 2 + 2  # config + setup, 8 x (shift + clock low, clock high), teardown


def test_bit_period_is_8_cycles_split_4_low_4_high(program):
    """SHIFT_OUT 1, 0 [3] holds the clock low for 4 cycles with the new bit on
    MOSI, SET 1, 1 [3] holds it high for 4."""
    _, sclk, cs = run(program, [0xA5])
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    ups = rising_edges(sclk)
    downs = [d for d in falling_edges(sclk) if start < d < end]  # the setup drop is before CS
    assert [b - a for a, b in zip(ups, ups[1:])] == [8] * 7
    assert [d - u for u, d in zip(ups, downs)] == [4] * 8, "high half"
    assert [u - d for d, u in zip(downs, ups[1:])] == [4] * 7, "low half"
    assert end - start == 4 + 8 * 8 + 4


def test_each_bit_lands_on_mosi_as_the_clock_drops(frame):
    """Every bit is on MOSI 4 cycles before its rising edge and stays through
    it. From the second bit on, that landing cycle is the cycle the clock
    drops: one edge does both. The first bit finds the clock already low."""
    bits = wire_bits(frame.byte, frame.msb_first)
    for i, up in enumerate(rising_edges(frame.sclk)):
        land = up - 4
        assert frame.mosi[land:up + 1] == [bits[i]] * 5, f"bit {i} on the wire"
        if i:
            assert (frame.sclk[land - 1], frame.sclk[land]) == (1, 0), f"bit {i}: clock did not drop on the landing cycle"


def test_program_waits_for_a_byte_with_cs_high(program):
    cpu = CPU(load_program(program))
    cpu.run_cycles(20)
    assert cpu.stalled and cpu.gpio[CS] == 1 and cpu.gpio[SCLK] == 0
    assert cpu.shift_dir == (program is MSB), "configured before the wait"
    cpu.tx_fifo.append(0x3C)
    cpu.run()
    assert sampled(cpu.pin_trace(MOSI), cpu.pin_trace(SCLK)) == wire_bits(0x3C, program is MSB)
