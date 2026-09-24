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
        decode(0x8000, isa)  # opcode 0b100 unassigned
    with pytest.raises(ValueError):
        decode(0xE000, isa)  # opcode 0b111 unassigned
