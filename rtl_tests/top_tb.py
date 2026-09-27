"""cocotb tests for rtl/top.v: the core between its TX and RX FIFOs. Run
through test_top.py, not directly.

The bench drives only top's host ports (tx_data, tx_push, rx_pop, ...). The
core's FIFO ports are wires inside top, so the paths under test are
host -> TX fifo.v -> core.v and core.v -> RX fifo.v -> host. Internals are
read hierarchically through VPI: dut.core_i.shift_reg, dut.tx_fifo.count.
"""

from pathlib import Path

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from cpu import assemble, load_program  # sim/cpu.py
from tb import Imem, reset, start_clock

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
BIT = 8  # clocks per UART bit in uart_tx_pull.asm and uart_rx.asm


def drive_host(dut, program_words):
    """Drive every top input besides clk, reset and imem_word so none is X,
    with the host idle: nothing pushed, nothing popped."""
    dut.program_words.value = program_words
    dut.gpio_in.value = 0
    dut.tx_data.value = 0
    dut.tx_push.value = 0
    dut.rx_pop.value = 0


def uart_frame(byte):
    """One 8N1 frame as line levels, one per bit: start, d0..d7 LSB first, stop."""
    return [0] + [(byte >> bit) & 1 for bit in range(8)] + [1]


def uart_decode(levels):
    """Decode one 8N1 frame from a line sampled once per clock. The line must
    idle high up to the start bit, and every bit must hold its level for
    exactly BIT clocks, so a glitch or a wrong bit time fails here rather than
    decoding by luck."""
    start = levels.index(0)
    assert start > 0 and all(levels[:start]), "line not idle high before the start bit"
    bits = []
    for i in range(10):
        cell = levels[start + i * BIT : start + (i + 1) * BIT]
        assert len(cell) == BIT, f"line ends inside bit {i}"
        assert len(set(cell)) == 1, f"bit {i} not held for {BIT} clocks: {cell}"
        bits.append(cell[0])
    assert bits[0] == 0 and bits[9] == 1, f"bad start/stop: {bits}"
    return sum(bit << i for i, bit in enumerate(bits[1:9]))


@cocotb.test()
async def host_push_then_pull(dut):
    """The host pushes 0xA5 into the TX FIFO and PULL takes it into shift_reg.
    program_words stays 0 while the byte goes in, so the core is halted and
    the PULL cannot issue against an empty FIFO and stall; that is valid, but
    not what this test is about. Raising program_words releases the PULL,
    which loads shift_reg and pops the FIFO on the same edge."""
    program = assemble("""
        PULL
    """)
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.core_i.pull_en.value) == 0

    # Host push, driven on the falling edge (the read-only phase forbids writes).
    await FallingEdge(dut.clk)
    dut.tx_data.value = 0xA5
    dut.tx_push.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.tx_fifo.count.value) == 1
    assert int(dut.tx_fifo.empty.value) == 0
    assert int(dut.tx_full.value) == 0
    assert int(dut.tx_fifo.head_data.value) == 0xA5
    assert int(dut.core_i.pc.value) == 0  # halted: the PULL has not issued

    # Release the core: the PULL sees the byte and pull_en rises.
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)
    await ReadOnly()
    assert int(dut.core_i.pull_en.value) == 1

    # Issue edge: shift_reg loads the head, the FIFO pops it, the core halts.
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.core_i.shift_reg.value) == 0xA5
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.tx_fifo.count.value) == 0
    assert int(dut.core_i.pc.value) == 1
    assert int(dut.core_i.halted.value) == 1
    assert int(dut.core_i.pull_en.value) == 0


@cocotb.test()
async def push_then_host_pop(dut):
    """PUSH hands in_shift_reg to the RX FIFO and the host pops it off rx_data.
    SHIFT_IN fills in_shift_reg; the bench seeds it instead, while program_words
    is 0 and the core is halted. Raising program_words releases the PUSH, which
    lands 0xA5 in the FIFO on its edge; one rx_pop empties it again."""
    program = assemble("""
        PUSH
    """)
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1
    assert int(dut.core_i.push_en.value) == 0

    # Seed and release the core together, between edges (the read-only phase
    # forbids writes). The FIFO has room, so push_en rises.
    await FallingEdge(dut.clk)
    dut.core_i.in_shift_reg.value = 0xA5
    dut.program_words.value = len(program)
    await ReadOnly()
    assert int(dut.core_i.push_en.value) == 1

    # Issue edge: the byte lands in the RX FIFO, the core halts.
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_empty.value) == 0
    assert int(dut.rx_data.value) == 0xA5
    assert int(dut.core_i.halted.value) == 1
    assert int(dut.core_i.push_en.value) == 0  # pushed once

    # Host pop, driven on the falling edge.
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.rx_fifo.count.value) == 0
    assert int(dut.rx_empty.value) == 1


@cocotb.test()
async def uart_tx_host_byte_to_pin(dut):
    """programs/uart_tx_pull.asm end to end. The host pushes 0xA5 into the TX
    FIFO while the program sends its idle bit; the PULL takes it and the
    SHIFT_OUTs send it. The bench sees only top's pins: it samples
    gpio_out[0] once per clock and decodes that as a UART line."""
    program = load_program(PROGRAMS / "uart_tx_pull.asm")
    byte = 0xA5
    dut.imem_word.value = 0
    drive_host(dut, program_words=len(program))
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    # Host push on the first falling edge, one clock into the idle bit; the
    # PULL does not issue until BIT clocks in.
    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0

    # Idle, 10 frame bits, and a bit time of the line resting high after the
    # program halts.
    levels = []
    for _ in range(12 * BIT):
        await RisingEdge(dut.clk)
        await ReadOnly()
        levels.append(int(dut.gpio_out.value) & 1)

    assert uart_decode(levels) == byte
    assert levels[-BIT:] == [1] * BIT  # idle after the stop bit
    assert int(dut.gpio_oe.value) & 1 == 1  # pin 0 driven, not released
    assert int(dut.tx_full.value) == 0
    assert int(dut.tx_fifo.empty.value) == 1  # the byte was consumed once


@cocotb.test()
async def uart_rx_pin_to_host_byte(dut):
    """programs/uart_rx.asm end to end, the mirror of the TX test. The bench
    drives one 8N1 frame of 0xA5 onto gpio_in[0] and reads the result only
    from top's host port: rx_empty, rx_data, rx_pop."""
    program = load_program(PROGRAMS / "uart_rx.asm")
    byte = 0xA5
    dut.imem_word.value = 0
    drive_host(dut, program_words=len(program))
    dut.gpio_in.value = 0b1111  # RX idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    async def drive_rx(level, clocks):
        """Hold gpio_in[0] at level for `clocks` rising edges, changing it on
        the falling edge (the read-only phase forbids writes)."""
        for _ in range(clocks):
            await FallingEdge(dut.clk)
            dut.gpio_in.value = 0b1110 | level
            await RisingEdge(dut.clk)

    await drive_rx(1, 2 * BIT)  # idle: the WAIT stalls
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1

    for level in uart_frame(byte):
        await drive_rx(level, BIT)
    await drive_rx(1, BIT)  # idle after the frame
    await ReadOnly()

    # PUSH ran once, mid stop bit: exactly one byte for the host.
    assert int(dut.rx_empty.value) == 0
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == byte

    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1


# SPI: the bench is the slave. It watches top's pins only, one sample per
# clock, and reads the frame the way a mode 0 slave would: CS low frames the
# transfer, MOSI is taken on every rising edge of SCLK.

MOSI, SCLK, CS = 0, 1, 2  # gpio_out pins spi_tx_lsb.asm and spi_tx_msb.asm drive


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


async def spi_pin_trace(dut, limit=200):
    """Sample gpio_out after every rising edge of clk until the core halts,
    plus a few clocks after so the idle levels show. Returns one list per pin,
    one level per clock. Edges are found in the traces afterwards, so there is
    no previous-level state to seed: the first sample is only ever a level."""
    mosi, sclk, cs = [], [], []
    tail = 4  # clocks recorded after the halt
    for _ in range(limit):
        await RisingEdge(dut.clk)
        await ReadOnly()
        pins = int(dut.gpio_out.value)
        mosi.append((pins >> MOSI) & 1)
        sclk.append((pins >> SCLK) & 1)
        cs.append((pins >> CS) & 1)
        if int(dut.core_i.halted.value):
            tail -= 1
            if tail == 0:
                return mosi, sclk, cs
    raise AssertionError(f"core still running after {limit} clocks")


def mode0_sampled(mosi, sclk, cs):
    """What a mode 0 slave shifts in: MOSI on each rising edge of SCLK while
    CS is low, in order."""
    return [mosi[e] for e in rising_edges(sclk) if cs[e] == 0]


@cocotb.test()
async def spi_tx_lsb_host_byte_to_pins(dut):
    """programs/spi_tx_lsb.asm end to end. The host pushes 0x96 into the TX
    FIFO while program_words is 0, as in host_push_then_pull, then releases
    the program; the PULL takes the byte and the SHIFT_OUTs clock it out.
    0x96 = 1001_0110 is not a palindrome, so LSB first (0 1 1 0 1 0 0 1) and
    MSB first (1 0 0 1 0 1 1 0) differ on the wire: a bit-order bug fails."""
    program = load_program(PROGRAMS / "spi_tx_lsb.asm")
    byte = 0x96
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert (int(dut.gpio_out.value) >> CS) & 1 == 1  # CS idle high out of reset
    assert int(dut.tx_fifo.empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    mosi, sclk, cs = await spi_pin_trace(dut)

    # CS starts high, falls once, rises once.
    assert cs[0] == 1
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    assert start < end
    assert cs[end:] == [1] * len(cs[end:])

    # Exactly 8 rising edges of SCLK, all inside the frame.
    edges = rising_edges(sclk)
    assert len(edges) == 8, f"rising edges of SCLK at {edges}"
    assert all(start < e < end for e in edges)

    # The slave's view of the byte: 0x96 LSB first.
    assert mode0_sampled(mosi, sclk, cs) == [0, 1, 1, 0, 1, 0, 0, 1]

    # Mode 0: SCLK is low when CS rises and stays low after.
    assert sclk[end - 1] == 0
    assert sclk[end:] == [0] * len(sclk[end:])

    # The pins are driven, and the byte was consumed exactly once.
    assert int(dut.gpio_oe.value) & 0b111 == 0b111
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.tx_full.value) == 0


@cocotb.test()
async def spi_tx_msb_host_byte_to_pins(dut):
    """programs/spi_tx_msb.asm end to end, the LSB test with the other
    program. The two programs differ in one word, CONFIG shift_dir 0 vs 1, so
    the same 0x96 must now reach the slave as 1 0 0 1 0 1 1 0: this proves
    that CONFIG changes what is on the wire, not just a register. Framing,
    clock count and clock idle are unchanged."""
    program = load_program(PROGRAMS / "spi_tx_msb.asm")
    byte = 0x96
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert (int(dut.gpio_out.value) >> CS) & 1 == 1  # CS idle high out of reset
    assert int(dut.tx_fifo.empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    mosi, sclk, cs = await spi_pin_trace(dut)

    # CS starts high, falls once, rises once.
    assert cs[0] == 1
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    assert start < end
    assert cs[end:] == [1] * len(cs[end:])

    # Exactly 8 rising edges of SCLK, all inside the frame.
    edges = rising_edges(sclk)
    assert len(edges) == 8, f"rising edges of SCLK at {edges}"
    assert all(start < e < end for e in edges)

    # The slave's view of the byte: 0x96 MSB first.
    assert mode0_sampled(mosi, sclk, cs) == [1, 0, 0, 1, 0, 1, 1, 0]

    # Mode 0: SCLK is low when CS rises and stays low after.
    assert sclk[end - 1] == 0
    assert sclk[end:] == [0] * len(sclk[end:])

    # The pins are driven, and the byte was consumed exactly once.
    assert int(dut.gpio_oe.value) & 0b111 == 0b111
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.tx_full.value) == 0
