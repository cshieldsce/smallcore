import pytest

from cpu import CPU, assemble, decode, load_isa


@pytest.fixture(scope="module")
def isa():
    return load_isa()


def run0(source, **kwargs):
    """Run a program to the end and return gpio 0's trace."""
    cpu = CPU(assemble(source), **kwargs)
    cpu.run()
    return cpu.pin_trace(0)


def test_delay_adds_cycles():
    assert run0("SET 0, 0 [3]\nSET 0, 1") == [0, 0, 0, 0, 1]
    assert run0("SET 0, 0\nSET 0, 0 [4]\nSET 0, 1") == [0] * 6 + [1]


def test_set_drives_one_pin_and_leaves_the_others():
    cpu = CPU(assemble("SET 1, 0\nSET 2, 0 [1]\nSET 1, 1\nSET 3, 0"))
    assert cpu.run() == [(1, 0, 1, 1), (1, 0, 0, 1), (1, 0, 0, 1), (1, 1, 0, 1), (1, 1, 0, 0)]
    assert cpu.gpio == [1, 1, 0, 0]


def test_every_pin_resets_to_the_same_level():
    assert CPU(assemble("PULL"), gpio=0, tx_data=[0]).run() == [(0, 0, 0, 0)]
    assert CPU(assemble("PULL"), tx_data=[0]).run() == [(1, 1, 1, 1)]


def test_shift_out_drives_gpio0_and_nothing_else():
    cpu = CPU(assemble("PULL\nSET 1, 0\nSHIFT_OUT\nSHIFT_OUT"), tx_data=[0b01])
    assert cpu.run()[1:] == [(1, 0, 1, 1), (1, 0, 1, 1), (0, 0, 1, 1)]


def test_shift_out_side_effect_drives_a_second_pin_on_the_same_edge():
    cpu = CPU(assemble("PULL\nSHIFT_OUT 1, 0 [1]\nSHIFT_OUT 2, 0\nSHIFT_OUT 1, 1"), tx_data=[0b011])
    cpu.step()
    assert cpu.gpio == [1, 1, 1, 1]  # PULL touches no pin
    cpu.step()
    assert (cpu.gpio, cpu.shift_reg) == ([1, 0, 1, 1], 0b01)  # bit 0 out and gpio[1] low, one edge
    cpu.step()
    assert (cpu.gpio, cpu.shift_reg) == ([1, 0, 1, 1], 0b01)  # delay cycle: everything holds
    cpu.step()
    assert (cpu.gpio, cpu.shift_reg) == ([1, 0, 0, 1], 0b00)
    cpu.step()
    assert (cpu.gpio, cpu.shift_reg) == ([0, 1, 0, 1], 0b00)
    assert cpu.halted


def test_shift_out_without_side_effect_touches_only_gpio0():
    plain = CPU(assemble("PULL\nSHIFT_OUT [3]\nSHIFT_OUT"), tx_data=[0b10]).run()
    assert plain == [(1, 1, 1, 1)] + [(0, 1, 1, 1)] * 4 + [(1, 1, 1, 1)]


def test_set_and_shift_out_share_gpio0():
    # SET 0, v and SHIFT_OUT write the same register; the last writer wins.
    cpu = CPU(assemble("PULL\nSHIFT_OUT\nSET 0, 1\nSHIFT_OUT"), tx_data=[0b10])
    cpu.run()
    assert cpu.pin_trace(0) == [1, 0, 1, 1]


def test_program_end_halts():
    cpu = CPU(assemble("SET 0, 0 [1]"))
    assert cpu.run() == [(0, 1, 1, 1)] * 2
    assert cpu.halted
    with pytest.raises(RuntimeError):
        cpu.step()


def test_shift_out_sends_lsb_first():
    # 0b0101 -> 1, 0, 1, 0; extra SHIFT_OUTs read the zero fill
    assert run0("PULL\n" + "SHIFT_OUT\n" * 6, tx_data=[0b0101]) == [1, 1, 0, 1, 0, 0, 0]  # first 1: PULL cycle, gpio 0 idle high


def test_shift_out_delay_holds_the_bit():
    assert run0("PULL\nSHIFT_OUT [2]\nSHIFT_OUT", tx_data=[0b01]) == [1, 1, 1, 1, 0]


def test_shift_dir_resets_to_lsb_first():
    assert CPU(assemble("PULL"), tx_data=[0]).shift_dir == 0


def test_config_shift_sets_shift_dir_and_touches_nothing_else():
    cpu = CPU(assemble("PULL\nCONFIG_SHIFT 1 [1]\nCONFIG_SHIFT 0"), tx_data=[0xA5])
    cpu.step()
    assert cpu.shift_dir == 0
    cpu.step()  # first cycle: shift_dir <- 1, pins and shift_reg untouched
    assert (cpu.shift_dir, cpu.gpio, cpu.shift_reg, cpu.pc) == (1, [1, 1, 1, 1], 0xA5, 1)
    cpu.step()  # delay cycle
    assert (cpu.shift_dir, cpu.pc) == (1, 2)
    cpu.step()
    assert (cpu.shift_dir, cpu.gpio, cpu.shift_reg) == (0, [1, 1, 1, 1], 0xA5)
    assert cpu.halted


def test_shift_out_sends_msb_first_after_config_shift_1():
    # 0b1000_0110 -> 1 0 0 0 0 1 1 0; extra SHIFT_OUTs read the zero fill
    trace = run0("CONFIG_SHIFT 1\nPULL\n" + "SHIFT_OUT\n" * 10, tx_data=[0b1000_0110])
    assert trace[2:] == [1, 0, 0, 0, 0, 1, 1, 0, 0, 0]


def test_msb_first_shift_out_order_pin_then_shift_left_on_first_cycle():
    """The RTL contract mirrored: with shift_dir 1, gpio[0] takes shift_reg[7]
    and shift_reg <<= 1 (zero fill) on the same edge; delay cycles hold."""
    cpu = CPU(assemble("CONFIG_SHIFT 1\nPULL\nSHIFT_OUT [1]\nSHIFT_OUT"), gpio=0, tx_data=[0b1100_0000])
    cpu.step()
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (0, 0xC0)  # configured and filled, pin untouched
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (1, 0x80)  # first cycle: gpio[0] = old bit 7, then shift left
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (1, 0x80)  # delay cycle: hold
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (1, 0x00)
    assert cpu.halted


def test_shift_dir_is_configuration_and_persists_across_pull_and_jmp():
    cpu = CPU(assemble("CONFIG_SHIFT 1\nloop: PULL\nSHIFT_OUT\nJMP loop"), tx_data=[0x80, 0x01])
    while not cpu.stalled:
        cpu.step()
    # config, PULL, bit 7 of 0x80 = 1, JMP, PULL, bit 7 of 0x01 = 0, JMP, stall
    assert cpu.pin_trace(0) == [1, 1, 1, 1, 1, 0, 0, 0]
    assert cpu.shift_dir == 1


def test_config_shift_mid_byte_switches_the_end_that_shifts():
    # 0b1000_0001: the LSB goes out first; the right shift leaves the other 1 in
    # bit 6, so after switching to MSB first the next bit out is bit 7 = 0.
    cpu = CPU(assemble("PULL\nSHIFT_OUT\nCONFIG_SHIFT 1\nSHIFT_OUT"), tx_data=[0b1000_0001])
    cpu.run()
    assert cpu.pin_trace(0) == [1, 1, 1, 0]
    assert cpu.shift_reg == 0x80


def test_shift_out_order_pin_then_shift_on_first_cycle():
    """The RTL contract: on SHIFT_OUT's first cycle gpio[0] takes shift_reg[0]
    and shift_reg >>= 1 on the same edge; the delay cycles change nothing."""
    cpu = CPU(assemble("PULL\nSHIFT_OUT [1]\nSHIFT_OUT"), gpio=0, tx_data=[0b11])
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (0, 0b11)  # PULL: register filled, pins untouched
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (1, 0b01)  # first cycle: gpio[0] = old bit 0, then shift
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (1, 0b01)  # delay cycle: hold
    cpu.step()
    assert (cpu.gpio[0], cpu.shift_reg) == (1, 0b00)
    assert cpu.halted


def test_pull_moves_next_fifo_byte_into_shift_reg():
    cpu = CPU(assemble("SET 0, 0\nPULL"), tx_data=[0xA3, 0x37])
    assert cpu.run() == [(0, 1, 1, 1)] * 2  # pins untouched
    assert cpu.shift_reg == 0xA3
    assert cpu.tx_fifo == [0x37], "only one byte consumed"


def test_pull_consumes_fifo_in_order():
    cpu = CPU(assemble("PULL\nPULL\nPULL"), tx_data=[1, 2, 3])
    seen = []
    while not cpu.halted:
        cpu.step()
        seen.append(cpu.shift_reg)
    assert seen == [1, 2, 3]
    assert cpu.tx_fifo == []


def test_pull_then_shift_out_sends_fifo_byte_lsb_first():
    assert run0("PULL\n" + "SHIFT_OUT\n" * 8, tx_data=[0b1000_0110])[1:] == [0, 1, 1, 0, 0, 0, 0, 1]


def test_pull_blocks_on_empty_fifo_until_a_byte_arrives():
    cpu = CPU(assemble("SET 0, 0\nPULL [1]\nSET 0, 1"))
    cpu.step()
    for _ in range(3):  # stalled: PC and pins hold, cycles still tick
        cpu.step()
        assert (cpu.pc, cpu.gpio, cpu.shift_reg, cpu.stalled) == (1, [0, 1, 1, 1], 0, True)
    assert cpu.cycle == 4
    cpu.tx_fifo.append(0x37)  # the outside world feeds the FIFO
    cpu.step()  # PULL completes on this cycle, then its delay
    assert (cpu.pc, cpu.shift_reg, cpu.stalled) == (1, 0x37, False)
    cpu.step()
    cpu.step()
    cpu.run()
    assert cpu.pin_trace(0) == [0, 0, 0, 0, 0, 0, 1]
    assert cpu.halted


def test_run_reports_a_stalled_pull():
    with pytest.raises(RuntimeError, match="stalled on PULL"):
        CPU(assemble("PULL")).run(max_cycles=10)


def test_jmp_loads_pc_and_touches_nothing_else():
    cpu = CPU(assemble("PULL\nJMP 3\nSET 0, 0\nSET 0, 1"), gpio=0, tx_data=[0xA5])
    cpu.step()
    cpu.step()  # JMP: one cycle, PC <- 3, pins and shift_reg unchanged
    assert (cpu.pc, cpu.gpio, cpu.shift_reg, cpu.cycle) == (3, [0, 0, 0, 0], 0xA5, 2)
    cpu.run()
    assert cpu.pin_trace(0) == [0, 0, 1]  # SET 0, 0 at address 2 was skipped


def test_jmp_delay_holds_before_the_jump():
    cpu = CPU(assemble("SET 0, 0\nJMP 3 [2]\nSET 0, 1\nSET 0, 1"))
    cpu.step()
    for _ in range(3):  # 1 + 2 cycles on the JMP, PC moves on the last one
        assert cpu.pc == 1
        cpu.step()
    assert cpu.pc == 3
    cpu.run()
    assert cpu.pin_trace(0) == [0, 0, 0, 0, 1]


def test_jmp_past_the_end_halts():
    cpu = CPU(assemble("SET 0, 0\nJMP 7"))
    cpu.run()
    assert cpu.pin_trace(0) == [0, 0]
    assert cpu.halted


def test_jmp_backwards_loops_forever():
    cpu = CPU(assemble("loop: SET 0, 0\nSET 0, 1\nJMP loop"))
    cpu.run_cycles(9)
    assert cpu.pin_trace(0) == [0, 1, 1, 0, 1, 1, 0, 1, 1]
    assert not cpu.halted
    with pytest.raises(RuntimeError, match="did not halt"):
        cpu.run(max_cycles=100)


def test_run_cycles_stops_early_at_halt():
    cpu = CPU(assemble("SET 0, 0\nSET 0, 1"))
    cpu.run_cycles(50)
    assert cpu.pin_trace(0) == [0, 1]
    assert cpu.halted


def test_loop_over_pull_drains_the_fifo_then_stalls():
    cpu = CPU(assemble("loop: PULL\nJMP loop"), tx_data=[1, 2, 3])
    seen = []
    while not cpu.stalled:
        cpu.step()
        seen.append(cpu.shift_reg)
    assert seen == [1, 1, 2, 2, 3, 3, 3]  # each byte is held across its JMP; the stall changes nothing
    assert (cpu.pc, cpu.tx_fifo, cpu.halted) == (0, [], False)


def test_decode_rejects_bad_words(isa):
    with pytest.raises(ValueError):
        decode(0x0002, isa)  # SET with operand bit 1 set: no operand lives there
    with pytest.raises(ValueError):
        decode(0x2001, isa)  # SHIFT_OUT takes no operand
    with pytest.raises(ValueError):
        decode(0x2004, isa)  # SHIFT_OUT with an input pin: bits 3:2 are SHIFT_IN's
    with pytest.raises(ValueError):
        decode(0x8002, isa)  # CONFIG_SHIFT with operand bit 1 set: only bit 0 is dir
    with pytest.raises(ValueError):
        decode(0x2003, isa)  # SHIFT_IN with the side value set but no side flag
    with pytest.raises(ValueError):
        decode(0x2042, isa)  # SHIFT_IN with operand bit 6 set: nothing lives there
    with pytest.raises(ValueError):
        decode(0xA000, isa)  # opcode 0b101 unassigned since SHIFT_IN joined SHIFT_OUT
    with pytest.raises(ValueError):
        decode(0xC000, isa)  # opcode 0b110 unassigned
    with pytest.raises(ValueError):
        decode(0xE000, isa)  # opcode 0b111 unassigned


# SHIFT_IN: gpio_in[pin] -> input shift register, obeying shift_dir.


def test_inputs_start_at_the_constructor_level_and_the_input_register_empty():
    cpu = CPU(assemble("PULL"), tx_data=[0])
    assert (cpu.gpio_in, cpu.in_shift_reg) == ([0, 0, 0, 0], 0)
    assert CPU(assemble("PULL"), gpio_in=1, tx_data=[0]).gpio_in == [1, 1, 1, 1]


def test_shift_in_lsb_first_enters_at_bit_7_and_shifts_right():
    """The RTL contract: on SHIFT_IN's first cycle in_shift_reg <= {gpio_in[pin], in_shift_reg[7:1]}."""
    cpu = CPU(assemble("SHIFT_IN 2\nSHIFT_IN 2\nSHIFT_IN 2"))
    cpu.gpio_in[2] = 1
    cpu.step()
    assert cpu.in_shift_reg == 0b1000_0000
    cpu.gpio_in[2] = 0
    cpu.step()
    assert cpu.in_shift_reg == 0b0100_0000
    cpu.gpio_in[2] = 1
    cpu.step()
    assert cpu.in_shift_reg == 0b1010_0000
    assert cpu.halted


def test_shift_in_msb_first_enters_at_bit_0_and_shifts_left():
    """With shift_dir 1: in_shift_reg <= {in_shift_reg[6:0], gpio_in[pin]}."""
    cpu = CPU(assemble("CONFIG_SHIFT 1\nSHIFT_IN 2\nSHIFT_IN 2\nSHIFT_IN 2"))
    cpu.step()
    cpu.gpio_in[2] = 1
    cpu.step()
    assert cpu.in_shift_reg == 0b0000_0001
    cpu.gpio_in[2] = 0
    cpu.step()
    assert cpu.in_shift_reg == 0b0000_0010
    cpu.gpio_in[2] = 1
    cpu.step()
    assert cpu.in_shift_reg == 0b0000_0101
    assert cpu.halted


@pytest.mark.parametrize("byte", (0x00, 0x01, 0x80, 0xA3, 0x5C, 0xFF), ids=lambda b: f"{b:#04x}")
@pytest.mark.parametrize("shift_dir", (0, 1), ids=("lsb_first", "msb_first"))
def test_eight_shift_ins_rebuild_a_byte_in_normal_order(byte, shift_dir):
    """The bits arrive in wire order (LSB or MSB first, as shift_dir says)
    and land in the register in byte order, so the same one bit of
    configuration serves both directions of a protocol."""
    bits = [(byte >> i) & 1 for i in range(8)]
    wire = bits[::-1] if shift_dir else bits
    cpu = CPU(assemble(f"CONFIG_SHIFT {shift_dir}\n" + "SHIFT_IN 1 [2]\n" * 8))
    cpu.step()
    for bit in wire:
        cpu.gpio_in[1] = bit
        cpu.run_cycles(3)
    assert cpu.halted
    assert cpu.in_shift_reg == byte


def test_shift_in_samples_the_named_pin_only():
    cpu = CPU(assemble("SHIFT_IN 3"), gpio_in=1)
    cpu.gpio_in[3] = 0
    cpu.step()
    assert cpu.in_shift_reg == 0


def test_shift_in_samples_on_its_first_cycle_only():
    """Delay cycles hold: the pin may change during them without being seen."""
    cpu = CPU(assemble("SHIFT_IN 0 [2]\nSHIFT_IN 0"))
    cpu.gpio_in[0] = 1
    cpu.step()
    assert (cpu.in_shift_reg, cpu.pc) == (0x80, 0)
    cpu.gpio_in[0] = 0
    cpu.step()
    assert (cpu.in_shift_reg, cpu.pc) == (0x80, 0)
    cpu.gpio_in[0] = 1
    cpu.step()
    assert (cpu.in_shift_reg, cpu.pc) == (0x80, 1)
    cpu.gpio_in[0] = 0
    cpu.step()
    assert cpu.in_shift_reg == 0x40
    assert cpu.halted


def test_shift_in_samples_the_level_present_as_the_cycle_executes():
    """The timing contract: the sample is what the outside world drove before
    the clock edge that executes SHIFT_IN. Changing the pin after that edge
    (before the next step) is too late for this SHIFT_IN and lands in the next."""
    cpu = CPU(assemble("SHIFT_IN 0\nSHIFT_IN 0"))
    cpu.gpio_in[0] = 1
    cpu.step()
    cpu.gpio_in[0] = 0
    assert cpu.in_shift_reg == 0x80
    cpu.step()
    assert cpu.in_shift_reg == 0x40


def test_shift_in_touches_no_output_pin_nor_the_output_side():
    cpu = CPU(assemble("CONFIG_SHIFT 1\nPULL\nSHIFT_IN 3 [1]"), tx_data=[0xA5])
    cpu.gpio_in[3] = 1
    cpu.run()
    assert (cpu.gpio, cpu.shift_reg, cpu.shift_dir, cpu.tx_fifo) == ([1, 1, 1, 1], 0xA5, 1, [])
    assert cpu.in_shift_reg == 0x01


def test_shift_in_side_effect_drives_a_pin_on_the_sampling_edge():
    """`SHIFT_IN 3, 1, 1`: gpio_in[3] is sampled and gpio[1] rises on one
    edge, which is SPI mode 0's rising clock edge. The sample cannot see the
    side effect: gpio_in is what the outside world drove before the edge."""
    cpu = CPU(assemble("SET 1, 0\nSHIFT_IN 3, 1, 1 [1]\nSHIFT_IN 3, 1, 0"))
    cpu.step()
    cpu.gpio_in[3] = 1
    cpu.step()
    assert (cpu.gpio, cpu.in_shift_reg) == ([1, 1, 1, 1], 0x80)  # sampled and clock up, one edge
    cpu.gpio_in[3] = 0
    cpu.step()
    assert (cpu.gpio, cpu.in_shift_reg) == ([1, 1, 1, 1], 0x80)  # delay cycle: everything holds
    cpu.step()
    assert (cpu.gpio, cpu.in_shift_reg) == ([1, 0, 1, 1], 0x40)
    assert cpu.halted


def test_shift_in_side_effect_may_drive_gpio0():
    # Unlike SHIFT_OUT, SHIFT_IN drives no pin of its own, so gpio[0] is free.
    cpu = CPU(assemble("SHIFT_IN 0, 0, 0"))
    cpu.run()
    assert cpu.gpio == [0, 1, 1, 1]


def test_shift_in_and_shift_out_share_shift_dir_but_not_a_register():
    """Full duplex in the small: the output register drains while the input
    register fills, each from its own end, both under one shift_dir."""
    cpu = CPU(assemble("CONFIG_SHIFT 1\nPULL\n" + "SHIFT_OUT\nSHIFT_IN 0\n" * 8), tx_data=[0xA3])
    cpu.step()
    cpu.step()
    for bit in [(0x5C >> i) & 1 for i in range(7, -1, -1)]:  # MSB first on the wire
        cpu.step()  # SHIFT_OUT
        cpu.gpio_in[0] = bit
        cpu.step()  # SHIFT_IN
    assert cpu.halted
    assert (cpu.shift_reg, cpu.in_shift_reg) == (0x00, 0x5C)
    assert cpu.pin_trace(0)[2::2] == [(0xA3 >> i) & 1 for i in range(7, -1, -1)]
