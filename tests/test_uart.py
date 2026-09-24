from pathlib import Path

import pytest

from cpu import CPU, Instruction, assemble, decode, encode, load_isa, load_program

CYCLES_PER_BIT = 8
PROGRAM = Path(__file__).resolve().parent.parent / "programs" / "uart_tx_0x55.asm"


def expected_frame(byte):
    """8N1 frame: start bit, 8 data bits LSB first, stop bit."""
    return [0] + [(byte >> i) & 1 for i in range(8)] + [1]


@pytest.fixture(scope="module")
def isa():
    return load_isa()


@pytest.fixture
def run():
    cpu = CPU(load_program(PROGRAM))
    cpu.pcs = []  # pc of the instruction executing in each cycle
    while not cpu.halted:
        cpu.pcs.append(cpu.pc)
        cpu.step()
    trace = cpu.trace
    start = trace.index(0)  # first falling edge = start bit
    return cpu, trace, start


def test_each_bit_holds_for_exactly_8_cycles(run, wave):
    cpu, trace, start = run
    frame = expected_frame(0x55)

    names = ["idle"] + ["start"] + [f"d{i}" for i in range(8)] + ["stop"]
    wave.add("pc", cpu.pcs)
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

    # The program ends right after the stop bit's 8 cycles.
    assert len(trace) == start + len(frame) * CYCLES_PER_BIT
    assert cpu.halted
    assert cpu.pin == 1


def test_line_idles_high_before_start_bit(run):
    _, trace, start = run
    assert start > 0
    assert trace[:start] == [1] * start


def test_decodes_as_0x55(run):
    _, trace, start = run
    samples = [trace[start + i * CYCLES_PER_BIT + CYCLES_PER_BIT // 2] for i in range(10)]
    assert samples[0] == 0 and samples[9] == 1
    assert sum(bit << i for i, bit in enumerate(samples[1:9])) == 0x55


def test_uart_program_is_one_instruction_per_bit():
    assert len(load_program(PROGRAM)) == 11


def test_wait_takes_n_cycles():
    cpu = CPU(assemble("SET 0\nWAIT 3\nSET 1"))
    assert cpu.run() == [0, 0, 0, 0, 1]


def test_delay_adds_cycles():
    assert CPU(assemble("SET 0 [3]\nSET 1")).run() == [0, 0, 0, 0, 1]
    assert CPU(assemble("SET 0\nWAIT 2 [3]\nSET 1")).run() == [0] * 6 + [1]


def test_program_end_halts():
    cpu = CPU(assemble("SET 0 [1]"))
    assert cpu.run() == [0, 0]
    assert cpu.halted
    with pytest.raises(RuntimeError):
        cpu.step()


@pytest.mark.parametrize("instr, word", [
    (Instruction("SET", (0,), 0), 0x0000),
    (Instruction("SET", (1,), 7), 0x0E01),   # 00 00111 000000001
    (Instruction("WAIT", (1,), 0), 0x4001),  # 01 00000 000000001
    (Instruction("WAIT", (511,), 31), 0x7FFF),
])
def test_encoding(isa, instr, word):
    assert encode(instr, isa) == word
    assert decode(word, isa) == instr


def test_every_word_fits_16_bits():
    assert all(0 <= w < 1 << 16 for w in load_program(PROGRAM))


def test_decode_rejects_spare_opcodes(isa):
    with pytest.raises(ValueError):
        decode(0x8000, isa)
    with pytest.raises(ValueError):
        decode(0xC000, isa)


@pytest.mark.parametrize("line", ["SET 2", "WAIT 0", "WAIT 512", "SET 1 [32]", "HALT", "SET", "SET 1 [7"])
def test_assembler_rejects_bad_lines(line):
    with pytest.raises(SyntaxError):
        assemble(line)
