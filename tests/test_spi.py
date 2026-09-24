"""SPI mode 0 master transmit checks. The `frame` fixture is the only place that
knows which gpio pin is which; every check watches the three pins like a slave
would: CS frames the transfer, MOSI is sampled on each rising edge of SCLK."""

from pathlib import Path

import pytest

from cpu import CPU, load_program

PROGRAM = Path(__file__).resolve().parent.parent / "programs" / "spi_tx.asm"
MOSI, SCLK, CS = 0, 1, 2  # gpio pins the program drives
BYTES = (0x00, 0x01, 0x55, 0x80, 0xA3, 0xFF)


def run(tx_data):
    """Run spi_tx.asm to its end: (mosi, sclk, cs) traces, one level per cycle."""
    cpu = CPU(load_program(PROGRAM), tx_data=tx_data)
    cpu.run()
    return cpu.pin_trace(MOSI), cpu.pin_trace(SCLK), cpu.pin_trace(CS)


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


@pytest.fixture(params=BYTES, ids=lambda b: f"{b:#04x}")
def frame(request):
    """(byte to send, mosi, sclk, cs, cycle CS falls, cycle CS rises again)."""
    byte = request.param
    mosi, sclk, cs = run([byte])
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    return byte, mosi, sclk, cs, start, end


def test_cs_frames_exactly_eight_clocks(frame, wave):
    byte, mosi, sclk, cs, start, end = frame
    wave.add("cs", cs, group="spi")
    wave.add("sclk", sclk, group="spi")
    wave.add("mosi", mosi, group="spi")
    edges = rising_edges(sclk)
    labels = ["-"] * len(mosi)
    for i, edge in enumerate(edges):
        labels[edge] = f"d{i}"
    wave.add("sample", labels)

    assert start < end
    assert cs[start:end] == [0] * (end - start), "CS stays low through the frame"
    assert cs[end:] == [1] * (len(cs) - end), "CS stays high after the frame"
    assert len(edges) == 8 and all(start < e < end for e in edges)


def test_clock_idles_low_outside_the_frame(frame):
    _, _, sclk, _, start, end = frame
    assert sclk[start] == 0 and sclk[end - 1] == 0, "clock low when CS moves"
    assert set(sclk[end:]) == {0}, "clock idle low after the frame"
    assert not any(e >= end for e in rising_edges(sclk) + falling_edges(sclk))


def test_mosi_is_stable_while_the_clock_is_high(frame):
    _, mosi, sclk, _, start, end = frame
    for i in range(start + 1, end):
        if sclk[i] == 1:
            assert mosi[i] == mosi[i - 1], f"MOSI changed at cycle {i} with SCLK high"


def test_mosi_settles_before_each_rising_edge(frame):
    _, mosi, sclk, _, _, _ = frame
    for edge in rising_edges(sclk):
        assert mosi[edge - 1] == mosi[edge], f"MOSI still moving on the sampling edge at cycle {edge}"


def test_slave_samples_the_supplied_byte_lsb_first(frame):
    byte, mosi, sclk, _, _, _ = frame
    bits = [mosi[e] for e in rising_edges(sclk)]
    assert sum(bit << i for i, bit in enumerate(bits)) == byte


def test_program_is_three_instructions_per_bit():
    words = load_program(PROGRAM)
    assert len(words) == 3 + 8 * 3 + 2  # setup, 8 x (clock low, shift, clock high), teardown


def test_frame_length_and_bit_period():
    """Every bit is 9 cycles: 1 (clock low) + 4 (SHIFT_OUT [3]) + 4 (SET 1, 1 [3])."""
    _, sclk, cs = run([0xA5])
    edges = rising_edges(sclk)
    assert [b - a for a, b in zip(edges, edges[1:])] == [9] * 7
    assert rising_edges(cs)[0] - falling_edges(cs)[0] == 4 + 8 * 9 + 4


def test_program_waits_for_a_byte_with_cs_high():
    cpu = CPU(load_program(PROGRAM))
    cpu.run_cycles(20)
    assert cpu.stalled and cpu.gpio[CS] == 1 and cpu.gpio[SCLK] == 0
    cpu.tx_fifo.append(0x3C)
    cpu.run()
    mosi, sclk = cpu.pin_trace(MOSI), cpu.pin_trace(SCLK)
    assert sum(mosi[e] << i for i, e in enumerate(rising_edges(sclk))) == 0x3C
