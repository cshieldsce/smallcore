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
    (Instruction("WAIT", (1,), 0), 0x2001),  # 001 00000 00000001
    (Instruction("WAIT", (255,), 31), 0x3FFF),
    (Instruction("LOAD", (0x55,), 0), 0x4055),  # 010 00000 01010101
    (Instruction("SHIFT_OUT", (), 7), 0x6700),  # 011 00111 00000000
    (Instruction("PULL", (), 0), 0x8000),  # 100 00000 00000000
    (Instruction("PULL", (), 7), 0x8700),
])
def test_encoding(isa, instr, word):
    assert encode(instr, isa) == word
    assert decode(word, isa) == instr


@pytest.mark.parametrize("line", ["SET 2", "WAIT 0", "WAIT 256", "SET 1 [32]", "HALT", "SET", "SET 1 [7",
                                  "LOAD 256", "LOAD", "SHIFT_OUT 1", "PULL 0x55"])
def test_assembler_rejects_bad_lines(line):
    with pytest.raises(SyntaxError):
        assemble(line)


@pytest.mark.parametrize("program", sorted(PROGRAMS.glob("*.asm")), ids=lambda p: p.stem)
def test_every_word_fits_16_bits(program):
    assert all(0 <= w < 1 << 16 for w in load_program(program))


def test_uart_program_is_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_0x55.asm")) == 11


def test_shift_uart_program_is_load_plus_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_shift_0x55.asm")) == 1 + 11


def test_pull_uart_program_is_pull_plus_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_pull.asm")) == 1 + 11
