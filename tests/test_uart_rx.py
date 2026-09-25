"""UART 8N1 receiver checks. The bench drives RX (gpio_in 0) from a
transmitter model, one level per cycle, or from the TX program on a second
CPU over a wire, and reads the RX FIFO as a host would. programs/uart_rx.asm
waits for the start bit with WAIT and samples each data bit once, mid-bit:
a frame may fall on any cycle and any idle may separate frames."""

import random
from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, Instruction, decode, encode, load_isa, load_program

CYCLES_PER_BIT = 8
RX = 0  # gpio_in pin the receiver watches
TX = 0  # gpio pin the transmit programs drive
PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
RECEIVER = PROGRAMS / "uart_rx.asm"
TRANSMITTER = PROGRAMS / "uart_tx_loop.asm"
BYTES = (0x00, 0x01, 0x55, 0x80, 0xA3, 0xFF)
STREAM = (0xA3, 0x5C, 0x3C, 0x96, 0x0F, 0xF0, 0x81, 0x7E)
SAMPLE_AT = 12  # cycles after the start bit falls that d0 is sampled: mid-bit


def frame(byte):
    """8N1 frame: start bit, 8 data bits LSB first, stop bit."""
    return [0] + [(byte >> i) & 1 for i in range(8)] + [1]


def line(frames):
    """RX level per cycle for frames [(idle cycles before the start bit, byte), ...]
    and the cycle each start bit falls on."""
    levels, starts = [], []
    for gap, byte in frames:
        starts.append(len(levels) + gap)
        levels += [1] * gap + [b for b in frame(byte) for _ in range(CYCLES_PER_BIT)]
    return levels, starts


def shifted(levels, start):
    """The same line with its first cycle at `start`: negative means the line
    was already `-start` cycles in when the CPU came out of reset."""
    return [1] * start + levels if start >= 0 else levels[-start:]


class Run(NamedTuple):
    received: list  # bytes the host took from the RX FIFO, in order
    samples: list  # cycles a SHIFT_IN sampled on
    rx: list  # RX level per cycle, as driven
    cpu: CPU


def drain(cpu):
    """A host that takes everything the moment it lands."""
    taken, cpu.rx_fifo[:] = list(cpu.rx_fifo), []
    return taken


def every(n):
    """A host that takes one byte every n cycles."""
    def host(cpu):
        return [cpu.rx_fifo.pop(0)] if cpu.cycle % n == 0 and cpu.rx_fifo else []
    return host


def run(program, levels, cycles, host=drain):
    """Run `program` for `cycles` cycles with RX following `levels` (high past
    their end) and `host(cpu)` reading the RX FIFO after each cycle."""
    cpu = CPU(program if isinstance(program, list) else load_program(program), gpio_in=1)
    received, samples, rx = [], [], []
    for _ in range(cycles):
        cpu.gpio_in[RX] = levels[cpu.cycle] if cpu.cycle < len(levels) else 1
        rx.append(cpu.gpio_in[RX])
        if cpu.counter == 0 and decode(cpu.program[cpu.pc], cpu.isa).op == "SHIFT_IN":
            samples.append(cpu.cycle)
        cpu.step()
        received += host(cpu)
    return Run(received, samples, rx, cpu)


def sample_cycles(starts):
    """Where the receiver must sample for frames falling at `starts`."""
    return [s + SAMPLE_AT + i * CYCLES_PER_BIT for s in starts for i in range(8)]


def labels(samples, n):
    """A wave row naming the data bit each sample took."""
    row = ["-"] * n
    for i, cycle in enumerate(samples):
        if cycle < n:
            row[cycle] = f"d{i % 8}"
    return row


def waiting(cpu):
    return cpu.stalled and decode(cpu.program[cpu.pc], cpu.isa).op == "WAIT"


@pytest.mark.parametrize("byte", BYTES, ids=lambda b: f"{b:#04x}")
def test_receiver_decodes_a_frame_from_any_start_cycle(byte, wave):
    for start in range(0, 48):
        levels, starts = line([(start, byte)])
        r = run(RECEIVER, levels, start + 100)
        if start == 5:
            wave.add("rx", r.rx, group="in")
            wave.add("sample", labels(r.samples, len(r.rx)))
        assert r.received == [byte], f"start bit at cycle {start}"
        assert r.samples == sample_cycles(starts), "mid-bit, one per data bit, from the edge"
        assert waiting(r.cpu), "back in the WAIT with the line idle"


def test_receiver_takes_a_stream_with_any_idle_between_frames(wave):
    """Back to back or far apart, each frame is found by its own falling
    edge, and no falling edge inside a frame is taken for a start bit."""
    rng = random.Random(7)
    frames = [(rng.randrange(0, 40), byte) for byte in STREAM * 3]
    levels, starts = line(frames)
    r = run(RECEIVER, levels, len(levels) + 100)
    wave.add("rx", r.rx[:400], group="in")
    wave.add("sample", labels(r.samples, 400))
    assert r.received == [byte for _, byte in frames]
    assert r.samples == sample_cycles(starts)
    assert len({b - a for a, b in zip(starts, starts[1:])}) > 4, "the gaps really varied"
    assert waiting(r.cpu)


def test_wait_is_what_makes_the_receiver_asynchronous():
    """The same program with `NOP [11]` in place of `WAIT 0, 0 [11]` samples at
    fixed cycles and decodes only a frame that falls within one bit of where it
    assumes, 3 cycles early to 4 late. With the WAIT any start cycle decodes,
    and so does a start bit still low at reset."""
    isa = load_isa()
    words = load_program(RECEIVER, isa)
    assert decode(words[0], isa) == Instruction("WAIT", (0, 0), 11)
    fixed = [encode(Instruction("NOP", (), 11), isa)] + words[1:]

    def good(program):
        return {start for start in range(-12, 20)
                if all(run(program, shifted(line([(0, byte)])[0], start), 100).received == [byte] for byte in BYTES)}

    assert good(fixed) == set(range(-3, 5))
    assert good(words) == set(range(-3, 20))


def test_a_frame_under_way_at_reset_is_lost_and_the_next_one_is_not():
    """Waking up in the middle of a frame, the WAIT takes the next low data
    bit for a start bit: that byte is garbage, as in any UART. The line then
    idles, the WAIT holds, and the next frame is right."""
    levels, _ = line([(0, 0xA3), (60, 0x5C)])
    r = run(RECEIVER, shifted(levels, -20), 300)
    assert len(r.received) == 2
    assert r.received[0] != 0xA3 and r.received[1] == 0x5C


def test_a_slow_host_loses_frames_and_the_receiver_is_back_in_step_after_an_idle():
    """PUSH stalls on a full RX FIFO. A host that takes a byte every two
    frames holds the loop in a stop bit while frames pass, and a WAIT
    entered mid-frame locks onto a data bit, so bytes go missing or wrong.
    Once the line idles long enough for the FIFO to drain, the WAIT is
    holding on an idle line again and the next frames decode."""
    burst = [(0, byte) for byte in STREAM * 2]  # the FIFO absorbs 8 frames at half rate, not 16
    after = [(700 if k == 0 else 10, byte) for k, byte in enumerate((0x11, 0x22, 0x33, 0x44))]
    levels, _ = line(burst + after)
    r = run(RECEIVER, levels, len(levels) + 800, host=every(160))  # long enough for the host to take the last byte
    assert r.received[-4:] == [0x11, 0x22, 0x33, 0x44]
    assert r.received[:-4] != list(STREAM * 2)
    assert len(r.received) < 20, "frames went missing, not just wrong"
    assert waiting(r.cpu)


def test_tx_program_feeds_the_rx_program_over_a_wire(wave):
    """Two cores: uart_tx_loop.asm sends the bytes a host drops into its TX
    FIFO at random moments, uart_rx.asm on the other end of the wire hands
    the same bytes to its host, in order. The wire carries what the
    transmitter drove on the previous edge."""
    rng = random.Random(3)
    sent = [rng.randrange(256) for _ in range(24)]
    tx = CPU(load_program(TRANSMITTER))
    rx = CPU(load_program(RECEIVER), gpio_in=1)
    pending, received, wire, starts = list(sent), [], [], []
    while len(received) < len(sent) and rx.cycle < 24 * 200:
        if pending and rng.random() < 0.02:
            tx.tx_fifo.append(pending.pop(0))  # the sending host, at its own pace
        level = tx.gpio[TX]
        if wire and wire[-1] == 1 and level == 0:
            starts.append(rx.cycle)
        wire.append(level)
        rx.gpio_in[RX] = level
        tx.step()
        rx.step()
        received += drain(rx)
    for _ in range(100):  # the last stop bit ends, both cores settle into their waits
        rx.gpio_in[RX] = tx.gpio[TX]
        tx.step()
        rx.step()
    wave.add("tx = rx", wire[:600], group="wire")
    wave.add("byte", [f"{sent[starts.index(c)]:02x}" if c in starts else "-" for c in range(600)])
    assert received == sent
    assert len({b - a for a, b in zip(starts, starts[1:])}) > 4, "the idle between frames really varied"
    assert waiting(rx) and tx.stalled and decode(tx.program[tx.pc], tx.isa).op == "PULL"
