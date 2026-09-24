"""UART 8N1 protocol checks. These only look at the TX pin: the `tx` fixture
is the single place that knows what drives it, and every check runs against
both programs (bit-banged SETs, and LOAD + SHIFT_OUT)."""

from pathlib import Path

import pytest

from cpu import CPU, load_program

CYCLES_PER_BIT = 8
PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
BITBANG = PROGRAMS / "uart_tx_0x55.asm"
SHIFT = PROGRAMS / "uart_tx_shift_0x55.asm"


def expected_frame(byte):
    """8N1 frame: start bit, 8 data bits LSB first, stop bit."""
    return [0] + [(byte >> i) & 1 for i in range(8)] + [1]


def run(program):
    """Run a program: (pin trace, shift_reg after each cycle)."""
    cpu = CPU(load_program(program))
    shift = []
    while not cpu.halted:
        cpu.step()
        shift.append(cpu.shift_reg)
    return cpu.trace, shift


@pytest.fixture(params=[BITBANG, SHIFT], ids=lambda p: p.stem)
def tx(request):
    """TX pin level for each cycle, and the cycle of the start bit."""
    trace, _ = run(request.param)
    start = trace.index(0)  # first falling edge = start bit
    return trace, start


def test_each_bit_holds_for_exactly_8_cycles(tx, wave):
    trace, start = tx
    frame = expected_frame(0x55)

    names = ["start"] + [f"d{i}" for i in range(8)] + ["stop"]
    labels = ["idle"] * start + [n for n in names for _ in range(CYCLES_PER_BIT)]
    wave.add("pin", trace, group="out")
    wave.add("bit", (labels + ["idle"] * len(trace))[:len(trace)], group="out")

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


def test_shift_program_matches_bitbang_from_start_bit(wave):
    """LOAD + 8 SHIFT_OUTs must put exactly the same levels on the pin as the
    eight hand-written SETs, cycle for cycle from the start bit onward."""
    bitbang, _ = run(BITBANG)
    shift_trace, shift_reg = run(SHIFT)
    wave.add("pin (shift)", shift_trace)
    wave.add("shift_reg", [f"{v:02x}" for v in shift_reg])
    wave.add("pin (bitbang)", bitbang)

    frame = bitbang[bitbang.index(0):]
    assert shift_trace[shift_trace.index(0):] == frame
    assert shift_reg[-1] == 0, "all eight bits were shifted out"
