"""cocotb tests for fpga/pynq_z2/smallcore_axi.v: the Zynq's ARM as SmallCore's
host. The bench is an AXI4-Lite master and the pads; every test body is
plain blocking code on fpga/pynq_z2/smallcore.py's SmallCore, the driver the
board runs, whose register reads and writes the bench turns into AXI
transactions (cocotb's bridge and resume). What passes here is what
`smallcore load`, `smallcore tx 96` and `smallcore rx` do on the board.
Run through test_pynq_axi.py."""

import sys
from pathlib import Path

import cocotb
from cocotb._bridge import bridge, resume
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from cpu import load_program  # model/cpu.py
from smallcore_tb import CS, MISO, MOSI, SCLK, Mode0Slave, bits_msb
from tb import Pads
from top_tb import I2cSlave, od_line

ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = ROOT / "programs"
sys.path.insert(0, str(ROOT / "fpga" / "pynq_z2"))
import smallcore as driver  # noqa: E402  fpga/pynq_z2/smallcore.py

SDA, SCL = 0, 1
TIMEOUT = 120.0  # seconds of wall clock a driver wait may take: the simulator is the slow part


class AxiMaster:
    """A minimal AXI4-Lite master on smallcore_axi's s_axi port: one
    transaction at a time, inputs driven on the falling edge, ready and
    valid read in ReadOnly after it, the handshake on the next rising edge."""

    def __init__(self, dut):
        self.dut = dut
        self.clk = dut.aclk
        for name in ("awvalid", "wvalid", "arvalid", "awaddr", "araddr", "wdata", "awprot", "arprot"):
            getattr(dut, f"s_axi_{name}").value = 0
        dut.s_axi_wstrb.value = 0xF
        dut.s_axi_bready.value = 1
        dut.s_axi_rready.value = 1

    async def _handshake(self, ready):
        while True:
            await ReadOnly()
            done = int(ready.value)
            await RisingEdge(self.clk)
            if done:
                return
            await FallingEdge(self.clk)

    async def _response(self, valid):
        """From a falling edge: wait for `valid` (ready is tied high), return
        in ReadOnly on the falling edge it shows, the handshake still to come."""
        while True:
            await ReadOnly()
            if int(valid.value):
                return
            await RisingEdge(self.clk)
            await FallingEdge(self.clk)

    async def write(self, offset, value):
        d = self.dut
        await FallingEdge(self.clk)
        d.s_axi_awaddr.value = offset
        d.s_axi_wdata.value = value
        d.s_axi_awvalid.value = 1
        d.s_axi_wvalid.value = 1
        await self._handshake(d.s_axi_awready)
        await FallingEdge(self.clk)
        d.s_axi_awvalid.value = 0
        d.s_axi_wvalid.value = 0
        await self._response(d.s_axi_bvalid)
        await RisingEdge(self.clk)

    async def read(self, offset):
        d = self.dut
        await FallingEdge(self.clk)
        d.s_axi_araddr.value = offset
        d.s_axi_arvalid.value = 1
        await self._handshake(d.s_axi_arready)
        await FallingEdge(self.clk)
        d.s_axi_arvalid.value = 0
        await self._response(d.s_axi_rvalid)
        value = int(d.s_axi_rdata.value)
        await RisingEdge(self.clk)
        return value


class Regs:
    """The driver's register port, blocking, on the bench's AXI master."""

    def __init__(self, axi):
        self.read = resume(axi.read)
        self.write = resume(axi.write)


async def begin(dut, wires=()):
    """Clock, AXI reset, the pads. Returns the driver and the pads."""
    Clock(dut.aclk, 10, unit="ns").start()  # FCLK_CLK0, 100 MHz
    axi = AxiMaster(dut)
    pads = Pads(dut, wires, clk=dut.aclk)
    dut.aresetn.value = 0
    await ClockCycles(dut.aclk, 10)
    await FallingEdge(dut.aclk)
    dut.aresetn.value = 1
    return driver.SmallCore(Regs(axi), timeout=TIMEOUT), pads


async def on(sc, body):
    """Run the blocking test body with the driver."""
    return await bridge(body)(sc)


class StrobeLog:
    """The host bus as smallcore sees it, one sample per core clock edge:
    (reset, we, re, addr, wdata)."""

    def __init__(self, dut):
        self.dut = dut
        self.samples = []
        cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await RisingEdge(d.core_clk)
            self.samples.append((int(d.core_reset.value), int(d.host_we.value), int(d.host_re.value),
                                 int(d.host_addr.value), int(d.host_wdata.value)))

    def strobes(self):
        """[(first sample, samples high, samples low before it, (addr, wdata) through the high)]."""
        out, low, start = [], 0, None
        for i, (reset, we, re, addr, wdata) in enumerate(self.samples):
            high = we or re
            if reset:
                low = 0
                continue
            if high and start is None:
                start, before, held = i, low, {(addr, wdata)}
            elif high:
                held.add((addr, wdata))
            elif start is not None:
                out.append((start, i - start, before, held))
                start, low = None, 1
            else:
                low += 1
        return out


@cocotb.test()
async def bridge_id_reset_and_a_fresh_chip(dut):
    """ID says the bridge is there, CLKDIV comes up at 4, and the chip behind
    it reads as a fresh one: halted, RX empty, slot 0."""
    sc, _ = await begin(dut)

    def body(sc):
        sc.check()
        assert sc.clkdiv == 4
        sc.reset()
        assert sc.status() == driver.Status(halted=True, tx_full=False, rx_empty=True)
        assert sc.control() == 0
        assert sc.pads().gpio_out == 0b1111, "every pad high out of reset"
        sc.clkdiv = 0
        assert sc.clkdiv == 1, "0 reads back as 1"

    await on(sc, body)


@cocotb.test()
async def strobes_keep_the_host_timing_at_every_clkdiv(dut):
    """Whatever CLKDIV says, each CMD is one strobe at least 4 core clocks
    high and 3 low, the first 3 after reset, addr and wdata steady through
    it, and exactly one transaction: 5 bytes queued fill the 4-deep FIFO
    and drop the fifth, as host.v says, not two or none of them."""
    sc, _ = await begin(dut)
    log = StrobeLog(dut)

    def body(sc):
        for div in (1, 3, 7):
            sc.clkdiv = div
            sc.reset()
            for b in range(5):
                sc.strobe_write(driver.TX_DATA, 0x10 + b)
            assert sc.status().tx_full
            sc.select(0)
        sc.control()  # a PEEK waits for the last strobe to finish

    await on(sc, body)
    strobes = log.strobes()
    assert len(strobes) == 3 * 6
    for start, high, low, held in strobes:
        assert high >= 4, f"strobe at core clock {start} high {high}"
        assert low >= 3, f"strobe at core clock {start} after {low} low"
        assert len(held) == 1, f"strobe at core clock {start}: addr/wdata moved {held}"
    fifo = dut.smallcore_i.top_i.tx_fifo
    assert int(fifo.count.value) == 4


@cocotb.test()
async def rom_spi_loopback_through_the_driver(dut):
    """The button smoke test from Linux: slot 8 from the ROM, 0x96 out and back
    through the PMOD jumper from pin 1 to pin 4, at CLKDIV 1, 4 and 13."""
    sc, _ = await begin(dut, wires=[(MOSI, MISO)])

    def body(sc):
        results = []
        for div in (1, 4, 13):
            sc.clkdiv = div
            sc.reset()
            sc.select(8)
            assert sc.status() == driver.Status(halted=False, tx_full=False, rx_empty=True), "stalled on PULL"
            sc.write(0x96)
            sc.wait_halted()
            results.append(sc.read())
            assert sc.status().rx_empty
        return results

    assert await on(sc, body) == [0x96, 0x96, 0x96]


@cocotb.test()
async def ram_spi_duplex_with_a_slave(dut):
    """spi_duplex_msb.asm uploaded to the RAM and run from it: the program
    comes from the ARM, not the ROM. A mode 0 slave on the pads sends 0x53
    and receives 0x96, MSB first; CS frames it; the host reads 0x53."""
    sc, pads = await begin(dut)
    slave = Mode0Slave(bits_msb(0x53))
    pads.attach(MISO, slave)

    def body(sc):
        sc.reset()
        words = sc.load(PROGRAMS / "spi" / "spi_duplex_msb.asm")
        assert sc.control() == driver.LOAD_RAM
        assert sc.status().halted
        sc.run()
        assert sc.control() == driver.RUN_RAM
        sc.write(0x96)
        sc.wait_halted()
        return words, sc.read()

    words, got = await on(sc, body)
    assert words == load_program(PROGRAMS / "spi" / "spi_duplex_msb.asm")
    ram = dut.smallcore_i.ram_i.mem
    assert [int(ram[i].value) for i in range(len(words))] == words
    assert got == 0x53
    assert slave.mosi == bits_msb(0x96)
    assert (int(dut.gpio_out.value) >> CS) & 1 and not (int(dut.gpio_out.value) >> SCLK) & 1


def i2c_bus(pads, slave):
    """SDA and SCL on pads 0 and 1: open-drain lines with pull-ups and the
    slave on the far end, resolved every aclk as top_tb.py's i2c_bus does."""
    scl_low = [None]

    def sda(out, oe):
        s = od_line(out, oe, SDA, slave.sda_low)
        c = od_line(out, oe, SCL, slave.scl_low)
        level, scl_low[0] = (0 if slave.sda_low else None), (0 if slave.scl_low else None)
        slave.update(s, c)
        return level

    pads.attach(SDA, sda)
    pads.attach(SCL, lambda out, oe: scl_low[0])


@cocotb.test()
async def ram_i2c_write_addr_data_acked(dut):
    """i2c_write_addr_data.asm from the RAM with a slave at 0x50 that ACKs:
    one START, 0xA0, 0x3C, one STOP, and two ACKs (0) back to the ARM."""
    sc, pads = await begin(dut)
    slave = I2cSlave()
    i2c_bus(pads, slave)

    def body(sc):
        sc.reset()
        sc.load(PROGRAMS / "i2c" / "i2c_write_addr_data.asm")
        sc.run()
        sc.write(0xA0)
        sc.write(0x3C)
        sc.wait_halted()
        return [sc.read(), sc.read()], sc.status()

    acks, status = await on(sc, body)
    assert slave.events == ["START", 0xA0, 0x3C, "STOP"]
    assert acks == [0, 0]
    assert status.rx_empty


@cocotb.test()
async def ram_i2c_with_nothing_on_the_bus_nacks(dut):
    """The board with only the PMOD pull-ups: nobody ACKs the address, the
    program STOPs, the ARM reads 1 and the data byte is still queued."""
    sc, _ = await begin(dut)  # released pads read 1: the pull-ups

    def body(sc):
        sc.reset()
        sc.load(PROGRAMS / "i2c" / "i2c_write_addr_data.asm")
        sc.run()
        sc.write(0xA0)
        sc.write(0x3C)
        sc.wait_halted()
        return sc.read(), sc.status()

    nack, status = await on(sc, body)
    assert nack == 1
    assert status.rx_empty and status.halted
    assert int(dut.smallcore_i.top_i.tx_fifo.count.value) == 1
    assert int(dut.gpio_oe.value) & 0b11 == 0, "both lines let go"


@cocotb.test()
async def ram_led_byte_puts_the_nibble_on_the_pads(dut):
    """led_byte.asm from the RAM: each byte written from Linux lands on the
    four pads, the PYNQ-Z2's LD0..LD3, as its low nibble, read back through
    PADS the way `smallcore pads` does."""
    sc, _ = await begin(dut)

    def body(sc):
        sc.reset()
        sc.load(PROGRAMS / "led" / "led_byte.asm")
        sc.run()
        seen = []
        for byte in (0x05, 0x0A, 0xF3, 0x0F, 0x00, 0x69):
            sc.write(byte)
            sc._until(lambda: sc.status().tx_full is False and sc.pads().gpio_out == byte & 0xF, "LEDs")
            seen.append(sc.pads())
        return seen

    for pads, byte in zip(await on(sc, body), (0x05, 0x0A, 0xF3, 0x0F, 0x00, 0x69)):
        assert pads.gpio_out == byte & 0xF
        assert pads.gpio_in == byte & 0xF, "the pads read back what they drive"
        assert pads.gpio_oe == 0xF


@cocotb.test()
async def ram_led_blink_chases_at_the_core_clock(dut):
    """led_blink.asm from the RAM at CLKDIV 2: LD0, LD1, LD2, LD3, LD0 in turn,
    each 1057 core clocks, 2114 aclk cycles: CLKDIV sets the pace."""
    sc, _ = await begin(dut)

    def body(sc):
        sc.reset()
        sc.clkdiv = 2
        sc.load(PROGRAMS / "led" / "led_blink.asm")
        sc.run()

    await on(sc, body)
    runs = []
    while len(runs) < 14:
        await RisingEdge(dut.aclk)
        await ReadOnly()
        p = int(dut.gpio_out.value)
        if runs and runs[-1][0] == p:
            runs[-1][1] += 1
        else:
            runs.append([p, 1])
    lit = [(p, n) for p, n in runs if p and not p & (p - 1)][1:5]  # one LED on; the first seen may be partial
    first = lit[0][0]
    assert [p for p, _ in lit] == [(first << i | first >> (4 - i)) & 0xF for i in range(4)], lit
    assert all(n in (2 * 1057, 2 * 1058) for _, n in lit), lit
