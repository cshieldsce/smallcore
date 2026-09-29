"""cocotb tests for rtl/host.v alone: the program load path. CONTROL 0x20
enters load mode, TX_DATA bytes pair up low then high into prog_wdata, and
prog_we fires once per pair at prog_addr, which then steps. No RAM yet: the
bench watches the write port the RAM will hear. Run through test_host.py."""

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

from tb import reset, start_clock

TX_DATA, RX_DATA, STATUS, CONTROL = 0, 1, 2, 3  # addr
RUN_RAM, LOAD = 0x10, 0x20  # CONTROL commands


async def host_write(dut, addr, data, hold=4, gap=3):
    """One write at the bus minimums, moving on falling edges like
    smallcore_tb's."""
    await FallingEdge(dut.clk)
    dut.addr.value = addr
    dut.wdata.value = data
    dut.we.value = 1
    for _ in range(hold):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.we.value = 0
    for _ in range(gap):
        await RisingEdge(dut.clk)


class ProgWrites:
    """Every clock prog_we is high, as (prog_addr, prog_wdata). prog_we is
    combinational on registered state and the held pins, so the falling edge
    sees the values the rising edge after it will act on."""

    def __init__(self, dut):
        self.dut = dut
        self.log = []
        cocotb.start_soon(self._watch())

    async def _watch(self):
        while True:
            await FallingEdge(self.dut.clk)
            if int(self.dut.prog_we.value):
                self.log.append((int(self.dut.prog_addr.value), int(self.dut.prog_wdata.value)))


async def begin(dut):
    """Idle bus, clock, reset, then the 3 idle clocks owed before the first
    strobe."""
    dut.wdata.value = 0
    dut.addr.value = 0
    dut.we.value = 0
    dut.re.value = 0
    dut.tx_full.value = 0
    dut.rx_empty.value = 1
    dut.halted.value = 1
    dut.rx_data.value = 0
    start_clock(dut)
    await reset(dut)
    await ClockCycles(dut.clk, 3)
    return ProgWrites(dut)


def state(dut):
    return {
        "load_mode": int(dut.load_mode.value),
        "ram_select": int(dut.ram_select.value),
        "prog_addr": int(dut.prog_addr.value),
        "prog_words": int(dut.prog_words.value),
    }


@cocotb.test()
async def load_two_words_then_run_ram(dut):
    """reset, CONTROL 20, bytes 90 07 80 07, CONTROL 10: two words land at
    addresses 0 and 1, each only on its high byte, and running RAM keeps the
    count."""
    writes = await begin(dut)
    assert state(dut) == {"load_mode": 0, "ram_select": 0, "prog_addr": 0, "prog_words": 0}

    await host_write(dut, CONTROL, LOAD)
    assert state(dut) == {"load_mode": 1, "ram_select": 1, "prog_addr": 0, "prog_words": 0}

    await host_write(dut, TX_DATA, 0x90)
    assert writes.log == [], "the low byte alone must not write"
    assert state(dut)["prog_words"] == 0

    await host_write(dut, TX_DATA, 0x07)
    assert writes.log == [(0, 0x0790)]
    assert state(dut)["prog_addr"] == 1
    assert state(dut)["prog_words"] == 1

    await host_write(dut, TX_DATA, 0x80)
    assert writes.log == [(0, 0x0790)]
    await host_write(dut, TX_DATA, 0x07)
    assert writes.log == [(0, 0x0790), (1, 0x0780)]
    assert state(dut)["prog_words"] == 2

    await host_write(dut, CONTROL, RUN_RAM)
    assert state(dut) == {"load_mode": 0, "ram_select": 1, "prog_addr": 2, "prog_words": 2}
    assert len(writes.log) == 2
