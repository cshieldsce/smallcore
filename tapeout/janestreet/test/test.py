# Smoke test of the wrapper: pins reach smallcore. Reset, STATUS says halted;
# a CONTROL write held 4 clocks selects spi_duplex_msb and STATUS says running.
# The cycle-accurate tests live in rtl_tests/ against sim/cpu.py.
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

STATUS, CONTROL = 2, 3
HALTED, RX_EMPTY = 0b100, 0b001
SPI_DUPLEX_MSB = 8


def uio(addr, we=0, re=0, pads=0b1111):
    """uio_in: re on 7, we on 6, addr on 5:4, the four pads' levels on 3:0."""
    return (re << 7) | (we << 6) | (addr << 4) | pads


@cocotb.test()
async def test_wrapper(dut):
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = uio(STATUS)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 3)  # the host keeps its strobes low 3 clocks after reset

    assert int(dut.uio_oe.value) == 0x0F, "pads driven, host control pins inputs"
    assert int(dut.uio_out.value) & 0x0F == 0x0F, "gpio_out resets to 1111"
    assert int(dut.uo_out.value) == HALTED | RX_EMPTY, "no program selected"

    dut.ui_in.value = SPI_DUPLEX_MSB
    dut.uio_in.value = uio(CONTROL, we=1)
    await ClockCycles(dut.clk, 4)
    dut.uio_in.value = uio(STATUS)
    await ClockCycles(dut.clk, 6)
    assert int(dut.uo_out.value) == RX_EMPTY, "running, stalled on PULL"
    assert int(dut.uio_oe.value) & 0x08 == 0, "MISO pad released by the program"
