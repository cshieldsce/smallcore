"""cocotb tests for rtl/smallcore.v: the chip. host.v turns the host's
strobes into FIFO pushes and pops and a program select, rom.v feeds the core
from programs/manifest.txt, top.v is the core with its FIFOs. The bench is the
host and the far end of the wire: it drives only smallcore's ports, the host
bus on one side and the four pads through tb.Pads on the other. Internals are
read only to confirm what the ports already showed. Run through
test_smallcore.py."""

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from cpu import load_program  # model/cpu.py
from tb import Pads, drive_smallcore, reset, start_clock

PROGRAMS = Path(__file__).resolve().parent.parent.parent / "programs"

TX_DATA, RX_DATA, STATUS, CONTROL = 0, 1, 2, 3  # host_addr
HALTED, TX_FULL, RX_EMPTY = 0b100, 0b010, 0b001  # STATUS bits
NONE, UART_TX_PULL, SPI_TX_MSB, SPI_DUPLEX_LSB, SPI_DUPLEX_MSB = 0, 2, 6, 7, 8  # manifest slots
MOSI, SCLK, CS, MISO = 0, 1, 2, 3  # pads the SPI programs use


async def host_write(dut, addr, data, hold=4, gap=3):
    """One write: addr and data set, we high for `hold` rising edges, low for
    `gap` more, the bus rules' minimums. Everything moves on falling edges,
    the read-only phase forbids writes. Leaves addr on the register written."""
    await FallingEdge(dut.clk)
    dut.host_addr.value = addr
    dut.host_wdata.value = data
    dut.host_we.value = 1
    for _ in range(hold):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.host_we.value = 0
    for _ in range(gap):
        await RisingEdge(dut.clk)


async def host_pop(dut, hold=4, gap=3):
    """One pop: re high for `hold` rising edges with addr on RX_DATA."""
    await FallingEdge(dut.clk)
    dut.host_addr.value = RX_DATA
    dut.host_re.value = 1
    for _ in range(hold):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.host_re.value = 0
    for _ in range(gap):
        await RisingEdge(dut.clk)


async def host_read(dut, addr):
    """host_rdata for addr, combinational: set on a falling edge, read once
    the time step has settled."""
    await FallingEdge(dut.clk)
    dut.host_addr.value = addr
    await ReadOnly()
    return int(dut.host_rdata.value)


async def begin(dut, wires=()):
    """Clock, idle host, pads, reset, then the 3 idle clocks the host owes
    after reset before its first strobe: the strobe synchronizers come out
    of reset as if the lines had been high, so they need to see them low
    before a rise counts. Returns the Pads."""
    drive_smallcore(dut)
    start_clock(dut)
    pads = Pads(dut, wires)
    await reset(dut)
    await ClockCycles(dut.clk, 3)
    return pads


def tx_count(dut):
    return int(dut.top_i.tx_fifo.count.value)


def rx_count(dut):
    return int(dut.top_i.rx_fifo.count.value)


@cocotb.test()
async def hard_reset_halts_with_no_program(dut):
    """Out of reset the chip does nothing: slot 0, no program, the core halted,
    both FIFOs empty, every pad driven high. STATUS says so at the port."""
    await begin(dut)
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY
    assert await host_read(dut, CONTROL) == NONE
    assert await host_read(dut, TX_DATA) == 0
    assert await host_read(dut, RX_DATA) == 0
    assert int(dut.top_i.core_i.pc.value) == 0
    assert int(dut.top_i.program_words.value) == 0
    assert int(dut.gpio_out.value) == 0b1111
    assert int(dut.gpio_oe.value) == 0b1111


@cocotb.test()
async def we_is_an_edge_not_a_level(dut):
    """One push per rising edge of we, however long it stays high, and two
    strobes with the minimum gap are two transactions. The last write is to
    CONTROL, so a decode that ignored addr would push a fourth byte."""
    await begin(dut)
    await host_write(dut, TX_DATA, 0x96, hold=4)
    await ReadOnly()
    assert tx_count(dut) == 1
    assert int(dut.top_i.tx_fifo.head_data.value) == 0x96
    await host_write(dut, TX_DATA, 0x53, hold=20)
    await ReadOnly()
    assert tx_count(dut) == 2
    await host_write(dut, TX_DATA, 0x3C, hold=4, gap=3)
    await host_write(dut, CONTROL, NONE, hold=4, gap=3)
    await ReadOnly()
    assert tx_count(dut) == 3
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY


@cocotb.test()
async def strobe_high_through_reset_does_nothing(dut):
    """A host holding we or re high while the chip resets has not made a
    rising edge: nothing is pushed, popped or selected until the strobe drops
    and rises again."""
    drive_smallcore(dut)
    dut.host_addr.value = TX_DATA
    dut.host_wdata.value = 0x96
    dut.host_we.value = 1
    dut.host_re.value = 1
    start_clock(dut)
    Pads(dut)
    await reset(dut)
    await ClockCycles(dut.clk, 6)
    await ReadOnly()
    assert tx_count(dut) == 0
    await FallingEdge(dut.clk)
    dut.host_we.value = 0
    dut.host_re.value = 0
    await ClockCycles(dut.clk, 3)
    await host_write(dut, TX_DATA, 0x96)
    await ReadOnly()
    assert tx_count(dut) == 1


@cocotb.test()
async def strobes_on_other_addresses_do_nothing(dut):
    """we on RX_DATA or STATUS and re on TX_DATA, STATUS or CONTROL are not
    transactions. A byte queued before stays, sel stays."""
    await begin(dut)
    await host_write(dut, TX_DATA, 0x96)
    for addr in (RX_DATA, STATUS):
        await host_write(dut, addr, 0x53)
    for addr in (TX_DATA, STATUS, CONTROL):
        await FallingEdge(dut.clk)
        dut.host_addr.value = addr
        dut.host_re.value = 1
        await ClockCycles(dut.clk, 4)
        await FallingEdge(dut.clk)
        dut.host_re.value = 0
        await ClockCycles(dut.clk, 3)
    await ReadOnly()
    assert tx_count(dut) == 1
    assert int(dut.top_i.tx_fifo.head_data.value) == 0x96
    assert await host_read(dut, CONTROL) == NONE
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY


@cocotb.test()
async def tx_fifo_full_drops_the_fifth_write(dut):
    """Four bytes fill the TX FIFO and STATUS says tx_full; a fifth write is
    dropped, the host's fault for not reading STATUS. The head is still the
    first byte."""
    await begin(dut)
    for byte in (0x96, 0x53, 0x3C, 0xC3):
        await host_write(dut, TX_DATA, byte)
    assert await host_read(dut, STATUS) == HALTED | TX_FULL | RX_EMPTY
    await host_write(dut, TX_DATA, 0x69)
    await ReadOnly()
    assert tx_count(dut) == 4
    assert int(dut.top_i.tx_fifo.head_data.value) == 0x96
    assert await host_read(dut, STATUS) == HALTED | TX_FULL | RX_EMPTY


@cocotb.test()
async def a_strobe_in_the_worst_phase_still_acts_once(dut):
    """The bus rule's reason. A strobe raised just after a rising edge is
    captured almost a full clock later, and the transaction decodes addr and
    wdata from the pins two clocks after that capture. Held 4 clocks, with
    addr and wdata changing the moment it drops, it still pushes the right
    byte exactly once; 3 would drop on the decoding clock."""
    await begin(dut)
    await RisingEdge(dut.clk)  # just after an edge: the worst phase
    dut.host_addr.value = TX_DATA
    dut.host_wdata.value = 0x96
    dut.host_we.value = 1
    await ClockCycles(dut.clk, 4)  # captured on the first, decoded on the third, still high on the fourth
    dut.host_we.value = 0  # drops just after the fourth edge, and the pins move with it
    dut.host_addr.value = CONTROL
    dut.host_wdata.value = 13
    await ClockCycles(dut.clk, 4)
    await ReadOnly()
    assert tx_count(dut) == 1
    assert int(dut.top_i.tx_fifo.head_data.value) == 0x96
    assert await host_read(dut, CONTROL) == NONE  # nothing decoded after the drop


async def until_cs(dut, level, limit=200):
    """Rising edges of clk until pad CS holds `level`."""
    for _ in range(limit):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if (int(dut.gpio_out.value) >> CS) & 1 == level:
            return
    raise AssertionError(f"CS never went to {level} in {limit} clocks")


@cocotb.test()
async def control_restarts_the_core_and_keeps_the_fifos(dut):
    """CONTROL mid-frame is an abort and restart: the core goes to pc 0 with
    its pads at reset levels, the TX FIFO keeps the byte queued behind the one
    the frame took, and the program runs again from the top on that byte.
    CONTROL while stalled on PULL restarts just the same. Slot 0 halts the
    core, as an unused slot did while there were any: 12..15 were taken
    2026-09-28."""
    await begin(dut)
    await host_write(dut, TX_DATA, 0x96)
    await host_write(dut, TX_DATA, 0x53)
    await host_write(dut, CONTROL, SPI_TX_MSB)
    assert await host_read(dut, CONTROL) == SPI_TX_MSB
    await until_cs(dut, 0)  # the PULL took 0x96 and dropped CS
    await ClockCycles(dut.clk, 20)  # into the frame
    await ReadOnly()
    assert (int(dut.gpio_out.value) >> CS) & 1 == 0
    assert tx_count(dut) == 1
    assert (await host_read(dut, STATUS)) & HALTED == 0

    await host_write(dut, CONTROL, SPI_TX_MSB, hold=3, gap=0)  # 3 high, raised on a falling edge: the restart is the third edge
    await ReadOnly()  # the clock after the restart pulse
    assert int(dut.top_i.core_i.pc.value) <= 1  # back at the top
    assert int(dut.gpio_out.value) == 0b1111  # reset levels: CS high, SCLK high
    assert tx_count(dut) == 1
    assert int(dut.top_i.tx_fifo.head_data.value) == 0x53
    await until_cs(dut, 0)  # a second frame, on 0x53
    assert tx_count(dut) == 0
    await until_cs(dut, 1)
    await ClockCycles(dut.clk, 4)
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY

    await host_write(dut, CONTROL, SPI_TX_MSB)  # stalls on PULL: FIFO empty
    await ClockCycles(dut.clk, 10)
    assert (await host_read(dut, STATUS)) & HALTED == 0
    await host_write(dut, CONTROL, SPI_TX_MSB)  # restart while stalled
    await ClockCycles(dut.clk, 10)
    assert (await host_read(dut, STATUS)) & HALTED == 0
    assert int(dut.top_i.core_i.pc.value) == 2  # config, clock low, stalled on the PULL

    await host_write(dut, CONTROL, NONE)
    assert await host_read(dut, CONTROL) == NONE
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY
    assert int(dut.top_i.program_words.value) == 0


# SPI over the bus: the bench is the host on one side and a mode 0 slave on
# the pads on the other, the far end of the wire.


def bits_msb(byte):
    """The bits of `byte`, bit 7 first: the wire order of an MSB-first transfer."""
    return [(byte >> bit) & 1 for bit in range(7, -1, -1)]


class Mode0Slave:
    """A mode 0 slave on the MISO pad sending `bits` in wire order. Nobody
    drives MISO while CS is high. Once CS is low the first bit is on the pad,
    and the next goes on at every falling edge of SCLK, so each is stable
    across the rising edge the master samples on. Called by Pads every falling
    edge of clk with gpio_out and gpio_oe; remembers what it saw of MOSI on
    each rising edge of SCLK, the byte it shifted in."""

    def __init__(self, bits):
        self.bits = bits
        self.i = 0
        self.sclk = 1
        self.mosi = []

    def __call__(self, out, oe):
        cs, sclk, mosi = (out >> CS) & 1, (out >> SCLK) & 1, (out >> MOSI) & 1
        if cs:
            self.i = 0
        else:
            if self.sclk == 0 and sclk == 1:
                self.mosi.append(mosi)
            if self.sclk == 1 and sclk == 0:
                self.i += 1
        self.sclk = sclk
        if cs:
            return None
        return self.bits[min(self.i, len(self.bits) - 1)]


async def until_halted(dut, limit=300):
    """Rising edges of clk until STATUS at the port says halted, then a few more."""
    await FallingEdge(dut.clk)
    dut.host_addr.value = STATUS
    for _ in range(limit):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.host_rdata.value) & HALTED:
            await ClockCycles(dut.clk, 4)
            return
    raise AssertionError(f"not halted after {limit} clocks")


@cocotb.test()
async def spi_duplex_msb_over_the_host_bus(dut):
    """The milestone. A developer at the host bus selects spi_duplex_msb, sees
    it running, writes 0x96, and reads 0x53 back, with nothing outside the chip
    but a mode 0 slave on the pads. The program came from rom.v, the byte went
    through host.v into the real TX FIFO, out of MOSI in one 8-clock CS frame
    MSB first, and the slave's byte came back through MISO, the input shift
    register, PUSH, the real RX FIFO and host.v."""
    pads = await begin(dut)
    slave = Mode0Slave(bits_msb(0x53))
    pads.attach(MISO, slave)

    await host_write(dut, CONTROL, SPI_DUPLEX_MSB)
    await ClockCycles(dut.clk, 10)
    assert await host_read(dut, STATUS) == RX_EMPTY  # running, stalled on PULL, nothing yet
    assert int(dut.gpio_oe.value) & (1 << MISO) == 0  # the program let go of the MISO pad
    assert (int(dut.gpio_out.value) >> CS) & 1 == 1

    await host_write(dut, TX_DATA, 0x96)
    await until_halted(dut)
    assert slave.mosi == bits_msb(0x96), f"the slave saw {slave.mosi}"
    assert (int(dut.gpio_out.value) >> CS) & 1 == 1
    assert await host_read(dut, STATUS) == HALTED  # done, a byte waiting, room in TX
    assert await host_read(dut, RX_DATA) == 0x53
    assert rx_count(dut) == 1
    await host_pop(dut)
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY
    assert rx_count(dut) == 0
    await host_pop(dut)  # nothing to pop
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY
    assert rx_count(dut) == 0


@cocotb.test()
async def spi_loopback_returns_the_byte_written(dut):
    """The board test's RTL twin: pad 0 (MOSI) jumpered to pad 3 (MISO), both
    duplex slots, each one returns the byte the host wrote. Loopback cannot
    tell the bit orders apart, the slave test above does; this proves the
    wiring the FPGA will have. The second byte is written before the second
    select, so it is still queued after the restart."""
    await begin(dut, wires=[(MOSI, MISO)])
    for slot, byte in ((SPI_DUPLEX_MSB, 0x96), (SPI_DUPLEX_LSB, 0x3C)):
        await host_write(dut, TX_DATA, byte)
        await host_write(dut, CONTROL, slot)
        await until_halted(dut)
        assert await host_read(dut, STATUS) == HALTED
        assert await host_read(dut, RX_DATA) == byte, f"slot {slot}"
        await host_pop(dut)
        assert await host_read(dut, STATUS) == HALTED | RX_EMPTY


@cocotb.test()
async def rx_data_reads_zero_while_empty(dut):
    """RX_DATA is 0 whenever the RX FIFO is empty, not whatever its memory
    holds. Four loopback frames wrap the DEPTH 4 ring, so after the fourth
    pop the read pointer is back on the slot that held the first byte; a
    read that showed the memory would show 0x96. Silicon does not zero its
    memory, so the read is gated on empty, and the reset-state test's
    RX_DATA == 0 is true by design rather than by the simulator."""
    await begin(dut, wires=[(MOSI, MISO)])
    for byte in (0x96, 0x3C, 0x53, 0xC3):
        await host_write(dut, TX_DATA, byte)
        await host_write(dut, CONTROL, SPI_DUPLEX_MSB)
        await until_halted(dut)
        assert await host_read(dut, RX_DATA) == byte
        await host_pop(dut)
        assert await host_read(dut, STATUS) == HALTED | RX_EMPTY
        assert await host_read(dut, RX_DATA) == 0, f"empty after {byte:#04x}"
    assert int(dut.top_i.rx_fifo.rd_ptr.value) == 0, "the ring wrapped: the test hit the case"


@cocotb.test()
async def control_switches_slots_mid_frame_and_the_new_program_takes_the_queued_byte(dut):
    """Two bytes queued and uart_tx_pull selected: pad 0 is sending the
    first as a UART frame. Mid-frame the host writes CONTROL with
    spi_tx_msb. On the clock after the strobe is decoded the core is at the
    top of slot 6, reading its words, the pads are at reset levels, the
    frame is cut, and the second byte, still queued, leaves as one 8-clock
    MSB-first SPI frame the slave on the pads captures. CONTROL reads the
    new slot; STATUS then says halted with nothing left."""
    pads = await begin(dut)
    slave = Mode0Slave(bits_msb(0x00))
    pads.attach(MISO, lambda out, oe: (slave(out, oe), None)[1])  # a listener only: the TX program never lets go of MISO
    spi = load_program(PROGRAMS / "spi" / "spi_tx_msb.asm")
    await host_write(dut, TX_DATA, 0x96)
    await host_write(dut, TX_DATA, 0x53)
    await host_write(dut, CONTROL, UART_TX_PULL)
    for _ in range(40):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.gpio_out.value) & 1 == 0:
            break  # the start bit: the PULL took 0x96
    else:
        raise AssertionError("no start bit")
    await ClockCycles(dut.clk, 12)  # into the first data bit
    await ReadOnly()
    assert tx_count(dut) == 1 and int(dut.top_i.tx_fifo.head_data.value) == 0x53
    assert (await host_read(dut, STATUS)) & HALTED == 0

    await host_write(dut, CONTROL, SPI_TX_MSB, hold=3, gap=0)  # the restart is the third edge
    await ReadOnly()  # the clock after it
    pc = int(dut.top_i.core_i.pc.value)
    assert pc <= 1, pc
    assert int(dut.top_i.program_words.value) == len(spi)
    assert int(dut.top_i.imem_word.value) == spi[pc], "not reading slot 6's words"
    assert int(dut.gpio_out.value) == 0b1111  # the frame is cut, every pad at its reset level
    assert tx_count(dut) == 1 and int(dut.top_i.tx_fifo.head_data.value) == 0x53
    assert await host_read(dut, CONTROL) == SPI_TX_MSB

    await until_cs(dut, 0)
    assert tx_count(dut) == 0
    await until_cs(dut, 1)
    assert slave.mosi == bits_msb(0x53), f"the slave saw {slave.mosi}"
    await until_halted(dut)
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY
