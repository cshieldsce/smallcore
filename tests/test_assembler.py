from pathlib import Path

import pytest

from cpu import Instruction, assemble, decode, encode, load_isa, load_program

PROGRAM = Path(__file__).resolve().parent.parent / "programs" / "uart_tx_0x55.asm"


@pytest.fixture(scope="module")
def isa():
    return load_isa()


@pytest.mark.parametrize("instr, word", [
    (Instruction("SET", (0,), 0), 0x0000),
    (Instruction("SET", (1,), 7), 0x0E01),   # 00 00111 000000001
    (Instruction("WAIT", (1,), 0), 0x4001),  # 01 00000 000000001
    (Instruction("WAIT", (511,), 31), 0x7FFF),
])
def test_encoding(isa, instr, word):
    assert encode(instr, isa) == word
    assert decode(word, isa) == instr


@pytest.mark.parametrize("line", ["SET 2", "WAIT 0", "WAIT 512", "SET 1 [32]", "HALT", "SET", "SET 1 [7"])
def test_assembler_rejects_bad_lines(line):
    with pytest.raises(SyntaxError):
        assemble(line)


def test_every_word_fits_16_bits():
    assert all(0 <= w < 1 << 16 for w in load_program(PROGRAM))


def test_uart_program_is_one_instruction_per_bit():
    assert len(load_program(PROGRAM)) == 11
