from pathlib import Path

import pytest

from cpu import Instruction, assemble, decode, encode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"


@pytest.fixture(scope="module")
def isa():
    return load_isa()


@pytest.mark.parametrize("instr, word", [
    (Instruction("SET", (0, 0), 0), 0x0000),
    (Instruction("SET", (0, 1), 7), 0x0701),   # 000 00111 00000001
    (Instruction("SET", (0, 1), 31), 0x1F01),  # 000 11111 00000001
    (Instruction("SET", (1, 0), 0), 0x0010),   # 000 00000 00010000  pin in operand[5:4]
    (Instruction("SET", (3, 1), 0), 0x0031),   # 000 00000 00110001
    (Instruction("SET", (2, 1), 5), 0x0521),   # 000 00101 00100001
    (Instruction("SHIFT_OUT", (), 7), 0x2700),  # 001 00111 00000000
    (Instruction("SHIFT_OUT", (), 3, side=(1, 0)), 0x2390),  # 001 00011 10010000  flag, side pin 1, value 0
    (Instruction("SHIFT_OUT", (), 0, side=(3, 1)), 0x20B1),  # 001 00000 10110001
    (Instruction("PULL", (), 0), 0x4000),  # 010 00000 00000000
    (Instruction("PULL", (), 7), 0x4700),
    (Instruction("JMP", (0,), 0), 0x6000),  # 011 00000 00000000
    (Instruction("JMP", (1,), 0), 0x6001),
    (Instruction("JMP", (255,), 31), 0x7FFF),  # 011 11111 11111111
    (Instruction("CONFIG", (0, 0), 0), 0x8000),  # 100 00000 00000000  field 0 = shift_dir in operand[3:2], value in [1:0]
    (Instruction("CONFIG", (0, 1), 0), 0x8001),  # 100 00000 00000001
    (Instruction("CONFIG", (0, 1), 7), 0x8701),  # 100 00111 00000001
    (Instruction("SHIFT_IN", (0,), 0), 0x2002),  # 001 00000 00000010  SHIFT with in = 1 in operand[1]
    (Instruction("SHIFT_IN", (3,), 0), 0x200E),  # 001 00000 00001110  pin in operand[3:2]
    (Instruction("SHIFT_IN", (3,), 3, side=(1, 1)), 0x239F),  # 001 00011 10011111  flag, side pin 1, pin 3, in, value 1
    (Instruction("SHIFT_IN", (2,), 0, side=(0, 0)), 0x208A),  # 001 00000 10001010  side effect on gpio[0] allowed
    (Instruction("SHIFT_IN", (1,), 31, side=(3, 1)), 0x3FB7),  # 001 11111 10110111
])
def test_encoding(isa, instr, word):
    assert encode(instr, isa) == word
    assert decode(word, isa) == instr


@pytest.mark.parametrize("line", ["SET 0, 2", "SET 0, 1 [32]", "HALT", "SET", "SET 1", "SET 4, 1", "SET 0, 1, 1",
                                  "SET 0, 1 [7", "WAIT 1", "LOAD 0x55",
                                  "SHIFT_OUT 1", "SHIFT_OUT 0, 1", "SHIFT_OUT 4, 0", "SHIFT_OUT 1, 2",
                                  "SHIFT_OUT 1, 0, 1", "SET 1, 0, 1", "PULL 1, 0", "JMP 0, 1, 0",
                                  "PULL 0x55", "JMP", "JMP 256", "JMP nowhere",
                                  "CONFIG", "CONFIG shift_dir", "CONFIG shift_dir, 2", "CONFIG 0, 1, 0", "CONFIG 1, 0",
                                  "CONFIG 4, 0", "CONFIG nothing, 0", "CONFIG_SHIFT 1", "CONFIG 0, shift_dir",
                                  "SHIFT_IN", "SHIFT_IN 4", "SHIFT_IN 3, 1", "SHIFT_IN 3, 4, 1", "SHIFT_IN 3, 1, 2",
                                  "SHIFT_IN 3, 1, 1, 0",
                                  "1: SET 0, 0", "loop:: SET 0, 0"])
def test_assembler_rejects_bad_lines(line):
    with pytest.raises(SyntaxError):
        assemble(line)


def test_set_operands_are_pin_then_value():
    assert assemble("SET 1, 0") == assemble("SET 1,0") == assemble("set 1 0") == [0x0010]
    assert decode(0x0031, load_isa()) == Instruction("SET", (3, 1), 0)


def test_shift_out_side_effect_is_optional():
    assert assemble("SHIFT_OUT [7]") == [0x2700]
    assert assemble("SHIFT_OUT 1, 0 [3]") == assemble("shift_out 1,0 [3]") == [0x2390]
    assert decode(0x2390, load_isa()) == Instruction("SHIFT_OUT", (), 3, side=(1, 0))
    assert decode(0x2700, load_isa()).side is None


def test_shift_in_takes_the_input_pin_then_an_optional_side_effect():
    assert assemble("SHIFT_IN 3") == [0x200E]
    assert assemble("SHIFT_IN 3, 1, 1 [3]") == assemble("shift_in 3,1,1 [3]") == [0x239F]
    assert decode(0x239F, load_isa()) == Instruction("SHIFT_IN", (3,), 3, side=(1, 1))
    assert decode(0x200E, load_isa()).side is None


def test_shift_out_and_shift_in_are_one_opcode_with_an_in_bit(isa):
    """One SHIFT opcode: operand[1] = 0 shifts out, 1 shifts in. The
    mnemonics stay, the decoder has one term fewer and opcode 101 is free."""
    out, in_ = isa["instructions"]["SHIFT_OUT"], isa["instructions"]["SHIFT_IN"]
    assert out["opcode"] == in_["opcode"] == 0b001
    assert out["select"] == {"name": "in", "lsb": 1, "bits": 1, "value": 0}
    assert in_["select"] == {"name": "in", "lsb": 1, "bits": 1, "value": 1}
    assert assemble("SHIFT_OUT 1, 0 [3]")[0] ^ assemble("SHIFT_IN 0, 1, 0 [3]")[0] == 0b10
    assert not any(spec["opcode"] == 0b101 for spec in isa["instructions"].values())


def test_side_effect_pin_and_value_sit_in_sets_operand_bits(isa):
    """One pin-write decoder: SET, SHIFT_OUT's side effect and SHIFT_IN's side
    effect all read `pin` from operand[5:4] and `value` from operand[0]."""
    def where(operands):
        return {o["name"]: (o["lsb"], o["bits"]) for o in operands}

    expected = where(isa["instructions"]["SET"]["operands"])
    for op in ("SHIFT_OUT", "SHIFT_IN"):
        side = isa["instructions"][op]["side_effect"]
        assert where(side["operands"]) == expected
        assert side["flag"] == {"lsb": 7, "bits": 1}


def test_config_takes_a_field_by_name_or_number_then_a_value():
    assert assemble("CONFIG shift_dir, 0") == assemble("CONFIG 0, 0") == [0x8000]
    assert assemble("CONFIG shift_dir, 1 [3]") == assemble("config shift_dir,1 [3]") == [0x8301]
    assert decode(0x8301, load_isa()) == Instruction("CONFIG", (0, 1), 3)


def test_config_fields_1_to_3_are_unassigned(isa):
    assert isa["config"] == {"shift_dir": {"field": 0, "bits": 1}}
    for word in (0x8004, 0x8008, 0x800C):  # fields 1, 2, 3
        with pytest.raises(ValueError, match="unassigned"):
            decode(word, isa)
    with pytest.raises(ValueError, match="outside 0..1"):
        decode(0x8002, isa)  # shift_dir is one bit wide


def test_jmp_takes_an_absolute_address():
    assert assemble("SET 0, 0\nJMP 0") == [0x0000, 0x6000]
    assert assemble("JMP 5 [3]") == [0x6305]


def test_labels_resolve_to_the_address_of_the_next_instruction():
    words = assemble("SET 0, 1\nloop:\n    PULL\n    SET 0, 0 [7]\n    JMP loop")
    assert words == assemble("SET 0, 1\nPULL\nSET 0, 0 [7]\nJMP 1"), "hardware only sees the address"
    assert decode(words[-1], load_isa()) == Instruction("JMP", (1,), 0)


def test_label_on_the_same_line_as_an_instruction():
    assert assemble("top: SET 0, 1\nJMP top") == assemble("SET 0, 1\nJMP 0")


def test_label_can_be_used_before_it_is_defined():
    assert assemble("JMP end\nSET 0, 0\nend: SET 0, 1") == assemble("JMP 2\nSET 0, 0\nSET 0, 1")


def test_label_at_end_of_program_is_the_halt_address():
    assert assemble("SET 0, 0\nJMP done\ndone:") == assemble("SET 0, 0\nJMP 2")


def test_labels_are_case_sensitive_and_take_no_words():
    assert len(assemble("a:\nA:\nSET 0, 0")) == 1
    with pytest.raises(SyntaxError, match="unknown label"):
        assemble("loop:\nJMP LOOP")


def test_duplicate_label_is_an_error():
    with pytest.raises(SyntaxError, match="defined twice"):
        assemble("x: SET 0, 0\nx: SET 0, 1")


@pytest.mark.parametrize("program", sorted(PROGRAMS.glob("*.asm")), ids=lambda p: p.stem)
def test_every_word_fits_16_bits(program):
    assert all(0 <= w < 1 << 16 for w in load_program(program))


def test_uart_program_is_one_instruction_per_bit():
    words = load_program(PROGRAMS / "uart_tx_0x55.asm")
    assert len(words) == 11
    assert all(decode(w, load_isa()).args[0] == 0 for w in words), "UART only drives gpio 0"


def test_pull_uart_program_is_pull_plus_one_instruction_per_bit():
    assert len(load_program(PROGRAMS / "uart_tx_pull.asm")) == 1 + 11


def test_loop_uart_program_jumps_back_to_its_pull():
    words = load_program(PROGRAMS / "uart_tx_loop.asm")
    isa = load_isa()
    assert len(words) == 1 + 1 + 10 + 1  # idle, PULL, start + 8 data + stop, JMP
    assert decode(words[1], isa).op == "PULL"
    assert decode(words[-1], isa) == Instruction("JMP", (1,), 0)
