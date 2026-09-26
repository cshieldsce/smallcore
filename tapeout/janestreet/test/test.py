# Smoke test of the provisional wrapper: reset values, then NOP words advance imem_addr once per cycle.
# The cycle-accurate checks live in rtl_tests/ against sim/cpu.py; this only proves the wrapper wiring.
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


@cocotb.test()
async def test_wrapper(dut):
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)

    # provisional mapping: imem_word = {uio_in, ui_in} = NOP [0], program_words = {ui_in[1], uio_in} = 0
    assert dut.uio_oe.value == 0x0F
    assert dut.uio_out.value == 0x0F  # gpio_out resets to 1111
    assert dut.uo_out.value == 0      # pc = 0

    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 3)
    assert dut.uo_out.value == 0      # program_words = 0: halted, pc holds

    # ui_in[1] = 1 makes program_words = 0x100 and imem_word = NOP with operand bit 1 set, still a NOP [0]
    dut.ui_in.value = 0x02
    await ClockCycles(dut.clk, 1)
    for expected in range(1, 5):
        await ClockCycles(dut.clk, 1)
        assert int(dut.uo_out.value) == expected, f"pc {int(dut.uo_out.value)} != {expected}"
