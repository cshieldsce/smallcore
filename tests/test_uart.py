"""UART 8N1 protocol checks. These only look at the TX pin, gpio 0: the `tx`
fixture is the single place that knows what drives it, and every check runs against
every program (bit-banged SETs, PULL + SHIFT_OUT with the byte supplied from
outside the program, and the same looped with JMP to stream any number of
bytes)."""

from pathlib import Path

import pytest

from cpu import CPU, decode, load_isa, load_program

CYCLES_PER_BIT = 8
TX = 0  # gpio pin the programs transmit on
PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
BITBANG = PROGRAMS / "uart_tx_0x55.asm"
PULL = PROGRAMS / "uart_tx_pull.asm"
LOOP = PROGRAMS / "uart_tx_loop.asm"

# (program, byte it must send, bytes put in the TX FIFO). The bit-banged
# program has 0x55 baked in; the PULL and LOOP programs send whatever they
# are given.
CASES = ([(BITBANG, 0x55, [])] + [(PULL, b, [b]) for b in (0x00, 0x55, 0xA3, 0xFF)]
         + [(LOOP, b, [b]) for b in (0x00, 0xA3)])


def expected_frame(byte):
    """8N1 frame: start bit, 8 data bits LSB first, stop bit."""
    return [0] + [(byte >> i) & 1 for i in range(8)] + [1]


def run(program, tx_data=()):
    """Run a program until it halts, or stalls on PULL with nothing left to
    send: (TX pin trace, shift_reg after each cycle)."""
    cpu = CPU(load_program(program), tx_data=tx_data)
    shift = []
    while not cpu.halted and not cpu.stalled:
        cpu.step()
        shift.append(cpu.shift_reg)
    return cpu.pin_trace(TX), shift


def decode_frame(trace, start):
    """Sample mid-bit like a receiver would: (byte, cycle after the stop bit)."""
    samples = [trace[start + i * CYCLES_PER_BIT + CYCLES_PER_BIT // 2] for i in range(10)]
    assert samples[0] == 0 and samples[9] == 1, "framing"
    return sum(bit << i for i, bit in enumerate(samples[1:9])), start + 10 * CYCLES_PER_BIT


@pytest.fixture(params=CASES, ids=lambda c: f"{c[0].stem}-{c[1]:#04x}")
def tx(request):
    """(TX pin level for each cycle, cycle of the start bit, byte that should be on the line)."""
    program, byte, tx_data = request.param
    trace, _ = run(program, tx_data)
    start = trace.index(0)  # first falling edge = start bit
    return trace, start, byte


def test_each_bit_holds_for_exactly_8_cycles(tx, wave):
    trace, start, byte = tx
    frame = expected_frame(byte)

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
    trace, start, _ = tx
    assert start > 0
    assert trace[:start] == [1] * start


def test_line_idles_high_after_stop_bit(tx):
    trace, start, byte = tx
    end = start + len(expected_frame(byte)) * CYCLES_PER_BIT
    assert len(trace) >= end, "trace ends before the stop bit completes"
    assert trace[end:] == [1] * (len(trace) - end)


def test_decodes_as_the_supplied_byte(tx):
    trace, start, byte = tx
    assert decode_frame(trace, start)[0] == byte


def test_shift_register_program_matches_bitbang_from_start_bit(wave):
    """8 SHIFT_OUTs after a PULL must put exactly the same levels on the pin
    as the eight hand-written SETs, cycle for cycle from the start bit."""
    bitbang, _ = run(BITBANG)
    shift_trace, shift_reg = run(PULL, tx_data=[0x55])
    wave.add("pin (shift)", shift_trace)
    wave.add("shift_reg", [f"{v:02x}" for v in shift_reg])
    wave.add("pin (bitbang)", bitbang)

    frame = bitbang[bitbang.index(0):]
    assert shift_trace[shift_trace.index(0):] == frame
    assert shift_reg[-1] == 0, "all eight bits were shifted out"


def test_loop_program_streams_every_fifo_byte_then_stalls_high(wave):
    """The milestone: one program, two bytes in the FIFO, two frames on the
    line that decode as those bytes, then the CPU stalls on PULL with TX high."""
    tx_data = [0x55, 0xA3]
    cpu = CPU(load_program(LOOP), tx_data=tx_data)
    pcs = []
    while not cpu.stalled:
        cpu.step()
        pcs.append(cpu.pc)
    trace = cpu.pin_trace(TX)
    wave.add("pin", trace, group="out")
    wave.add("pc", pcs)

    # Walk the line like a receiver: each frame starts at the next falling edge.
    decoded, end = [], 0
    for _ in tx_data:
        start = trace.index(0, end)
        assert trace[end:start] == [1] * (start - end), "idle high between frames"
        byte, end = decode_frame(trace, start)
        decoded.append(byte)
    assert decoded == tx_data

    # Afterwards: stalled on the PULL, FIFO empty, line high and staying high.
    assert cpu.stalled and not cpu.halted
    assert decode(cpu.program[cpu.pc], cpu.isa).op == "PULL"
    assert cpu.tx_fifo == []
    assert cpu.gpio[TX] == 1 and trace[end:] == [1] * (len(trace) - end)
    cpu.run_cycles(50)
    trace = cpu.pin_trace(TX)
    assert cpu.stalled and trace[end:] == [1] * (len(trace) - end)


def test_loop_program_resumes_when_a_byte_arrives_later():
    cpu = CPU(load_program(LOOP), tx_data=[0x0F])
    while not cpu.stalled:
        cpu.step()
    cpu.run_cycles(20)  # idle high, still stalled
    assert cpu.stalled and set(cpu.pin_trace(TX)[-20:]) == {1}
    cpu.tx_fifo.append(0xF0)  # the outside world feeds the FIFO
    before = len(cpu.trace)
    cpu.step()  # the PULL completes on this cycle
    assert not cpu.stalled and cpu.shift_reg == 0xF0
    while not cpu.stalled:
        cpu.step()
    frame = cpu.pin_trace(TX)[before:]
    assert decode_frame(frame, frame.index(0))[0] == 0xF0


def test_uart_programs_rely_on_the_lsb_first_reset_direction():
    """UART is LSB first and no UART program has to say so: shift_dir resets
    to 0 and only CONFIG_SHIFT changes it."""
    isa = load_isa()
    for program in (BITBANG, PULL, LOOP):
        assert all(decode(w, isa).op != "CONFIG_SHIFT" for w in load_program(program))
    cpu = CPU(load_program(LOOP), tx_data=[0xA3])
    assert cpu.shift_dir == 0
    while not cpu.stalled:
        cpu.step()
    assert cpu.shift_dir == 0


def test_pull_program_is_independent_of_its_data():
    """The same program words send different bytes: only the FIFO changes."""
    words = load_program(PULL)
    frames = {b: run(PULL, [b])[0] for b in (0x00, 0xA3, 0xFF)}
    assert len(set(map(tuple, frames.values()))) == 3
    assert load_program(PULL) == words
