"""cocotb tests for rtl/top.v: the core reading its TX FIFO. Run through
test_top.py, not directly.

The bench drives only top's host ports (tx_data, tx_push, ...). core.tx_data
and core.tx_empty are wires inside top now, fed by the FIFO, so the path under
test is host -> fifo.v -> core.v. Internals are read hierarchically through
VPI: dut.core_i.shift_reg, dut.tx_fifo.count.
"""

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from cpu import assemble  # sim/cpu.py
from tb import Imem, reset, start_clock


def drive_host(dut, program_words):
    """Drive every top input besides clk, reset and imem_word so none is X,
    with the host idle: nothing pushed, nothing popped."""
    dut.program_words.value = program_words
    dut.gpio_in.value = 0
    dut.tx_data.value = 0
    dut.tx_push.value = 0
    dut.rx_pop.value = 0


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
