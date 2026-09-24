"""UART 8N1 protocol checks. These only look at the TX pin: the `tx` fixture
is the single place that knows what drives it."""

from pathlib import Path

import pytest

from cpu import CPU, load_program

CYCLES_PER_BIT = 8
PROGRAM = Path(__file__).resolve().parent.parent / "programs" / "uart_tx_0x55.asm"


def expected_frame(byte):
    """8N1 frame: start bit, 8 data bits LSB first, stop bit."""
    return [0] + [(byte >> i) & 1 for i in range(8)] + [1]


@pytest.fixture
def tx():
    """TX pin level for each cycle, and the cycle of the start bit."""
    trace = CPU(load_program(PROGRAM)).run()
    start = trace.index(0)  # first falling edge = start bit
    return trace, start


def test_each_bit_holds_for_exactly_8_cycles(tx, wave):
    trace, start = tx
    frame = expected_frame(0x55)

    names = ["idle"] + ["start"] + [f"d{i}" for i in range(8)] + ["stop"]
    wave.add("pin", trace, group="out")
    wave.add("bit", [n for n in names for _ in range(CYCLES_PER_BIT)][:len(trace)], group="out")

    for i, bit in enumerate(frame):
        lo = start + i * CYCLES_PER_BIT
        window = trace[lo:lo + CYCLES_PER_BIT]
        assert window == [bit] * CYCLES_PER_BIT, f"bit {i}: cycles {lo}..{lo + 7} = {window}"

    # Uniform windows alone would also pass for longer bits. Check that the
    # level changes exactly on each bit boundary (where the frame changes).
    for i in range(1, len(frame)):
        edge = start + i * CYCLES_PER_BIT
        if frame[i] != frame[i - 1]:
            assert trace[edge - 1] != trace[edge], f"no transition at bit {i} (cycle {edge})"


def test_line_idles_high_before_start_bit(tx):
    trace, start = tx
    assert start > 0
    assert trace[:start] == [1] * start


def test_line_idles_high_after_stop_bit(tx):
    trace, start = tx
    end = start + len(expected_frame(0x55)) * CYCLES_PER_BIT
    assert len(trace) >= end, "trace ends before the stop bit completes"
    assert trace[end:] == [1] * (len(trace) - end)


def test_decodes_as_0x55(tx):
    trace, start = tx
    samples = [trace[start + i * CYCLES_PER_BIT + CYCLES_PER_BIT // 2] for i in range(10)]
    assert samples[0] == 0 and samples[9] == 1
    assert sum(bit << i for i, bit in enumerate(samples[1:9])) == 0x55
