import pytest

from cpu import CPU, assemble, decode, load_isa


@pytest.fixture(scope="module")
def isa():
    return load_isa()


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


def test_load_leaves_pin_alone():
    cpu = CPU(assemble("SET 0\nLOAD 255"))
    assert cpu.run() == [0, 0]
    assert cpu.shift_reg == 255


def test_shift_out_sends_lsb_first():
    # 0b0101 -> 1, 0, 1, 0; extra SHIFT_OUTs read the zero fill
    cpu = CPU(assemble("LOAD 0b0101\n" + "SHIFT_OUT\n" * 6))
    assert cpu.run() == [1, 1, 0, 1, 0, 0, 0]  # first 1 is the LOAD cycle (pin idle high)


def test_shift_out_delay_holds_the_bit():
    assert CPU(assemble("LOAD 0b01\nSHIFT_OUT [2]\nSHIFT_OUT")).run() == [1, 1, 1, 1, 0]


def test_shift_out_order_pin_then_shift_on_first_cycle():
    """The RTL contract: on SHIFT_OUT's first cycle the pin takes shift_reg[0]
    and shift_reg >>= 1 on the same edge; the delay cycles change nothing."""
    cpu = CPU(assemble("LOAD 0b11\nSHIFT_OUT [1]\nSHIFT_OUT"), pin=0)
    cpu.step()
    assert (cpu.pin, cpu.shift_reg) == (0, 0b11)  # LOAD: register filled, pin untouched
    cpu.step()
    assert (cpu.pin, cpu.shift_reg) == (1, 0b01)  # first cycle: pin = old bit 0, then shift
    cpu.step()
    assert (cpu.pin, cpu.shift_reg) == (1, 0b01)  # delay cycle: hold
    cpu.step()
    assert (cpu.pin, cpu.shift_reg) == (1, 0b00)
    assert cpu.halted


def test_pull_moves_next_fifo_byte_into_shift_reg():
    cpu = CPU(assemble("SET 0\nPULL"), tx_data=[0xA3, 0x37])
    assert cpu.run() == [0, 0]  # pin untouched
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
    cpu = CPU(assemble("PULL\n" + "SHIFT_OUT\n" * 8), tx_data=[0b1000_0110])
    assert cpu.run()[1:] == [0, 1, 1, 0, 0, 0, 0, 1]


def test_pull_blocks_on_empty_fifo_until_a_byte_arrives():
    cpu = CPU(assemble("SET 0\nPULL [1]\nSET 1"))
    cpu.step()
    for _ in range(3):  # stalled: PC and pin hold, cycles still tick
        cpu.step()
        assert (cpu.pc, cpu.pin, cpu.shift_reg, cpu.stalled) == (1, 0, 0, True)
    assert cpu.cycle == 4
    cpu.tx_fifo.append(0x37)  # the outside world feeds the FIFO
    cpu.step()  # PULL completes on this cycle, then its delay
    assert (cpu.pc, cpu.shift_reg, cpu.stalled) == (1, 0x37, False)
    cpu.step()
    cpu.step()
    assert cpu.run() == [0, 0, 0, 0, 0, 0, 1]
    assert cpu.halted


def test_run_reports_a_stalled_pull():
    with pytest.raises(RuntimeError, match="stalled on PULL"):
        CPU(assemble("PULL")).run(max_cycles=10)


def test_decode_rejects_bad_words(isa):
    with pytest.raises(ValueError):
        decode(0x2000, isa)  # WAIT 0
    with pytest.raises(ValueError):
        decode(0x0002, isa)  # SET 2
    with pytest.raises(ValueError):
        decode(0xE000, isa)  # opcode 0b111 unassigned
