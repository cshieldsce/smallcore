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

from tb import Pads, drive_smallcore, reset, start_clock

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"

TX_DATA, RX_DATA, STATUS, CONTROL = 0, 1, 2, 3  # host_addr
HALTED, TX_FULL, RX_EMPTY = 0b100, 0b010, 0b001  # STATUS bits
NONE, SPI_TX_MSB, SPI_DUPLEX_LSB, SPI_DUPLEX_MSB = 0, 6, 7, 8  # manifest slots
MOSI, SCLK, CS, MISO = 0, 1, 2, 3  # pads the SPI programs use


async def host_write(dut, addr, data, hold=3, gap=3):
    """One write: addr and data set, we high for `hold` rising edges, low for
    `gap` more. Everything moves on falling edges, the read-only phase forbids
    writes. Leaves addr on the register written."""
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


async def host_pop(dut, hold=3, gap=3):
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
    await host_write(dut, TX_DATA, 0x96, hold=3)
    await ReadOnly()
    assert tx_count(dut) == 1
    assert int(dut.top_i.tx_fifo.head_data.value) == 0x96
    await host_write(dut, TX_DATA, 0x53, hold=20)
    await ReadOnly()
    assert tx_count(dut) == 2
    await host_write(dut, TX_DATA, 0x3C, hold=3, gap=3)
    await host_write(dut, CONTROL, NONE, hold=3, gap=3)
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
        await ClockCycles(dut.clk, 3)
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
    CONTROL while stalled on PULL restarts just the same. An unused slot halts
    the core like slot 0."""
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

    await host_write(dut, CONTROL, SPI_TX_MSB, hold=3, gap=0)
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

    await host_write(dut, CONTROL, 13)
    assert await host_read(dut, CONTROL) == 13
    assert await host_read(dut, STATUS) == HALTED | RX_EMPTY
    assert int(dut.top_i.program_words.value) == 0
