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


def test_decode_rejects_spare_opcodes(isa):
    with pytest.raises(ValueError):
        decode(0x8000, isa)
    with pytest.raises(ValueError):
        decode(0xC000, isa)
