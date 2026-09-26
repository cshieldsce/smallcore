"""cocotb tests for rtl/core.v. Run through test_core.py, not directly: each
@cocotb.test() runs inside the Verilator simulation, `dut` is the top-level
module, and `await` hands control back to the simulator until the trigger
(a clock edge, a time step) happens.

The core runs NOP and its delay counter, so the tests check reset and then
step the RTL and the model together, one cycle at a time, comparing state.
"""

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

from cpu import CPU, assemble, load_program  # sim/cpu.py, the golden model
from tb import Imem, drive_inputs, model_state, reset, rtl_state, start_clock

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"


@cocotb.test()
async def reset_state(dut):
    """Hold reset over a few edges: pc and the counter clear, every pin high."""
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=0)
    start_clock(dut)
    dut.reset.value = 1
    await ClockCycles(dut.clk, 2)
    await ReadOnly()  # let this edge's nonblocking assignments settle before reading

    assert int(dut.imem_addr.value) == 0
    assert dut.gpio_out.value == 0b1111
    assert int(dut.pc.value) == 0  # internal, read through VPI
    assert int(dut.delay_counter.value) == 0


@cocotb.test()
async def reset_matches_model(dut):
    """The same program into both: after reset the RTL's state is the model's
    starting state, and imem_word is the first word of the program."""
    program = load_program(PROGRAMS / "uart_tx_0x55.asm")
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program))
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)  # after reset: imem_addr is a known 0, not X, when Imem first reads it
    await ReadOnly()

    assert rtl_state(dut) == model_state(cpu)
    assert int(dut.imem_word.value) == program[0]


@cocotb.test()
async def nop_timing_matches_model(dut):
    """Step the RTL and the model one cycle at a time until the model halts;
    the architectural state must match after every edge. NOP [3] exercises
    the delay counter, and running off the end exercises halted."""
    program = assemble("""
        NOP
        NOP [3]
        NOP
    """)
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program))
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    while not cpu.halted:
        cpu.step()  # model: one architectural cycle
        await RisingEdge(dut.clk)  # RTL: one hardware cycle
        await ReadOnly()  # let the nonblocking assignments settle
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"
