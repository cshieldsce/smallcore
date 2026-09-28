"""cocotb tests for rtl/top.v: the core between its TX and RX FIFOs. Run
through test_top.py, not directly.

The bench drives only top's host ports (tx_data, tx_push, rx_pop, ...). The
core's FIFO ports are wires inside top, so the paths under test are
host -> TX fifo.v -> core.v and core.v -> RX fifo.v -> host. Internals are
read hierarchically through VPI: dut.core_i.shift_reg, dut.tx_fifo.count.
"""

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from cpu import assemble, decode, load_isa, load_program  # sim/cpu.py
from tb import Imem, drive_host, reset, start_clock

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
BIT = 8  # clocks per UART bit in uart_tx_pull.asm and uart_rx.asm


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


# Full duplex: the bench also answers on MISO. The slave is a background task
# that sees CS and SCLK on gpio_out and drives gpio_in[MISO], nothing else.

MISO = 3  # gpio_in pin spi_duplex_lsb.asm and spi_duplex_msb.asm sample


def bits_lsb(byte):
    """The bits of `byte`, bit 0 first: the wire order of an LSB-first
    transfer. Reversed, the order of an MSB-first one."""
    return [(byte >> bit) & 1 for bit in range(8)]


async def mode0_slave(dut, bits):
    """Drive gpio_in[MISO] like a mode 0 slave sending `bits` in order. A bit
    goes on the pin on a falling edge of clk while CS is low and SCLK is low,
    so it is stable before the rising edge of SCLK on which the master
    samples; seeing that edge, the slave moves on to the next bit. After the
    last bit the pin holds. Nothing inside the core is read.

    Until the transfer starts the pin idles at the opposite of bit 0, so a
    master that samples before the slave has presented bit 0 gets the wrong
    bit with either first bit, instead of matching an idle level by luck."""
    i = 0
    prev_sclk = None  # no seed: the first sample is only a level
    dut.gpio_in.value = (1 - bits[0]) << MISO
    while i < len(bits):
        await FallingEdge(dut.clk)
        pins = int(dut.gpio_out.value)
        if (pins >> CS) & 1 == 0 and (pins >> SCLK) & 1 == 0:
            dut.gpio_in.value = bits[i] << MISO
        await RisingEdge(dut.clk)
        await ReadOnly()
        pins = int(dut.gpio_out.value)
        sclk = (pins >> SCLK) & 1
        if (pins >> CS) & 1 == 0 and prev_sclk == 0 and sclk == 1:
            i += 1  # the master took this bit on that edge
        prev_sclk = sclk


@cocotb.test()
async def spi_duplex_lsb_host_bytes_both_ways(dut):
    """programs/spi_duplex_lsb.asm end to end, both directions in one frame.
    The host pushes 0x96 into the TX FIFO; a mode 0 slave on gpio_in[3] sends
    0x53 while the master clocks 0x96 out. One transfer runs the TX FIFO,
    PULL, SHIFT_OUT, MOSI, SCLK, CS, MISO, SHIFT_IN, in_shift_reg, PUSH, the
    RX FIFO and the host pop. 0x96 and 0x53 differ and neither is a
    palindrome, so a crossed direction or a bit-order slip cannot pass."""
    program = load_program(PROGRAMS / "spi_duplex_lsb.asm")
    master_byte, slave_byte = 0x96, 0x53
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    cocotb.start_soon(mode0_slave(dut, bits_lsb(slave_byte)))  # 1 1 0 0 1 0 1 0
    await ReadOnly()
    assert (int(dut.gpio_out.value) >> CS) & 1 == 1  # CS idle high out of reset
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = master_byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    mosi, sclk, cs = await spi_pin_trace(dut)

    # Master to slave: one frame, eight clocks, 0x96 LSB first on MOSI, as in
    # the transmit-only test.
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    edges = rising_edges(sclk)
    assert len(edges) == 8 and all(start < e < end for e in edges), f"rising edges of SCLK at {edges}"
    assert mode0_sampled(mosi, sclk, cs) == [0, 1, 1, 0, 1, 0, 0, 1]
    assert sclk[end:] == [0] * len(sclk[end:])
    assert int(dut.tx_fifo.empty.value) == 1

    # Slave to master: the PUSH on the edge that raised CS put 0x53 in the RX
    # FIFO, rebuilt in normal order from the eight MISO samples.
    assert int(dut.rx_empty.value) == 0
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == slave_byte

    # Host pop, driven on the falling edge.
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1
    assert int(dut.rx_fifo.count.value) == 0


@cocotb.test()
async def spi_duplex_msb_host_bytes_both_ways(dut):
    """programs/spi_duplex_msb.asm end to end: the LSB duplex test with the
    other program and a slave that sends MSB first. The same two bytes must
    cross with both wire orders reversed, and the host must still read 0x53:
    SHIFT_IN under CONFIG shift_dir 1 fills in_shift_reg from the other end,
    so eight MSB-first samples land in normal order."""
    program = load_program(PROGRAMS / "spi_duplex_msb.asm")
    master_byte, slave_byte = 0x96, 0x53
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    cocotb.start_soon(mode0_slave(dut, bits_lsb(slave_byte)[::-1]))  # 0 1 0 1 0 0 1 1
    await ReadOnly()
    assert (int(dut.gpio_out.value) >> CS) & 1 == 1  # CS idle high out of reset
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = master_byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    mosi, sclk, cs = await spi_pin_trace(dut)

    # Master to slave: 0x96 MSB first on MOSI.
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    edges = rising_edges(sclk)
    assert len(edges) == 8 and all(start < e < end for e in edges), f"rising edges of SCLK at {edges}"
    assert mode0_sampled(mosi, sclk, cs) == [1, 0, 0, 1, 0, 1, 1, 0]
    assert sclk[end:] == [0] * len(sclk[end:])
    assert int(dut.tx_fifo.empty.value) == 1

    # Slave to master: 0x53 arrives whole whichever end went first.
    assert int(dut.rx_empty.value) == 0
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == slave_byte

    # Host pop, driven on the falling edge.
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1
    assert int(dut.rx_fifo.count.value) == 0


# I2C: the bench is the bus. Two open-drain lines with pull-ups, the master's
# pad on one end and a slave on the other. The bench cannot watch gpio_out
# alone: the pad drives a line only while gpio_oe says so, and gpio_in has
# to carry the resolved line back, or the master never sees the slave.

SDA, SCL = 0, 1  # the same pin numbers on gpio_out/gpio_oe (the pad) and gpio_in (the bus)


def od_line(out, oe, pin, slave_low):
    """One line: 0 if the pad pulls it low (gpio_oe set, gpio_out 0) or the
    slave does, else 1 from the pull-up. A pad driving a 1 against the slave's
    0 is a fight, which no open-drain master ever has, so it fails here."""
    driving = (oe >> pin) & 1
    level = (out >> pin) & 1
    assert not (driving and level and slave_low), f"pin {pin}: pad drives 1 against the slave's 0"
    return 0 if (driving and not level) or slave_low else 1


class I2cSlave:
    """A slave that ACKs every byte (or NACKs every byte, with ack=False).
    Open-drain like the master: it pulls a line low (sda_low, scl_low) or
    lets go. It reads the resolved bus one step behind, the way a real part
    does: START and STOP are SDA moving while SCL is high, a bit is SDA on a
    rising edge of SCL. After the eighth bit it takes SDA as SCL falls,
    before the ninth clock, holds it through that clock and lets go as that
    clock falls. With `stretch`, it also holds SCL low for that many steps
    after every falling edge of SCL, and the master has to wait for it.
    `events` is what it saw, in bus order: "START", each byte, "STOP"."""

    def __init__(self, ack=True, stretch=0):
        self.ack = ack
        self.stretch = stretch
        self.events = []
        self.sda = self.scl = 1  # the bus as last seen
        self.bits = []
        self.active = self.acking = self.sda_low = self.scl_low = False
        self.hold = 0  # steps left on the current stretch

    def update(self, sda, scl):
        if scl and self.scl and sda != self.sda:  # SDA moved with SCL high
            if sda == 0:
                self.active, self.acking, self.sda_low, self.bits = True, False, False, []
                self.events.append("START")
            else:
                self.active = False
                self.events.append("STOP")
        elif self.active and scl and not self.scl:  # SCL rose
            if not self.acking and len(self.bits) < 8:
                self.bits.append(sda)
        elif self.active and not scl and self.scl:  # SCL fell
            if self.acking:  # the ACK clock is over
                self.acking, self.sda_low, self.bits = False, False, []
            elif len(self.bits) == 8:
                self.events.append(int("".join(map(str, self.bits)), 2))
                self.acking, self.sda_low = True, self.ack
            self.hold = self.stretch
        self.sda, self.scl = sda, scl
        self.scl_low = self.hold > 0
        self.hold = max(self.hold - 1, 0)


async def i2c_bus(dut, slave, limit=300):
    """The wire, until the core halts plus a few clocks. On every falling edge
    of clk it resolves SDA and SCL from the pad and the slave, puts them on
    gpio_in[1:0] for the master's next edge, and shows them to the slave,
    whose answer lands on the next resolution. Returns four lists, one level
    per clock: sda, scl, and whether the pad was holding SDA low, SCL low."""
    sda, scl, pad_sda_low, pad_scl_low = [], [], [], []
    tail = 4  # clocks recorded after the halt
    for _ in range(limit):
        await FallingEdge(dut.clk)
        out, oe = int(dut.gpio_out.value), int(dut.gpio_oe.value)
        s = od_line(out, oe, SDA, slave.sda_low)
        c = od_line(out, oe, SCL, slave.scl_low)
        dut.gpio_in.value = (int(dut.gpio_in.value) & ~0b11) | s | (c << SCL)
        sda.append(s)
        scl.append(c)
        pad_sda_low.append(bool((oe >> SDA) & 1 and not (out >> SDA) & 1))
        pad_scl_low.append(bool((oe >> SCL) & 1 and not (out >> SCL) & 1))
        slave.update(s, c)
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.core_i.halted.value):
            tail -= 1
            if tail == 0:
                return sda, scl, pad_sda_low, pad_scl_low
    raise AssertionError(f"core still running after {limit} clocks")


def i2c_starts(sda, scl):
    """Clocks on which SDA fell with SCL high before and after."""
    return [i for i in falling_edges(sda) if scl[i - 1] == 1 and scl[i] == 1]


def i2c_stops(sda, scl):
    """Clocks on which SDA rose with SCL high before and after."""
    return [i for i in rising_edges(sda) if scl[i - 1] == 1 and scl[i] == 1]


@cocotb.test()
async def i2c_write_host_byte_to_bus_ack_to_host(dut):
    """programs/i2c_write.asm end to end with a slave that ACKs. The host
    pushes 0xA3 into the TX FIFO; the master STARTs, clocks it out MSB first,
    lets go of SDA for the ninth clock, samples the slave's ACK there, PUSHes
    that sample to the RX FIFO and STOPs. The bench resolves the bus every
    clock from gpio_out, gpio_oe and the slave, so the test spans the pad
    both ways: the byte out through gpio_oe, the ACK back in through gpio_in,
    SHIFT_IN, in_shift_reg, PUSH and the RX FIFO to rx_data."""
    program = load_program(PROGRAMS / "i2c_write.asm")
    byte = 0xA3
    slave = I2cSlave()
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0011  # the bus idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    sda, scl, pad_sda_low, _ = await i2c_bus(dut, slave)

    # The slave saw one transaction: START, the byte, STOP.
    assert slave.events == ["START", byte, "STOP"]

    # On the wire: one START, one STOP, and between them nine clocks, each a
    # fall then a rise, eight bits and the ACK; a tenth fall ends the ACK
    # clock and a tenth rise is the STOP's, which stays high.
    (start,), (stop,) = i2c_starts(sda, scl), i2c_stops(sda, scl)
    rises = [e for e in rising_edges(scl) if start < e < stop]
    falls = [e for e in falling_edges(scl) if start < e < stop]
    assert len(rises) == 10 and len(falls) == 10, f"SCL rose at {rises}, fell at {falls}"
    assert all(f < r for f, r in zip(falls, rises)) and all(r < f for r, f in zip(rises, falls[1:]))
    assert [sda[e] for e in rises[:8]] == [1, 0, 1, 0, 0, 0, 1, 1]  # 0xA3 MSB first

    # The ninth clock is the slave's: SDA is low because the slave holds it,
    # the pad has let go.
    assert sda[rises[8]] == 0
    assert not pad_sda_low[rises[8]]

    # Bus free: both lines high, and high because the pad let go, not drove.
    assert sda[-1] == 1 and scl[-1] == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0

    # The byte was consumed once; the ACK, a 0, reached the host.
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 0
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == 0

    # Host pop, driven on the falling edge.
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1


@cocotb.test()
async def i2c_write_host_byte_to_bus_nack_to_host(dut):
    """programs/i2c_write.asm with a slave that NACKs: the ACK test with the
    slave letting go of SDA on the ninth clock. The pad has let go too, so the
    pull-up puts a 1 on the bus, gpio_in[0] carries it in, SHIFT_IN samples
    it and the PUSH hands the host a 1. Everything else on the wire is the
    same: one START, the byte MSB first, ten clocks, one STOP."""
    program = load_program(PROGRAMS / "i2c_write.asm")
    byte = 0xA3
    slave = I2cSlave(ack=False)
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0011  # the bus idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    sda, scl, pad_sda_low, _ = await i2c_bus(dut, slave)

    # The slave still saw the whole transaction; it just did not answer.
    assert slave.events == ["START", byte, "STOP"]

    (start,), (stop,) = i2c_starts(sda, scl), i2c_stops(sda, scl)
    rises = [e for e in rising_edges(scl) if start < e < stop]
    falls = [e for e in falling_edges(scl) if start < e < stop]
    assert len(rises) == 10 and len(falls) == 10, f"SCL rose at {rises}, fell at {falls}"
    assert all(f < r for f, r in zip(falls, rises)) and all(r < f for r, f in zip(rises, falls[1:]))
    assert [sda[e] for e in rises[:8]] == [1, 0, 1, 0, 0, 0, 1, 1]  # 0xA3 MSB first

    # The ninth clock: nobody holds SDA, so the pull-up has it high.
    assert sda[rises[8]] == 1
    assert not pad_sda_low[rises[8]]

    # Bus free, both lines let go.
    assert sda[-1] == 1 and scl[-1] == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0

    # The byte was consumed once; the NACK, a 1, reached the host.
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 0
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == 1

    # Host pop, driven on the falling edge.
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1


@cocotb.test()
async def i2c_write_addr_data_both_acked(dut):
    """programs/i2c_write_addr_data.asm end to end with a slave that ACKs:
    address byte 0xA0 (0x50 written), data byte 0x3C, one START and STOP.
    The host preloads both bytes. After the address's ACK clock the sample
    sits in in_shift_reg bit 0 and SKIP 0, 0 reads it there: a 0 steps over
    the JMP to the STOP, so the second PULL takes the data byte. The slave's
    electrical answer decides what the core fetches next. Both ACKs reach
    the host through the RX FIFO, popped as a host would, head first."""
    program = load_program(PROGRAMS / "i2c_write_addr_data.asm")
    address, data = 0xA0, 0x3C  # 0x50 << 1 | write
    slave = I2cSlave()
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0011  # the bus idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host pushes both bytes on consecutive edges with the core halted, then
    # releases it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = address
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_data.value = data
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    await ReadOnly()
    assert int(dut.tx_fifo.count.value) == 2
    await FallingEdge(dut.clk)
    dut.program_words.value = len(program)

    sda, scl, pad_sda_low, _ = await i2c_bus(dut, slave)

    # The slave saw one transaction of two bytes.
    assert slave.events == ["START", address, data, "STOP"]

    # On the wire: nineteen clocks between START and STOP, nine per byte
    # (eight bits and the ACK), a fall ending the last ACK clock and the
    # STOP's rise, which stays high.
    (start,), (stop,) = i2c_starts(sda, scl), i2c_stops(sda, scl)
    rises = [e for e in rising_edges(scl) if start < e < stop]
    falls = [e for e in falling_edges(scl) if start < e < stop]
    assert len(rises) == 19 and len(falls) == 19, f"SCL rose at {rises}, fell at {falls}"
    assert all(f < r for f, r in zip(falls, rises)) and all(r < f for r, f in zip(rises, falls[1:]))
    assert [sda[e] for e in rises[0:8]] == [1, 0, 1, 0, 0, 0, 0, 0]  # 0xA0 MSB first
    assert [sda[e] for e in rises[9:17]] == [0, 0, 1, 1, 1, 1, 0, 0]  # 0x3C MSB first

    # Both ACK clocks: the slave holds SDA low, the pad has let go.
    for ack in (rises[8], rises[17]):
        assert sda[ack] == 0 and not pad_sda_low[ack]

    # Bus free, both lines let go.
    assert sda[-1] == 1 and scl[-1] == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0

    # Both bytes were consumed; two ACKs wait for the host, address's first.
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_fifo.count.value) == 2
    assert int(dut.rx_data.value) == 0

    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == 0

    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1


@cocotb.test()
async def i2c_write_addr_data_addr_nacked(dut):
    """programs/i2c_write_addr_data.asm with a slave that NACKs: the mirror of
    the both-ACK test. Same two bytes preloaded. The NACK on the address
    clock is a 1 in in_shift_reg bit 0, so SKIP 0, 0 is not taken, the JMP
    runs and the master STOPs one clock later. Only the address's ten clocks
    reach the wire; the second PULL never runs and 0x3C stays at the head of
    the TX FIFO. The host gets one sample, the NACK."""
    program = load_program(PROGRAMS / "i2c_write_addr_data.asm")
    address, data = 0xA0, 0x3C  # 0x50 << 1 | write
    slave = I2cSlave(ack=False)
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0011  # the bus idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host pushes both bytes on consecutive edges with the core halted, then
    # releases it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = address
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_data.value = data
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    await ReadOnly()
    assert int(dut.tx_fifo.count.value) == 2
    await FallingEdge(dut.clk)
    dut.program_words.value = len(program)

    sda, scl, pad_sda_low, _ = await i2c_bus(dut, slave)

    # The slave saw the address and a STOP, no data byte.
    assert slave.events == ["START", address, "STOP"]

    # On the wire: the address's nine clocks, the fall ending its ACK clock
    # and the STOP's rise, as in the one-byte tests. No data clocks.
    (start,), (stop,) = i2c_starts(sda, scl), i2c_stops(sda, scl)
    rises = [e for e in rising_edges(scl) if start < e < stop]
    falls = [e for e in falling_edges(scl) if start < e < stop]
    assert len(rises) == 10 and len(falls) == 10, f"SCL rose at {rises}, fell at {falls}"
    assert all(f < r for f, r in zip(falls, rises)) and all(r < f for r, f in zip(rises, falls[1:]))
    assert [sda[e] for e in rises[0:8]] == [1, 0, 1, 0, 0, 0, 0, 0]  # 0xA0 MSB first

    # The ACK clock: nobody holds SDA, the pull-up has it high.
    assert sda[rises[8]] == 1 and not pad_sda_low[rises[8]]

    # Bus free, both lines let go.
    assert sda[-1] == 1 and scl[-1] == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0

    # The data byte was never pulled: it is still the head of the TX FIFO.
    assert int(dut.tx_fifo.count.value) == 1
    assert int(dut.tx_fifo.head_data.value) == data
    assert int(dut.tx_full.value) == 0

    # One sample for the host, the NACK.
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == 1

    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1


@cocotb.test()
async def i2c_write_stretch_slave_holds_scl_master_waits(dut):
    """programs/i2c_write_stretch.asm with a slave that ACKs and holds SCL
    low for 8 steps after every falling edge. The program lets go of SCL
    with SET 1, 1 and then WAIT 1, 1 until the bus really is high, so the
    high phase starts from the rise the bus shows. The master's own low
    phase covers 3 of the 8 steps (its release reaches the bus on the 4th),
    so every low phase is 5 clocks longer than the 4 of i2c_write.asm and
    the transaction 50 clocks longer over its ten clocks, the same numbers
    as the model's test. The byte, the ACK and the STOP are unchanged."""
    program = load_program(PROGRAMS / "i2c_write_stretch.asm")
    byte = 0xA3
    stretch = 8
    slave = I2cSlave(stretch=stretch)
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0011  # the bus idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    sda, scl, pad_sda_low, pad_scl_low = await i2c_bus(dut, slave)

    # The transaction is still right: one START, the byte, the ACK, one STOP.
    assert slave.events == ["START", byte, "STOP"]
    (start,), (stop,) = i2c_starts(sda, scl), i2c_stops(sda, scl)
    rises = [e for e in rising_edges(scl) if start < e < stop]
    falls = [e for e in falling_edges(scl) if start < e < stop]
    assert len(rises) == 10 and len(falls) == 10, f"SCL rose at {rises}, fell at {falls}"
    assert all(f < r for f, r in zip(falls, rises)) and all(r < f for r, f in zip(rises, falls[1:]))
    assert [sda[e] for e in rises[:8]] == [1, 0, 1, 0, 0, 0, 1, 1]  # 0xA3 MSB first
    assert sda[rises[8]] == 0 and not pad_sda_low[rises[8]]
    assert sda[-1] == 1 and scl[-1] == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_fifo.count.value) == 1
    assert int(dut.rx_data.value) == 0

    # Stretching happened on the wire: clocks where the pad had let go of SCL
    # and the bus was still low, held by the slave. Five per clock, ten clocks.
    over = stretch - 3
    held = [i for i in range(len(scl)) if scl[i] == 0 and not pad_scl_low[i]]
    assert len(held) == 10 * over, f"SCL held low by the slave on {len(held)} clocks"
    assert all(start < i < stop for i in held)

    # The master waited: every low phase is the slave's length, every high
    # phase is still 4 clocks from the rise the bus showed.
    assert [u - d for d, u in zip(falls, rises)] == [4 + over] * 10, "low phases"
    assert [d - u for u, d in zip(rises, falls[1:])] == [4] * 9, "high phases"

    await FallingEdge(dut.clk)
    dut.rx_pop.value = 1
    await FallingEdge(dut.clk)
    dut.rx_pop.value = 0
    await ReadOnly()
    assert int(dut.rx_empty.value) == 1


# SWD: the bench is the wire and the target. Stage 1, the request: the host
# owns SWDIO and the target takes it on every rising edge of SWCLK. Stage 2,
# the turnaround: after the park bit the host lets go of SWDIO for one clock.
# Stage 3, the ACK: the target takes the line on the turnaround's rise with
# ACK[0], then ACK[1], ACK[2]; the host samples the three and PUSHes them.
# Stage 4, the decision: WAIT sends the request again when the host supplies
# it again, FAULT exits, both after a turnaround back that gives the host the
# line; OK goes on. Stage 5, the read data (swd_read.asm): on OK the target
# keeps the line and drives 32 data bits and a parity bit; the host PUSHes a
# byte per eight, the parity in a fifth byte, then takes the line back. Stage
# 6, the write data (swd_write.asm): on OK, after the turnaround back, the
# host clocks out 32 data bits and the parity from five more TX FIFO bytes.
# The bench resolves SWDIO every clock from the pad (gpio_out, gpio_oe), the
# target and a pull-up, and feeds it back on gpio_in, the pad readback.

SWDIO, SWCLK = 0, 1  # the same pin numbers on gpio_out/gpio_oe (the pad) and gpio_in (the wire): SWDIO is the shift pin
SWD_OK, SWD_WAIT, SWD_FAULT = 1, 2, 4  # the ACK, ACK[0] first on the wire
SWD_CLOCKS = 13  # rises of SWCLK in a transaction without data: the request, the turnaround, the ACK, the turnaround back
SWD_READ_CLOCKS = 46  # in a read the target says OK to: 32 data bits and the parity between the ACK and the turnaround back
SWD_WRITE_CLOCKS = 46  # in a write the target says OK to: the turnaround back, then 32 data bits and the parity from the host


class SwdTarget:
    """A target on the wire. It follows the clock: on each rising edge of SWCLK
    it samples the line as it stood at the edge. The first eight samples of a
    transaction are a request, checked after the eighth, start 1, stop 0,
    park 1, parity right, and appended to `requests` as the byte the host
    sent. On the ninth rise, the turnaround's, the target takes the line with
    ACK[0] of the next answer in `acks` (the last one repeats), moves to
    ACK[1] and ACK[2] on the next two. Then, for a read (RnW set) it said OK
    to, it drives `data` bit 0 up from the twelfth rise, one bit per rise, the
    parity from the forty-fourth, lets go on the forty-fifth and is ready for
    the next request after the forty-sixth, the host's turnaround. For a
    write (RnW clear) it said OK to, it lets go on the twelfth, the
    thirteenth is the host's turnaround, and it samples the host's data bits
    on the next 32 rises and the parity on the forty-sixth, appending (word,
    parity ok) to `written`. Otherwise it lets go on the twelfth and is ready
    after the thirteenth. `drive` is what it puts on the wire: 0, 1 or None."""

    def __init__(self, acks=(SWD_OK,), data=0):
        self.acks = list(acks)
        self.data = data
        self.parity = bin(data).count("1") & 1
        self.swclk = 1  # the clock as last seen: every pin is high out of reset
        self.rises = 0  # in this transaction
        self.samples = []
        self.requests = []
        self.written = []
        self.drive = None

    def update(self, swdio, swclk):
        if swclk and not self.swclk:
            self.rises += 1
            n = self.rises
            if n <= 8:
                self.samples.append(swdio)
                if n == 8:
                    start, apndp, rnw, a2, a3, parity, stop, park = self.samples
                    assert (start, stop, park) == (1, 0, 1), f"bad request framing: {self.samples}"
                    assert parity == apndp ^ rnw ^ a2 ^ a3, f"request parity error: {self.samples}"
                    self.requests.append(sum(bit << i for i, bit in enumerate(self.samples)))
            else:
                ack = self.acks[min(len(self.requests) - 1, len(self.acks) - 1)]
                rnw = (self.requests[-1] >> 2) & 1
                reading, writing = rnw == 1 and ack == SWD_OK, rnw == 0 and ack == SWD_OK
                if n <= 11:
                    self.drive = (ack >> (n - 9)) & 1
                elif reading and n <= 43:
                    self.drive = (self.data >> (n - 12)) & 1
                elif reading and n == 44:
                    self.drive = self.parity
                elif n == (45 if reading else 12):
                    self.drive = None
                elif writing and n == 13:
                    pass  # the host's turnaround back: it takes the line as this clock falls
                elif writing and n <= 46:
                    self.samples.append(swdio)  # data bits 0..31 on rises 14..45, the parity on 46
                    if n == 46:
                        bits = self.samples[8:]
                        word = sum(bit << i for i, bit in enumerate(bits[:32]))
                        self.written.append((word, bits[32] == bin(word).count("1") & 1))
                        self.rises, self.samples = 0, []
                else:  # the host's turnaround: whatever comes next is a new request
                    self.rises, self.samples = 0, []
        self.swclk = swclk
        return self.drive


async def swd_wire(dut, target, limit=600):
    """The wire, until the core halts plus a few clocks. On every falling edge
    of clk it shows the target the wire as it stood for the host's last edge,
    resolves SWDIO from the pad, the target's answer and the pull-up, puts it
    on gpio_in[0] for the host's next edge, and records it. A pad driving
    against the target is a fight, which no working host has: it fails here.
    Returns four lists, one entry per clock: swdio (the wire), swclk, whether
    the pad was driving SWDIO, and what the target drove (0, 1 or None)."""
    swdio, swclk, host_drives, target_drives = [], [], [], []
    line = 1
    tail = 4  # clocks recorded after the halt
    for _ in range(limit):
        await FallingEdge(dut.clk)
        out, oe = int(dut.gpio_out.value), int(dut.gpio_oe.value)
        clock = (out >> SWCLK) & 1
        drive = target.update(line, clock)
        driving = (oe >> SWDIO) & 1
        pad = (out >> SWDIO) & 1 if driving else None
        assert not (pad is not None and drive is not None and pad != drive), f"the pad drives {pad} against the target's {drive}"
        line = pad if pad is not None else drive if drive is not None else 1
        dut.gpio_in.value = (int(dut.gpio_in.value) & ~(1 << SWDIO)) | (line << SWDIO)
        swdio.append(line)
        swclk.append(clock)
        host_drives.append(driving)
        target_drives.append(drive)
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.core_i.halted.value):
            tail -= 1
            if tail == 0:
                return swdio, swclk, host_drives, target_drives
    raise AssertionError(f"core still running after {limit} clocks")


async def swd_write_host(dut, request, payload, received, delay=0):
    """The host doing one write the way the FIFOs ask. It pushes the request
    and nothing else, because a WAIT would make the retry PULL a data byte as
    the request; it pops every byte the core PUSHes into `received`; on a
    WAIT it queues the request again, `delay` clocks later, on an OK the
    `payload`, the four data bytes and the parity byte; and it pushes one
    queued byte per clock while tx_full is low. Runs until cancelled. Pushes
    and pops are levels on top's ports: held high across a clock, each acts
    on that clock."""
    queue = [request]
    acks = 0
    due = None  # clocks to go before the request is queued again
    while True:
        await FallingEdge(dut.clk)
        dut.tx_push.value = 0
        dut.rx_pop.value = 0
        if int(dut.rx_empty.value) == 0:
            received.append(int(dut.rx_data.value))
            dut.rx_pop.value = 1
        if len(received) > acks:
            acks = len(received)
            ack = received[-1] >> 5
            if ack == SWD_WAIT:
                due = delay
            elif ack == SWD_OK:
                queue.extend(payload)
        if due is not None:
            if due == 0:
                queue.append(request)
                due = None
            else:
                due -= 1
        if queue and int(dut.tx_full.value) == 0:
            dut.tx_data.value = queue.pop(0)
            dut.tx_push.value = 1


def swd_payload(data, parity=None):
    """What the host queues after a write request the target said OK to: the
    four data bytes from bit 0 up and a fifth byte whose bit 0 is the parity,
    the host's to compute because the core has no XOR."""
    parity = bin(data).count("1") & 1 if parity is None else parity
    return [(data >> (8 * i)) & 0xFF for i in range(4)] + [parity]


async def swd_host_drain(dut, received):
    """The host at the RX port during a read: whenever a byte is there it reads
    rx_data and pops it, one pop per clock, appending to `received`. Runs
    until cancelled."""
    while True:
        await FallingEdge(dut.clk)
        if int(dut.rx_empty.value) == 0:
            received.append(int(dut.rx_data.value))
            dut.rx_pop.value = 1
            await FallingEdge(dut.clk)
            dut.rx_pop.value = 0


async def swd_log(dut, log):
    """One entry per falling edge of clk, (imem_addr, RX FIFO full), indexed
    like swd_wire's lists when started on the same edge. imem_addr is the pc
    on a pin. Runs until cancelled."""
    while True:
        await FallingEdge(dut.clk)
        log.append((int(dut.imem_addr.value), int(dut.rx_fifo.full.value)))


async def swd_sleeping_host(dut, received, pops, sleep):
    """The host that does not read: nothing until the RX FIFO is full, then
    `sleep` more clocks, then one pop, `sleep` clocks again, one more pop,
    and only then a drain, one byte per clock. Counts clocks from its start,
    indexed like swd_wire's lists when started on the same edge, and appends
    the index of every clock it raised rx_pop on to `pops`. Runs until
    cancelled."""
    phase, timer, i = "asleep", 0, -1
    while True:
        await FallingEdge(dut.clk)
        i += 1
        dut.rx_pop.value = 0
        if phase == "asleep":
            if int(dut.rx_fifo.full.value):
                phase, timer = "one", sleep
        elif phase in ("one", "two"):
            timer -= 1
            if timer == 0:
                received.append(int(dut.rx_data.value))
                dut.rx_pop.value = 1
                pops.append(i)
                phase, timer = ("two", sleep) if phase == "one" else ("draining", 0)
        elif int(dut.rx_empty.value) == 0:
            received.append(int(dut.rx_data.value))
            dut.rx_pop.value = 1
            pops.append(i)


@cocotb.test()
async def swd_write_host_word_to_wire(dut):
    """programs/swd_write.asm end to end with a target that says OK. The host
    pushes 0xA9, a DP write to A[3:2] = 01: Start 1, APnDP 0, RnW 0, A2 1, A3
    0, parity 1, Stop 0, Park 1, and, once it has read the OK, the word
    0xE31D5396 as four bytes from bit 0 up and a fifth with the parity, 1
    for 17 ones, in bit 0, feeding the 4-deep TX FIFO as room appears. On the
    wire: the request (1 0 0 1 0 1 0 1, not a palindrome, so a bit-order
    slip fails), the turnaround, OK, the turnaround back, then the host owns
    the line and clocks out the 32 data bits and the parity, a PULL per byte
    in a clock's last high cycle. The target sees the request, then the word
    with a good parity. The host reads 0x20 and nothing else; 46 clocks; all
    six bytes consumed; halted owning the line."""
    program = load_program(PROGRAMS / "swd_write.asm")
    byte, data = 0xA9, 0xE31D5396
    target = SwdTarget([SWD_OK])
    received = []
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0001  # the wire idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.gpio_out.value) & 0b11 == 0b11  # both lines high out of reset
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # The host pushes the request, then release the core.
    host = cocotb.start_soon(swd_write_host(dut, byte, swd_payload(data), received))
    await FallingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.program_words.value = len(program)

    swdio, swclk, host_drives, target_drives = await swd_wire(dut, target)
    host.cancel()
    assert len(swclk) == 384 + 2, f"{len(swclk) - 2} clocks from release to halt, the model's write takes 384"  # one entry per clock through the halting edge, two after

    # 46 rises: 8 request, the turnaround, 3 ACK, the turnaround back, 32
    # data, the parity. 8 clocks apart, but for the branch and the first
    # PULL between the turnaround back and data bit 0. What a rise takes is
    # the wire as it stood at the edge, the entry before the one that shows
    # the clock high.
    ups, downs = rising_edges(swclk), falling_edges(swclk)
    assert len(ups) == SWD_WRITE_CLOCKS, f"rising edges of SWCLK at {ups}"
    gaps = [b - a for a, b in zip(ups, ups[1:])]
    assert gaps[:12] == [8] * 12 and gaps[13:] == [8] * 32
    assert gaps[12] == 8 + 4 + 3, "the take-back word's low half, two SKIPs, the JMP and the PULL"
    assert [d - u for u, d in zip(ups, [d for d in downs if d > ups[0]])] == [4] * SWD_WRITE_CLOCKS
    taken = [swdio[e - 1] for e in ups]

    # The target's view: the request, OK given, the word and its parity taken.
    assert taken[:8] == [1, 0, 0, 1, 0, 1, 0, 1]
    assert target.requests == [byte]
    assert taken[8] == 1 and taken[12] == 1, "both turnaround edges find the pull-up"
    assert taken[9:12] == [1, 0, 0]
    assert taken[13:45] == [(data >> i) & 1 for i in range(32)]
    assert taken[45] == 1, "parity of 17 ones"
    assert target.written == [(data, True)]

    # Who drove: the host through the park bit and from the turnaround back
    # to the end, the target from the turnaround's rise to the third ACK
    # rise, nobody through either turnaround.
    release, trn, last, retake = ups[7] + 4, ups[8], ups[11], ups[12] + 4
    assert host_drives[:release] == [1] * release, "the host let go before the park bit was clocked"
    assert host_drives[release:retake] == [0] * (retake - release), "the host drove while the target had the line"
    assert host_drives[retake:] == [1] * len(host_drives[retake:]), "the host let go of the line during the data"
    assert target_drives[:trn] == [None] * trn
    assert None not in target_drives[trn:last], "the target let go during the ACK"
    assert target_drives[last:] == [None] * len(target_drives[last:]), "the target drove after the ACK"
    assert swclk[downs[-1]:] == [0] * len(swclk[downs[-1]:]), "SWCLK idle low after the transaction"

    # The host read the ACK and nothing else; every byte it queued went out.
    assert received == [SWD_OK << 5]
    assert int(dut.rx_empty.value) == 1
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.halted.value) == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0b11
    assert (int(dut.gpio_out.value) >> SWCLK) & 1 == 0


@cocotb.test()
async def swd_write_wait_sends_the_request_again_ok_writes_the_word(dut):
    """programs/swd_write.asm with a target that says WAIT, then OK. The core
    cannot keep a copy of the request (SHIFT_OUT empties shift_reg and only
    PULL reloads it), so WAIT is a JMP back to the PULL and the host supplies
    the request again; and the host must not have queued the data behind the
    request, or that retry would PULL data byte 0 as the request: it queues
    the data only on the OK. On the wire: a 13-clock transaction answered
    WAIT, the host owning the line between, then a 46-clock one answered OK
    with the word 0xE31D5396 written. The host reads 0x40 then 0x28: OK in
    bits 7:5 with the WAIT's bit walked down to bit 3, because in_shift_reg
    keeps shifting; the ACK is the byte >> 5 either way."""
    program = load_program(PROGRAMS / "swd_write.asm")
    byte, data = 0xA9, 0xE31D5396
    target = SwdTarget([SWD_WAIT, SWD_OK])
    received = []
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0001  # the wire idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    host = cocotb.start_soon(swd_write_host(dut, byte, swd_payload(data), received))
    await FallingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.program_words.value = len(program)

    swdio, swclk, host_drives, target_drives = await swd_wire(dut, target)
    host.cancel()

    # Two transactions: thirteen rises answered WAIT, then 46 answered OK,
    # SWCLK low between them while the host reads the WAIT and pushes again.
    ups = rising_edges(swclk)
    assert len(ups) == SWD_CLOCKS + SWD_WRITE_CLOCKS, f"rising edges of SWCLK at {ups}"
    gaps = [b - a for a, b in zip(ups, ups[1:])]
    assert gaps[:12] == [8] * 12 and gaps[13:25] == [8] * 12 and gaps[26:] == [8] * 32
    assert swclk[ups[12] + 4:ups[13]] == [0] * (ups[13] - ups[12] - 4), "SWCLK moved between the transactions"
    taken = [swdio[e - 1] for e in ups]

    # The target saw the same request twice, answered WAIT then OK, took the word.
    assert target.requests == [byte, byte]
    assert taken[:8] == taken[13:21] == [1, 0, 0, 1, 0, 1, 0, 1]
    assert taken[9:12] == [0, 1, 0]
    assert taken[22:25] == [1, 0, 0]
    assert taken[26:58] == [(data >> i) & 1 for i in range(32)] and taken[58] == 1
    assert target.written == [(data, True)]

    # The host owned the line from the first turnaround back through the
    # second request's park bit, and from the second turnaround back to the
    # end; the target drove only its two ACKs.
    retake1, release2, retake2 = ups[12] + 4, ups[20] + 4, ups[25] + 4
    assert host_drives[retake1:release2] == [1] * (release2 - retake1), "the host let go between the transactions"
    assert host_drives[release2:retake2] == [0] * (retake2 - release2)
    assert host_drives[retake2:] == [1] * len(host_drives[retake2:])
    drove = [i for i, d in enumerate(target_drives) if d is not None]
    first, second = [i for i in drove if i < ups[13]], [i for i in drove if i >= ups[13]]
    assert first and first[0] == ups[8] and first[-1] == ups[11] - 1, "first ACK: from the turnaround's rise to the third ACK rise"
    assert second and second[0] == ups[21] and second[-1] == ups[24] - 1, "second ACK"
    assert len(drove) == len(first) + len(second), "the target drove outside its ACKs"

    # The host read WAIT then OK; everything it pushed was consumed; halted owning the line.
    assert received == [SWD_WAIT << 5, SWD_OK << 5 | SWD_WAIT << 2]
    assert [b >> 5 for b in received] == [SWD_WAIT, SWD_OK]
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1
    assert int(dut.halted.value) == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0b11


@cocotb.test()
async def swd_read_ok_data_and_parity_to_host(dut):
    """programs/swd_read.asm end to end with a target that says OK and has
    0xE31D5396 to give. The host pushes 0x8D, a DP read of A[3:2] = 01: Start
    1, APnDP 0, RnW 1, A2 1, A3 0, parity 0, Stop 0, Park 1, and drains the
    RX FIFO as bytes land, as a host reading a word must (the FIFO holds four
    and a read is six). On the wire: the request, the turnaround, OK, then no
    turnaround: the target keeps the line and the host samples 32 data bits
    from bit 0 up and the parity on the next 33 rises, one clock with nobody
    driving, and the host takes the line back. The host reads 0x20, then
    0x96 0x53 0x1D 0xE3 (none a palindrome, so a bit-order slip in the data
    fails), then 0xF1: the parity, 1 for 17 ones, as bit 7 over data[31:25].
    46 clocks, both requests' bytes consumed, halted owning the line."""
    program = load_program(PROGRAMS / "swd_read.asm")
    byte, data = 0x8D, 0xE31D5396
    target = SwdTarget([SWD_OK], data)
    received = []
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0001  # the wire idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    # Host push with the core halted, then release it on the next falling edge.
    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)
    drain = cocotb.start_soon(swd_host_drain(dut, received))

    swdio, swclk, host_drives, target_drives = await swd_wire(dut, target)
    drain.cancel()
    assert len(swclk) == 379 + 2, f"{len(swclk) - 2} clocks from release to halt, the model's read takes 379"  # one entry per clock through the halting edge, two after

    # 46 rises: 8 request, the turnaround, 3 ACK, 32 data, the parity, the
    # turnaround back. Request, turnaround and ACK clocks 8 apart; the branch
    # stretches the third ACK clock by two words; data clocks 8 apart again.
    ups = rising_edges(swclk)
    assert len(ups) == SWD_READ_CLOCKS, f"rising edges of SWCLK at {ups}"
    gaps = [b - a for a, b in zip(ups, ups[1:])]
    assert gaps[:11] == [8] * 11 and gaps[12:] == [8] * 33 and gaps[11] == 8 + 2
    taken = [swdio[e - 1] for e in ups]

    # The target's view: the read request, then what it drove is what the host took.
    assert taken[:8] == [1, 0, 1, 1, 0, 0, 0, 1]
    assert target.requests == [byte]
    assert taken[8] == 1, "the turnaround's edge finds the pull-up"
    assert taken[9:12] == [1, 0, 0]
    assert taken[12:44] == [(data >> i) & 1 for i in range(32)]
    assert taken[44] == 1, "parity of 17 ones"
    assert taken[45] == 1, "the turnaround back's edge finds the pull-up"

    # Who drove: the host through the park bit and from the turnaround back
    # on, the target from the turnaround's rise to the parity's, nobody in
    # between or through either turnaround.
    release, trn, last, retake = ups[7] + 4, ups[8], ups[44], ups[45] + 4
    assert host_drives[:release] == [1] * release
    assert host_drives[release:retake] == [0] * (retake - release), "the host drove while the target had the line"
    assert host_drives[retake:] == [1] * len(host_drives[retake:]), "the host did not take the line back"
    assert target_drives[:trn] == [None] * trn
    assert None not in target_drives[trn:last], "the target let go before the parity was taken"
    assert target_drives[last:] == [None] * len(target_drives[last:]), "the target kept the line after the parity"
    assert swclk[ups[45] + 4:] == [0] * len(swclk[ups[45] + 4:]), "SWCLK idle low after the transaction"

    # What the host read, in order, and the state at the end.
    assert received == [SWD_OK << 5, 0x96, 0x53, 0x1D, 0xE3, 0xF1]
    assert int(dut.rx_empty.value) == 1
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.halted.value) == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0b11
    assert int(dut.gpio_out.value) & 0b11 == 0b01


@cocotb.test()
async def swd_read_sleeping_host_stalls_the_fifth_push_and_resumes_once(dut):
    """The adversarial read: programs/swd_read.asm, a target that says OK and
    has 0xE31D5396, and a host that reads nothing until the RX FIFO is full,
    then sleeps 200 more clocks. Four PUSHes fill it (the ACK, data bytes 0,
    1, 2); the fifth, data byte 3's, finds it full right after the
    thirty-second data bit and the core stops there for the whole sleep, at
    the pins: SWCLK stopped high without a glitch; the pad off SWDIO, the
    target holding bit 31; imem_addr, the pc, on the PUSH; the FIFO full the
    whole time, so no PUSH repeated. The host pops one byte and execution
    resumes exactly once: one more rise (the parity's), imem_addr through the
    PUSH, the parity's SHIFT_IN and the parity's PUSH once each, the FIFO
    full again with the one byte that PUSH added, SWCLK high and still for
    the second sleep. The host pops again, then drains: 46 rises in all and
    the six bytes, byte 3 and the parity whole, which is the proof at the
    pins that no sample repeated while the clock stood."""
    program = load_program(PROGRAMS / "swd_read.asm")
    isa = load_isa()
    pushes = [i for i, w in enumerate(program) if decode(w, isa).op == "PUSH"]
    byte, data, sleep, held = 0x8D, 0xE31D5396, 200, 100  # the host sleeps 200 clocks from the FIFO filling: the stall begins 64 later and is held at least 100
    target = SwdTarget([SWD_OK], data)
    received, pops, log = [], [], []
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0001  # the wire idles high
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    await FallingEdge(dut.clk)
    dut.tx_data.value = byte
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)
    host = cocotb.start_soon(swd_sleeping_host(dut, received, pops, sleep))
    logger = cocotb.start_soon(swd_log(dut, log))

    swdio, swclk, host_drives, target_drives = await swd_wire(dut, target, limit=1200)
    host.cancel()
    logger.cancel()
    assert len(log) == len(swclk), "the log and the wire count different clocks"
    pcs, full = [pc for pc, _ in log], [f for _, f in log]
    ups = rising_edges(swclk)
    assert len(ups) == SWD_READ_CLOCKS, f"rising edges of SWCLK at {ups}"
    first, second = pops[0], pops[1]

    # The first stall: from four clocks after the thirty-second data bit's
    # rise, when the PUSH found the FIFO full, to the host's first pop.
    stop = ups[43] + 4
    assert first - stop >= held, "the host popped before the stall had settled"
    still = slice(stop, first + 1)
    assert set(swclk[still]) == {1}, "SWCLK moved while the host slept"
    assert set(host_drives[still]) == {0}, "the pad drove SWDIO during the stall"
    assert set(target_drives[still]) == set(swdio[still]) == {(data >> 31) & 1}, "the target holds data bit 31 and the wire shows it"
    assert set(pcs[still]) == {pushes[-2]}, "the pc moved off data byte 3's PUSH"
    assert set(full[still]) == {1}, "the FIFO was not full the whole stall"
    assert full[first + 1] == 0, "the pop made room"

    # The resume: one rise, three addresses once each, full again, still again.
    assert [e for e in ups if first < e <= second] == [ups[44]], "not exactly one more rise, the parity's"
    visited = [pc for i, pc in enumerate(pcs[first:second + 1]) if i == 0 or pc != pcs[first:second + 1][i - 1]]
    assert visited == [pushes[-2], pushes[-2] + 1, pushes[-1]], "the PUSH, the parity's SHIFT_IN, the parity's PUSH, once each"
    assert second - (ups[44] + 4) >= held, "the second stall was not held"
    again = slice(ups[44] + 4, second + 1)
    assert set(swclk[again]) == {1} and set(pcs[again]) == {pushes[-1]} and set(full[again]) == {1}
    assert set(host_drives[again]) == {0} and set(target_drives[again]) == {None} and set(swdio[again]) == {1}, "after the parity the target let go: the wire at the pull-up, the pad still off"

    # After the second pop: the turnaround back and the halt; six bytes, whole.
    assert ups[45] > second
    assert received == [SWD_OK << 5, 0x96, 0x53, 0x1D, 0xE3, 0xF1]
    assert len(pops) == 6
    assert int(dut.rx_empty.value) == 1
    assert int(dut.halted.value) == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0b11
    assert int(dut.gpio_out.value) & 0b11 == 0b01


@cocotb.test()
async def swd_write_wait_host_takes_its_time_to_push_the_request_again(dut):
    """The WAIT retry's question: the core cannot resend the request, so the
    host pushes it again; must it hurry? programs/swd_write.asm, a target
    that says WAIT then OK, and a host that takes 150 clocks after reading
    the WAIT to push the request again. After the turnaround back the
    retry's PULL finds the TX FIFO empty and the core stands still with
    SWCLK low, SWDIO high and the pad's, imem_addr on the PULL, the target
    seeing no edge to count, until the byte lands. Then the second
    transaction is the prompt host's, 46 rises eight clocks apart (the
    turnaround back to data bit 0 fifteen), the target takes the word with a
    good parity. SWD moves on SWCLK alone: a slow host costs time, not
    correctness."""
    program = load_program(PROGRAMS / "swd_write.asm")
    byte, data, delay = 0xA9, 0xE31D5396, 150
    target = SwdTarget([SWD_WAIT, SWD_OK])
    received, log = [], []
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0001
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1

    host = cocotb.start_soon(swd_write_host(dut, byte, swd_payload(data), received, delay=delay))
    await FallingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.program_words.value = len(program)
    logger = cocotb.start_soon(swd_log(dut, log))

    swdio, swclk, host_drives, target_drives = await swd_wire(dut, target, limit=1000)
    host.cancel()
    logger.cancel()
    assert len(log) == len(swclk)
    pcs = [pc for pc, _ in log]
    ups = rising_edges(swclk)
    assert len(ups) == SWD_CLOCKS + SWD_WRITE_CLOCKS, f"rising edges of SWCLK at {ups}"
    gaps = [b - a for a, b in zip(ups, ups[1:])]
    assert gaps[:12] == [8] * 12 and gaps[13:25] == [8] * 12 and gaps[25] == 8 + 4 + 3 and gaps[26:] == [8] * 32

    # The idle: the turnaround back's high half, the take-back's low half,
    # SKIP, SKIP, JMP, then the PULL at address 1 holds until the byte lands,
    # four clocks of PULL and four of SHIFT_OUT before the second request's
    # first rise. Longer than the prompt host's 19 by the host's delay less
    # the thirteen clocks it had in hand: the WAIT reaches it that long
    # before the PULL wants the byte.
    idle = slice(ups[12] + 11, ups[13] - 8)
    assert gaps[12] == 19 + delay - 13, f"the gap between the transactions was {gaps[12]}"
    assert idle.stop - idle.start == delay - 13
    assert set(pcs[idle]) == {1}, "the core was somewhere other than the request's PULL while the host took its time"
    assert set(pcs[ups[12] + 4:ups[12] + 11]) != {1}, "the words before the PULL"
    between = slice(ups[12] + 4, ups[13])
    assert set(swclk[between]) == {0}, "SWCLK moved between the transactions"
    assert set(host_drives[between]) == {1} and set(swdio[between]) == {1}, "the host did not hold SWDIO high"
    assert set(target_drives[between]) == {None}

    # The two transactions themselves, as with a prompt host.
    taken = [swdio[e - 1] for e in ups]
    assert target.requests == [byte, byte]
    assert taken[:8] == taken[13:21] == [1, 0, 0, 1, 0, 1, 0, 1]
    assert taken[9:12] == [0, 1, 0] and taken[22:25] == [1, 0, 0]
    assert taken[26:58] == [(data >> i) & 1 for i in range(32)] and taken[58] == 1
    assert target.written == [(data, True)]
    assert received == [SWD_WAIT << 5, SWD_OK << 5 | SWD_WAIT << 2]
    assert int(dut.tx_fifo.empty.value) == 1
    assert int(dut.rx_empty.value) == 1
    assert int(dut.halted.value) == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0b11


@cocotb.test()
async def restart_resets_the_core_and_keeps_the_fifos(dut):
    """top.restart is the core's reset without the FIFOs' reset: a program
    several words in, with a byte queued behind the one it took, goes back to
    pc 0 with its GPIO at reset levels, and the queued byte is still there.
    top.halted is the core's halted, read at the port: 1 with no program, 0
    while this one runs, 1 again when it runs off the end."""
    program = assemble("""
        SET 0, 0
        PULL
        NOP [31]
        NOP [31]
    """)
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert int(dut.halted.value) == 1  # no program

    # Two bytes queued with the core halted, then release it.
    for byte in (0x96, 0x53):
        await FallingEdge(dut.clk)
        dut.tx_data.value = byte
        dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)
    await ClockCycles(dut.clk, 6)  # SET, PULL, into the first NOP's delay
    await ReadOnly()
    assert int(dut.halted.value) == 0
    assert int(dut.core_i.pc.value) == 2
    assert (int(dut.gpio_out.value) & 1) == 0  # the SET landed
    assert int(dut.tx_fifo.count.value) == 1  # PULL took 0x96, 0x53 waits

    # One-clock restart pulse.
    await FallingEdge(dut.clk)
    dut.restart.value = 1
    await FallingEdge(dut.clk)
    dut.restart.value = 0
    await ReadOnly()
    assert int(dut.core_i.pc.value) == 0
    assert int(dut.core_i.delay_counter.value) == 0
    assert int(dut.gpio_out.value) == 0b1111  # reset levels
    assert int(dut.tx_fifo.count.value) == 1  # the FIFO did not reset
    assert int(dut.tx_fifo.head_data.value) == 0x53

    # The program runs again and takes the second byte.
    await ClockCycles(dut.clk, 3)
    await ReadOnly()
    assert int(dut.tx_fifo.count.value) == 0
    assert int(dut.core_i.shift_reg.value) == 0x53
    await ClockCycles(dut.clk, 70)
    await ReadOnly()
    assert int(dut.halted.value) == 1  # ran off the end


@cocotb.test()
async def restart_on_the_clock_a_pull_or_push_issues_keeps_the_fifos(dut):
    """A restart pulse on the very clock a PULL issues: the core resets and
    the TX FIFO must not pop, or the byte would vanish into a shift register
    the reset then clears. Same for a PUSH: a stale in_shift_reg must not
    land in the RX FIFO. A restart leaves both FIFOs untouched, whatever the
    core was about to do."""
    program = assemble("""
        NOP [1]
        PULL
        PUSH
    """)
    dut.imem_word.value = 0
    drive_host(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    await FallingEdge(dut.clk)
    dut.tx_data.value = 0x96
    dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)

    async def restart_when(en):
        """Wait for the core to be about to act on a FIFO, then pulse restart
        across that same edge."""
        for _ in range(20):
            await RisingEdge(dut.clk)
            await ReadOnly()
            if int(en.value) == 1:
                break
        else:
            raise AssertionError("the instruction never issued")
        await FallingEdge(dut.clk)
        assert int(en.value) == 1  # still up: the edge has not happened yet
        dut.restart.value = 1
        await FallingEdge(dut.clk)
        dut.restart.value = 0
        await ReadOnly()

    await restart_when(dut.pull_en)  # the PULL's edge
    assert int(dut.core_i.pc.value) == 0
    assert int(dut.tx_fifo.count.value) == 1, "the restart popped the byte"
    assert int(dut.tx_fifo.head_data.value) == 0x96
    assert int(dut.core_i.shift_reg.value) == 0

    await restart_when(dut.push_en)  # runs again: NOP, PULL takes the byte, then the PUSH's edge
    assert int(dut.core_i.pc.value) == 0
    assert int(dut.tx_fifo.count.value) == 0
    assert int(dut.rx_fifo.count.value) == 0, "the restart pushed a byte"
