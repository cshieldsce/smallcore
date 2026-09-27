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

from cpu import assemble, load_program  # sim/cpu.py
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
