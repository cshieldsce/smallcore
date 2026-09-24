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


def test_decode_rejects_bad_operands(isa):
    with pytest.raises(ValueError):
        decode(0x4000, isa)  # WAIT 0
    with pytest.raises(ValueError):
        decode(0x8100, isa)  # LOAD 256
