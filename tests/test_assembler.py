from pathlib import Path

import pytest

from cpu import Instruction, assemble, decode, encode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"


@pytest.fixture(scope="module")
def isa():
    return load_isa()


@pytest.mark.parametrize("instr, word", [
    (Instruction("SET", (0,), 0), 0x0000),
    (Instruction("SET", (1,), 7), 0x0701),   # 000 00111 00000001
    (Instruction("SET", (1,), 31), 0x1F01),  # 000 11111 00000001
    (Instruction("SHIFT_OUT", (), 7), 0x2700),  # 001 00111 00000000
    (Instruction("PULL", (), 0), 0x4000),  # 010 00000 00000000
    (Instruction("PULL", (), 7), 0x4700),
])
def test_encoding(isa, instr, word):
    assert encode(instr, isa) == word
    assert decode(word, isa) == instr


@pytest.mark.parametrize("line", ["SET 2", "SET 1 [32]", "HALT", "SET", "SET 1 [7", "WAIT 1", "LOAD 0x55",
                                  "SHIFT_OUT 1", "PULL 0x55"])
def test_assembler_rejects_bad_lines(line):
    with pytest.raises(SyntaxError):
        assemble(line)


@pytest.mark.parametrize("program", sorted(PROGRAMS.glob("*.asm")), ids=lambda p: p.stem)
def test_every_word_fits_16_bits(program):
    assert all(0 <= w < 1 << 16 for w in load_program(program))


def test_uart_program_is_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_0x55.asm")) == 11


def test_pull_uart_program_is_pull_plus_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_pull.asm")) == 1 + 11
