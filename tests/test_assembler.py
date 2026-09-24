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
    (Instruction("JMP", (0,), 0), 0x6000),  # 011 00000 00000000
    (Instruction("JMP", (1,), 0), 0x6001),
    (Instruction("JMP", (255,), 31), 0x7FFF),  # 011 11111 11111111
])
def test_encoding(isa, instr, word):
    assert encode(instr, isa) == word
    assert decode(word, isa) == instr


@pytest.mark.parametrize("line", ["SET 2", "SET 1 [32]", "HALT", "SET", "SET 1 [7", "WAIT 1", "LOAD 0x55",
                                  "SHIFT_OUT 1", "PULL 0x55", "JMP", "JMP 256", "JMP nowhere",
                                  "1: SET 0", "loop:: SET 0"])
def test_assembler_rejects_bad_lines(line):
    with pytest.raises(SyntaxError):
        assemble(line)


def test_jmp_takes_an_absolute_address():
    assert assemble("SET 0\nJMP 0") == [0x0000, 0x6000]
    assert assemble("JMP 5 [3]") == [0x6305]


def test_labels_resolve_to_the_address_of_the_next_instruction():
    words = assemble("SET 1\nloop:\n    PULL\n    SET 0 [7]\n    JMP loop")
    assert words == assemble("SET 1\nPULL\nSET 0 [7]\nJMP 1"), "hardware only sees the address"
    assert decode(words[-1], load_isa()) == Instruction("JMP", (1,), 0)


def test_label_on_the_same_line_as_an_instruction():
    assert assemble("top: SET 1\nJMP top") == assemble("SET 1\nJMP 0")


def test_label_can_be_used_before_it_is_defined():
    assert assemble("JMP end\nSET 0\nend: SET 1") == assemble("JMP 2\nSET 0\nSET 1")


def test_label_at_end_of_program_is_the_halt_address():
    assert assemble("SET 0\nJMP done\ndone:") == assemble("SET 0\nJMP 2")


def test_labels_are_case_sensitive_and_take_no_words():
    assert len(assemble("a:\nA:\nSET 0")) == 1
    with pytest.raises(SyntaxError, match="unknown label"):
        assemble("loop:\nJMP LOOP")


def test_duplicate_label_is_an_error():
    with pytest.raises(SyntaxError, match="defined twice"):
        assemble("x: SET 0\nx: SET 1")


@pytest.mark.parametrize("program", sorted(PROGRAMS.glob("*.asm")), ids=lambda p: p.stem)
def test_every_word_fits_16_bits(program):
    assert all(0 <= w < 1 << 16 for w in load_program(program))


def test_uart_program_is_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_0x55.asm")) == 11


def test_pull_uart_program_is_pull_plus_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_pull.asm")) == 1 + 11


def test_loop_uart_program_jumps_back_to_its_pull():
    words = load_program(PROGRAMS / "uart_tx_loop.asm")
    isa = load_isa()
    assert len(words) == 1 + 1 + 10 + 1  # idle, PULL, start + 8 data + stop, JMP
    assert decode(words[1], isa).op == "PULL"
    assert decode(words[-1], isa) == Instruction("JMP", (1,), 0)
