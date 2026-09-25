from pathlib import Path

import pytest

from cpu import Instruction, assemble, decode, encode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"


@pytest.fixture(scope="module")
def isa():
    return load_isa()


@pytest.mark.parametrize("instr, word", [
    (Instruction("NOP", (), 0), 0x0000),
    (Instruction("NOP", (), 7), 0x0700),       # 000 00111 00000000
    (Instruction("SET", (0, 0), 0), 0x0080),   # 000 00000 10000000  NOP + side flag in operand[7]
    (Instruction("SET", (0, 1), 7), 0x0790),   # 000 00111 10010000  value in operand[4]
    (Instruction("SET", (0, 1), 31), 0x1F90),  # 000 11111 10010000
    (Instruction("SET", (1, 0), 0), 0x00A0),   # 000 00000 10100000  pin in operand[6:5]
    (Instruction("SET", (3, 1), 0), 0x00F0),   # 000 00000 11110000
    (Instruction("SET", (2, 1), 5), 0x05D0),   # 000 00101 11010000
    (Instruction("SHIFT_OUT", (), 7), 0x2700),  # 001 00111 00000000
    (Instruction("SHIFT_OUT", (), 3, side=(1, 0)), 0x23A0),  # 001 00011 10100000  flag, side pin 1, value 0
    (Instruction("SHIFT_OUT", (), 0, side=(3, 1)), 0x20F0),  # 001 00000 11110000
    (Instruction("PULL", (), 0), 0x4000),  # 010 00000 00000000
    (Instruction("PULL", (), 7), 0x4700),
    (Instruction("PULL", (), 3, side=(2, 0)), 0x43C0),  # 010 00011 11000000  pull, then drop gpio[2] on the same edge
    (Instruction("PUSH", (), 0), 0x4001),  # 010 00000 00000001  FIFO with push = 1 in operand[0]
    (Instruction("PUSH", (), 7), 0x4701),
    (Instruction("PUSH", (), 3, side=(2, 1)), 0x43D1),  # 010 00011 11010001  push and raise gpio[2]
    (Instruction("JMP", (0,), 0), 0x6000),  # 011 00000 00000000
    (Instruction("JMP", (1,), 0), 0x6001),
    (Instruction("JMP", (255,), 31), 0x7FFF),  # 011 11111 11111111
    (Instruction("CONFIG", (0, 0), 0), 0x8000),  # 100 00000 00000000  field 0 = shift_dir in operand[3:2], value in [1:0]
    (Instruction("CONFIG", (0, 1), 0), 0x8001),  # 100 00000 00000001
    (Instruction("CONFIG", (0, 1), 7), 0x8701),  # 100 00111 00000001
    (Instruction("CONFIG", (0, 1), 0, side=(1, 0)), 0x80A1),  # 100 00000 10100001  side effect on CONFIG too
    (Instruction("CONFIG", (1, 3), 0), 0x8007),  # 100 00000 00000111  field 1 = open_drain01, value 0b11
    (Instruction("CONFIG", (2, 2), 1), 0x810A),  # 100 00001 00001010  field 2 = open_drain23, value 0b10
    (Instruction("SHIFT_IN", (0,), 0), 0x2002),  # 001 00000 00000010  SHIFT with in = 1 in operand[1]
    (Instruction("SHIFT_IN", (3,), 0), 0x200E),  # 001 00000 00001110  pin in operand[3:2]
    (Instruction("SHIFT_IN", (3,), 3, side=(1, 1)), 0x23BE),  # 001 00011 10111110  flag, side pin 1, value 1, pin 3, in
    (Instruction("SHIFT_IN", (2,), 0, side=(0, 0)), 0x208A),  # 001 00000 10001010  side effect on gpio[0] allowed
    (Instruction("SHIFT_IN", (1,), 31, side=(3, 1)), 0x3FF6),  # 001 11111 11110110
    (Instruction("WAIT", (0, 0), 0), 0xA000),  # 101 00000 00000000  pin in operand[3:2], level in operand[0]
    (Instruction("WAIT", (3, 1), 0), 0xA00D),  # 101 00000 00001101
    (Instruction("WAIT", (0, 0), 11), 0xAB00),  # 101 01011 00000000  the UART start bit wait
    (Instruction("WAIT", (1, 1), 3, side=(2, 0)), 0xA3C5),  # 101 00011 11000101  release, and drop gpio[2] on that edge
    (Instruction("WAIT", (2, 0), 31, side=(0, 1)), 0xBF98),  # 101 11111 10011000
    (Instruction("SKIP", (0, 0), 0), 0xC000),  # 110 00000 00000000  bit in operand[3:1], level in operand[0]
    (Instruction("SKIP", (7, 1), 0), 0xC00F),  # 110 00000 00001111
    (Instruction("SKIP", (0, 0), 3, side=(1, 0)), 0xC3A0),  # 110 00011 10100000  decide, and drop gpio[1] on the same edge
    (Instruction("SKIP", (5, 1), 31, side=(3, 1)), 0xDFFB),  # 110 11111 11111011
])
def test_encoding(isa, instr, word):
    assert encode(instr, isa) == word
    assert decode(word, isa) == instr


@pytest.mark.parametrize("line", ["SET 0, 2", "SET 0, 1 [32]", "HALT", "SET", "SET 1", "SET 4, 1", "SET 0, 1, 1",
                                  "SET 0, 1 [7", "LOAD 0x55",
                                  "WAIT", "WAIT 1", "WAIT 4, 0", "WAIT 0, 2", "WAIT 0, 0, 1", "WAIT 0, 0, 4, 1",
                                  "WAIT 0, 0, 1, 2", "WAIT 0, 0, 1, 0, 1", "WAIT_PIN 0, 0",
                                  "SKIP", "SKIP 0", "SKIP 8, 0", "SKIP 0, 2", "SKIP 0, 0, 1", "SKIP 0, 0, 4, 0",
                                  "SKIP 0, 0, 1, 2", "SKIP 0, 0, 1, 0, 1", "SKIP_IF 0, 0",
                                  "SHIFT_OUT 1", "SHIFT_OUT 0, 1", "SHIFT_OUT 4, 0", "SHIFT_OUT 1, 2",
                                  "SHIFT_OUT 1, 0, 1", "SET 1, 0, 1", "PULL 1", "PULL 4, 0", "PULL 1, 2", "PULL 1, 0, 1",
                                  "NOP 1", "NOP 1, 0", "JMP 0, 1, 0", "JMP 0, 1", "CONFIG shift_dir, 1, 4, 0",
                                  "PUSH 1", "PUSH 0x55", "PUSH 4, 1", "PUSH 1, 0, 1",
                                  "PULL 0x55", "JMP", "JMP 256", "JMP nowhere",
                                  "CONFIG", "CONFIG shift_dir", "CONFIG shift_dir, 2", "CONFIG 0, 1, 0", "CONFIG 3, 0",
                                  "CONFIG 4, 0", "CONFIG nothing, 0", "CONFIG_SHIFT 1", "CONFIG 0, shift_dir",
                                  "CONFIG open_drain01, 4", "CONFIG open_drain23, 4", "CONFIG open_drain, 3",
                                  "SHIFT_IN", "SHIFT_IN 4", "SHIFT_IN 3, 1", "SHIFT_IN 3, 4, 1", "SHIFT_IN 3, 1, 2",
                                  "SHIFT_IN 3, 1, 1, 0",
                                  "1: SET 0, 0", "loop:: SET 0, 0"])
def test_assembler_rejects_bad_lines(line):
    with pytest.raises(SyntaxError):
        assemble(line)


def test_set_operands_are_pin_then_value():
    assert assemble("SET 1, 0") == assemble("SET 1,0") == assemble("set 1 0") == [0x00A0]
    assert decode(0x00F0, load_isa()) == Instruction("SET", (3, 1), 0)


def test_nop_is_set_without_the_side_effect():
    assert assemble("NOP") == [0x0000]
    assert assemble("NOP [7]") == assemble("nop [7]") == [0x0700]
    assert decode(0x0700, load_isa()) == Instruction("NOP", (), 7)
    assert decode(0x0790, load_isa()) == Instruction("SET", (0, 1), 7)
    assert assemble("SET 2, 0")[0] == assemble("NOP")[0] | 0x80 | 2 << 5


def test_shift_out_side_effect_is_optional():
    assert assemble("SHIFT_OUT [7]") == [0x2700]
    assert assemble("SHIFT_OUT 1, 0 [3]") == assemble("shift_out 1,0 [3]") == [0x23A0]
    assert decode(0x23A0, load_isa()) == Instruction("SHIFT_OUT", (), 3, side=(1, 0))
    assert decode(0x2700, load_isa()).side is None


def test_shift_in_takes_the_input_pin_then_an_optional_side_effect():
    assert assemble("SHIFT_IN 3") == [0x200E]
    assert assemble("SHIFT_IN 3, 1, 1 [3]") == assemble("shift_in 3,1,1 [3]") == [0x23BE]
    assert decode(0x23BE, load_isa()) == Instruction("SHIFT_IN", (3,), 3, side=(1, 1))
    assert decode(0x200E, load_isa()).side is None


def test_pull_and_push_are_one_opcode_with_a_push_bit(isa):
    """One FIFO opcode: operand[0] = 0 moves TX FIFO -> shift_reg, 1 moves
    in_shift_reg -> RX FIFO. Each direction stalls on its own FIFO."""
    pull, push = isa["instructions"]["PULL"], isa["instructions"]["PUSH"]
    assert pull["opcode"] == push["opcode"] == 0b010
    assert pull["select"] == {"name": "push", "lsb": 0, "bits": 1, "value": 0}
    assert push["select"] == {"name": "push", "lsb": 0, "bits": 1, "value": 1}
    assert assemble("PULL 2, 0 [3]")[0] ^ assemble("PUSH 2, 0 [3]")[0] == 0b1


def test_one_opcode_is_free(isa):
    assert sorted({spec["opcode"] for spec in isa["instructions"].values()}) == [0b000, 0b001, 0b010, 0b011, 0b100, 0b101, 0b110]


def test_shift_out_and_shift_in_are_one_opcode_with_an_in_bit(isa):
    """One SHIFT opcode: operand[1] = 0 shifts out, 1 shifts in. The
    mnemonics stay, the decoder has one term fewer and opcode 101 went to WAIT."""
    out, in_ = isa["instructions"]["SHIFT_OUT"], isa["instructions"]["SHIFT_IN"]
    assert out["opcode"] == in_["opcode"] == 0b001
    assert out["select"] == {"name": "in", "lsb": 1, "bits": 1, "value": 0}
    assert in_["select"] == {"name": "in", "lsb": 1, "bits": 1, "value": 1}
    assert assemble("SHIFT_OUT 1, 0 [3]")[0] ^ assemble("SHIFT_IN 0, 1, 0 [3]")[0] == 0b10
    assert [op for op, spec in isa["instructions"].items() if spec["opcode"] == 0b101] == ["WAIT"]


def test_the_side_effect_is_one_field_shared_by_every_instruction_but_jmp(isa):
    """One pin-write port: operand[7] enables it, operand[6:5] is the pin and
    operand[4] the value, on every opcode. SET's operands are those bits, and
    every instruction allows the side effect except JMP, whose target needs
    all eight operand bits, and NOP, which with the side effect is SET."""
    side = isa["side_effect"]
    assert side["flag"] == {"lsb": 7, "bits": 1}
    assert [(o["name"], o["lsb"], o["bits"]) for o in side["operands"]] == [("pin", 5, 2), ("value", 4, 1)]
    assert isa["instructions"]["SET"]["operands"] == side["operands"]
    assert isa["instructions"]["SET"]["select"] == {"name": "side", "lsb": 7, "bits": 1, "value": 1}
    allows = {op: bool(spec.get("side_effect")) for op, spec in isa["instructions"].items()}
    assert allows == {"NOP": False, "SET": False, "SHIFT_OUT": True, "SHIFT_IN": True,
                      "PULL": True, "PUSH": True, "WAIT": True, "SKIP": True, "JMP": False, "CONFIG": True}
    assert assemble("PULL 2, 0 [3]") == [0x43C0]
    assert assemble("CONFIG shift_dir, 1, 1, 0") == [0x80A1]
    for line in ("SET 3, 1", "SHIFT_OUT 3, 1", "SHIFT_IN 0, 3, 1", "PULL 3, 1", "WAIT 0, 0, 3, 1",
                 "SKIP 0, 0, 3, 1", "CONFIG shift_dir, 0, 3, 1"):
        assert assemble(line)[0] & 0xF0 == 0xF0, line


def test_wait_takes_an_input_pin_and_a_level_then_an_optional_side_effect(isa):
    """WAIT's pin sits where SHIFT_IN's does, operand[3:2], so one mux picks
    the input pin for both; the level is operand[0] and operand[1] is unused."""
    assert assemble("WAIT 0, 0") == [0xA000]
    assert assemble("WAIT 3, 1, 2, 0 [3]") == assemble("wait 3,1,2,0 [3]") == [0xA3CD]
    assert decode(0xA3CD, isa) == Instruction("WAIT", (3, 1), 3, side=(2, 0))
    assert decode(0xA000, isa).side is None
    pin = next(o for o in isa["instructions"]["WAIT"]["operands"] if o["name"] == "pin")
    assert pin == next(o for o in isa["instructions"]["SHIFT_IN"]["operands"] if o["name"] == "pin")
    with pytest.raises(ValueError, match="not used"):
        decode(0xA002, isa)  # operand[1] is unused


def test_skip_takes_a_register_bit_and_a_level_then_an_optional_side_effect(isa):
    """SKIP's level sits where WAIT's does, operand[0]; the bit it tests fills
    operand[3:1], so every own bit is used and there is no unused bit to
    reject."""
    assert assemble("SKIP 0, 0") == [0xC000]
    assert assemble("SKIP 3, 1, 2, 0 [3]") == assemble("skip 3,1,2,0 [3]") == [0xC3C7]
    assert decode(0xC3C7, isa) == Instruction("SKIP", (3, 1), 3, side=(2, 0))
    assert decode(0xC00F, isa) == Instruction("SKIP", (7, 1), 0)
    bit, level = (next(o for o in isa["instructions"]["SKIP"]["operands"] if o["name"] == n) for n in ("bit", "level"))
    assert (bit["lsb"], bit["bits"]) == (1, 3)
    assert level == next(o for o in isa["instructions"]["WAIT"]["operands"] if o["name"] == "level")
    with pytest.raises(ValueError, match="no side flag|not used"):
        decode(0xC010, isa)  # the side value without the flag


def test_config_takes_a_field_by_name_or_number_then_a_value():
    assert assemble("CONFIG shift_dir, 0") == assemble("CONFIG 0, 0") == [0x8000]
    assert assemble("CONFIG shift_dir, 1 [3]") == assemble("config shift_dir,1 [3]") == [0x8301]
    assert decode(0x8301, load_isa()) == Instruction("CONFIG", (0, 1), 3)


def test_config_open_drain_is_two_fields_of_two_pins_and_field_3_is_unassigned(isa):
    """CONFIG's value is two bits, the pin modes are four: two fields, the
    lower pins in 1 and the upper in 2, so an I2C master sets SDA and SCL in
    one word and CONFIG keeps its shape and its side effect."""
    assert isa["config"] == {"shift_dir": {"field": 0, "bits": 1},
                             "open_drain01": {"field": 1, "bits": 2}, "open_drain23": {"field": 2, "bits": 2}}
    assert assemble("CONFIG open_drain01, 3") == assemble("CONFIG 1, 3") == [0x8007]
    assert assemble("CONFIG open_drain23, 1 [2]") == assemble("config open_drain23,1 [2]") == [0x8209]
    assert decode(0x8209, isa) == Instruction("CONFIG", (2, 1), 2)
    with pytest.raises(ValueError, match="unassigned"):
        decode(0x800C, isa)  # field 3
    with pytest.raises(ValueError, match="outside 0..1"):
        decode(0x8002, isa)  # shift_dir is one bit wide


def test_jmp_takes_an_absolute_address():
    assert assemble("SET 0, 0\nJMP 0") == [0x0080, 0x6000]
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


def test_pull_uart_program_is_one_instruction_per_bit_with_the_pull_as_the_start_bit():
    words = load_program(PROGRAMS / "uart_tx_pull.asm")
    assert len(words) == 11
    assert decode(words[1], load_isa()) == Instruction("PULL", (), 7, side=(0, 0))


def test_loop_uart_program_jumps_back_to_its_pull():
    words = load_program(PROGRAMS / "uart_tx_loop.asm")
    isa = load_isa()
    assert len(words) == 1 + 10 + 1  # idle, PULL as the start bit + 8 data + stop, JMP
    assert decode(words[1], isa) == Instruction("PULL", (), 7, side=(0, 0))
    assert decode(words[-1], isa) == Instruction("JMP", (1,), 0)


def test_rx_uart_program_waits_for_the_start_bit_then_samples_each_bit_once():
    words = load_program(PROGRAMS / "uart_rx.asm")
    isa = load_isa()
    assert len(words) == 1 + 8 + 1 + 1  # WAIT through the start bit, 8 samples, PUSH, JMP
    assert decode(words[0], isa) == Instruction("WAIT", (0, 0), 11)
    assert all(decode(w, isa) == Instruction("SHIFT_IN", (0,), 7) for w in words[1:9])
    assert decode(words[9], isa) == Instruction("PUSH", (), 2)
    assert decode(words[-1], isa) == Instruction("JMP", (0,), 0)
