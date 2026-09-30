"""The LED programs of the PYNQ-Z2 bring-up, programs/led/, on the model.
They are loaded into the program RAM by the host, not held in the ROM: no
slot is free. Each pad reads back its own level, as a pad with nothing
outside does: gpio_in[k] is gpio[k] as it stood at the end of the cycle
before, the way the board's IOBUF returns it."""

from pathlib import Path

import pytest

from cpu import CPU, load_program

LED = Path(__file__).resolve().parent.parent.parent / "programs" / "led"
BYTES = range(256)


def step(cpu):
    """One clock with every pad reading back what it drives."""
    cpu.gpio_in = list(cpu.gpio)
    cpu.step()


def until_stalled(cpu, limit=200):
    """Run until the core waits on PULL again. Returns the trace of the cycles run."""
    start = len(cpu.trace)
    step(cpu)
    while not cpu.stalled:
        assert len(cpu.trace) - start < limit, "never came back to PULL"
        step(cpu)
    return cpu.trace[start:]


def nibble(levels):
    return sum(level << k for k, level in enumerate(levels))


def test_led_byte_shows_every_low_nibble():
    cpu = CPU(load_program(LED / "led_byte.asm"))
    until_stalled(cpu)  # first PULL, nothing queued
    for byte in BYTES:
        before = cpu.gpio[:]
        cpu.tx_fifo.append(byte)
        trace = until_stalled(cpu)
        assert nibble(cpu.gpio) == byte & 0xF, f"byte {byte:#04x}: pins {cpu.gpio}"
        assert cpu.acc == 0, "acc is empty for the next byte"
        # pins 1..3 move at most once, straight to the new level: no flicker on LD1..LD3
        for k in (1, 2, 3):
            levels = [before[k]] + [t[k] for t in trace]
            changes = sum(a != b for a, b in zip(levels, levels[1:]))
            assert changes <= 1, f"byte {byte:#04x}: pin {k} moved {changes} times"


def test_led_byte_same_clocks_every_byte():
    """PULL to PULL is the same for every byte: a byte costs 35 clocks, the
    twelve drain words 24 of them with their REPEAT, and the stall cycle."""
    cpu = CPU(load_program(LED / "led_byte.asm"))
    until_stalled(cpu)
    lengths = set()
    for byte in (0x00, 0xFF, 0x5A):
        cpu.tx_fifo.append(byte)
        lengths.add(len(until_stalled(cpu)))
    assert lengths == {35}


def test_led_byte_needs_pad_0_to_read_back():
    """If pad 0 is held low from outside, ACC_CRC reads 0, acc stays 0 and the
    LEDs go dark whatever the byte: the program's one requirement on the board."""
    cpu = CPU(load_program(LED / "led_byte.asm"), tx_data=[0x0F])
    for _ in range(40):
        cpu.gpio_in = [0] + cpu.gpio[1:]
        cpu.step()
    assert nibble(cpu.gpio) == 0


@pytest.mark.parametrize("steps", [9])
def test_led_blink_chases_one_led_round(steps):
    """One pin high at a time, 0, 1, 2, 3, 0, ..., never two on: each on for
    1057 clocks (1058 for the last of the round, its JMP), then a one-clock
    gap, the SET that clears it before the SET that lights the next."""
    cpu = CPU(load_program(LED / "led_blink.asm"))
    for _ in range(3):  # the three SETs that turn pins 1..3 off
        step(cpu)
    assert cpu.gpio == [1, 0, 0, 0]
    runs = []  # (pattern, clocks held)
    while sum(p != 0 for p, _ in runs) < steps + 1:
        step(cpu)
        pattern = nibble(cpu.gpio)
        if runs and runs[-1][0] == pattern:
            runs[-1][1] += 1
        else:
            runs.append([pattern, 1])
    one_hot = [p for p, _ in runs if bin(p).count("1") == 1]
    assert one_hot[:steps] == [1 << (i % 4) for i in range(steps)]
    # between two LEDs is one clock where both are off (the SET that clears the old one)
    for p, n in runs[1:steps * 2]:
        if p == 0:
            assert n == 1
        else:
            assert n in (1057, 1058), f"pattern {p:04b} held {n}"
