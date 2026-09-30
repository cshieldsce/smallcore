"""cocotb test for rtl/ram.v: a write lands on the rising edge, a read follows
raddr with no clock at all. No reset and no check of unwritten words, the RAM
has neither by design. Run through test_ram.py."""

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from tb import start_clock


async def write(dut, addr, data):
    """we high across one rising edge, dropped on the falling edge after."""
    await FallingEdge(dut.clk)
    dut.we.value = 1
    dut.waddr.value = addr
    dut.wdata.value = data
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.we.value = 0


async def read(dut, addr):
    """rdata 1 ns after raddr moves, well short of the next rising edge: the
    read has no clock to wait for."""
    dut.raddr.value = addr
    await Timer(1, "ns")
    return int(dut.rdata.value)


@cocotb.test()
async def writes_on_the_edge_reads_without_one(dut):
    """0790 to address 0, 0780 to address 1, then raddr 0 -> 1 -> 0 between
    rising edges, rdata following each move at once."""
    dut.we.value = 0
    dut.waddr.value = 0
    dut.wdata.value = 0
    dut.raddr.value = 0
    start_clock(dut)

    await write(dut, 0, 0x0790)
    assert await read(dut, 0) == 0x0790

    await write(dut, 1, 0x0780)
    edges = 0

    async def count_edges():
        nonlocal edges
        while True:
            await RisingEdge(dut.clk)
            edges += 1

    counter = cocotb.start_soon(count_edges())
    assert await read(dut, 1) == 0x0780
    assert await read(dut, 0) == 0x0790
    counter.cancel()
    assert edges == 0, "the reads crossed a rising edge"
