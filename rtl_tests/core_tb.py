"""cocotb tests for rtl/core.v. Run through test_core.py, not directly: each
@cocotb.test() runs inside the Verilator simulation, `dut` is the top-level
module, and `await` hands control back to the simulator until the trigger
(a clock edge, a time step) happens.

The core runs NOP and its delay counter, so the tests check reset and then
step the RTL and the model together, one cycle at a time, comparing state.
"""

import random
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from cpu import CPU, Instruction, assemble, decode, encode, load_isa, load_program  # sim/cpu.py, the golden model
from tb import Imem, drive_inputs, gpio_bits, model_state, reset, rtl_state, start_clock

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


@cocotb.test()
async def set_timing_matches_model(dut):
    """SET against the model, cycle by cycle. SET 2, 0 [2] must drive the pin
    on its issue edge, hold it through the delay without rewriting it, and only
    then let the pc move on; the next two SETs run back to back, and running
    off the end checks halted."""
    program = assemble("""
        SET 2, 0 [2]
        SET 1, 0
        SET 2, 1
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
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def config_matches_model(dut):
    """CONFIG against the model, cycle by cycle. Each write lands on its issue
    edge; open_drain01 = 3 with every pin reset high releases pins 0 and 1, so
    gpio_oe drops to 1100 combinationally. The [2] holds the state through the
    delay, and running off the end checks halted."""
    program = assemble("""
        CONFIG shift_dir, 1
        CONFIG open_drain01, 3
        CONFIG open_drain23, 1
        CONFIG shift_dir, 0 [2]
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
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def shift_out_matches_model(dut):
    """SHIFT_OUT against the model, cycle by cycle. With shift_dir 0 each
    SHIFT_OUT drives shift_reg[0] onto gpio[0] and shifts right; the [2] holds
    everything through the delay. CONFIG shift_dir, 1 moves the wire end to
    bit 7, so the last two shift left. Running off the end checks halted."""
    program = assemble("""
        SHIFT_OUT
        SHIFT_OUT [2]
        CONFIG shift_dir, 1
        SHIFT_OUT
        SHIFT_OUT
    """)
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program))
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    # PULL is not in the RTL yet, so seed the shift register identically on
    # both sides. Written before ReadOnly: the read-only phase forbids writes.
    seed = 0b10110001
    cpu.shift_reg = seed
    dut.shift_reg.value = seed
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def shift_in_matches_model(dut):
    """SHIFT_IN against the model, cycle by cycle, with gpio_in held at 1010 so
    each pin reads differently. With shift_dir 0 each sample enters at bit 7
    and shifts right; the [2] holds everything through the delay. CONFIG
    shift_dir, 1 moves the entry to bit 0, so the last two shift left. Running
    off the end checks halted."""
    program = assemble("""
        SHIFT_IN 1
        SHIFT_IN 0
        SHIFT_IN 3 [2]
        CONFIG shift_dir, 1
        SHIFT_IN 2
        SHIFT_IN 1
    """)
    gpio_in = 0b1010
    cpu = CPU(program)
    cpu.gpio_in = gpio_bits(gpio_in)  # CPU(gpio_in=) sets every pin to one level; this is per pin
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program), gpio_in=gpio_in)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def wait_stall_matches_model(dut):
    """WAIT against the model while the pin disagrees, then after it agrees.
    WAIT 0, 0 wants pin 0 low with every pin held high, so edges go by with
    nothing moving. Pin 0 then drops between edges and the WAIT issues like
    any instruction: the stall does not count toward its [2], it still spends
    its full delay before the SET. Running off the end checks halted."""
    program = assemble("""
        WAIT 0, 0 [2]
        SET 1, 0
    """)
    cpu = CPU(program, gpio_in=1)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program), gpio_in=0b1111)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    # Pin 0 is high: every stalled edge changes nothing.
    for _ in range(2):
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert cpu.stalled
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"
        assert (rtl["pc"], rtl["counter"]) == (0, 0)

    # Drop pin 0 on the falling edge, between the rising edges that sample it
    # (the read-only phase forbids writes).
    await FallingEdge(dut.clk)
    cpu.gpio_in[0] = 0
    dut.gpio_in.value = 0b1110

    # Release edge: the WAIT issues and loads its full delay.
    cpu.step()
    await RisingEdge(dut.clk)
    await ReadOnly()
    rtl = rtl_state(dut)
    assert not cpu.stalled
    assert rtl == model_state(cpu), f"cycle {cpu.cycle}: RTL={rtl}, model={model_state(cpu)}"
    assert (rtl["pc"], rtl["counter"]) == (0, 2)

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def jmp_matches_model(dut):
    """JMP against the model, cycle by cycle. The JMP holds the pc through its
    [2], then loads the target on its last cycle, so the SET 1, 0 at address 2
    never runs. Running off the end after target checks halted."""
    program = assemble("""
        SET 0, 0
        JMP target [2]
        SET 1, 0
    target:
        SET 2, 0
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
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"

    assert gpio_bits(dut.gpio_out.value)[1] == 1  # the skipped SET 1, 0 never ran


@cocotb.test()
async def skip_taken_matches_model(dut):
    """SKIP with its condition true, cycle by cycle. in_shift_reg bit 3 is 1,
    so SKIP 3, 1 [2] holds the pc through its delay and then steps it by 2 on
    its last cycle: SET 0, 0 never runs. Running off the end checks halted."""
    program = assemble("""
        SKIP 3, 1 [2]
        SET 0, 0
        SET 1, 0
    """)
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program))
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    # Only bit 3 set: testing the wrong bit reads 0 and falls through.
    seed = 0b00001000
    cpu.in_shift_reg = seed
    dut.in_shift_reg.value = seed
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"

    assert gpio_bits(dut.gpio_out.value)[:2] == [1, 0]  # SET 0, 0 skipped, SET 1, 0 ran


@cocotb.test()
async def skip_not_taken_matches_model(dut):
    """The same SKIP with its condition false: in_shift_reg bit 3 is 0, so
    after the delay the pc steps by 1 and both SETs run."""
    program = assemble("""
        SKIP 3, 1 [2]
        SET 0, 0
        SET 1, 0
    """)
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program))
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    # Every bit but 3 set: testing the wrong bit reads 1 and skips.
    seed = 0b11110111
    cpu.in_shift_reg = seed
    dut.in_shift_reg.value = seed
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"

    assert gpio_bits(dut.gpio_out.value)[:2] == [0, 0]  # both SETs ran


@cocotb.test()
async def pull_matches_model(dut):
    """PULL with a byte waiting, cycle by cycle. tx_data 0xA5 with tx_empty
    low: pull_en is high before the first edge, shift_reg loads 0xA5 on the
    issue edge and the [2] holds it, then SHIFT_OUT shifts it. Running off the
    end checks halted."""
    program = assemble("""
        PULL [2]
        SHIFT_OUT
    """)
    cpu = CPU(program, tx_data=[0xA5])
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program), tx_empty=0, tx_data=0xA5)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)
    assert dut.pull_en.value == 1

    cpu.step()
    await RisingEdge(dut.clk)
    await ReadOnly()
    rtl = rtl_state(dut)
    assert rtl == model_state(cpu), f"cycle {cpu.cycle}: RTL={rtl}, model={model_state(cpu)}"
    assert (rtl["shift_reg"], rtl["pc"], rtl["counter"]) == (0xA5, 0, 2)
    assert dut.pull_en.value == 0  # the delay does not pull again

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def pull_stall_matches_model(dut):
    """PULL against an empty TX FIFO, then after a byte arrives. With tx_empty
    high edges go by with nothing moving and pull_en low. The byte arrives
    between edges, pull_en rises, and the next edge loads shift_reg and
    completes the PULL. Running off the end checks halted."""
    program = assemble("""
        PULL
        SET 0, 0
    """)
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program), tx_empty=1)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    # TX FIFO empty: every stalled edge changes nothing.
    for _ in range(2):
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert cpu.stalled
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"
        assert (rtl["pc"], rtl["counter"]) == (0, 0)
        assert dut.pull_en.value == 0

    # A byte arrives on the falling edge, between the rising edges that sample
    # it (the read-only phase forbids writes).
    await FallingEdge(dut.clk)
    cpu.tx_fifo.append(0xA5)
    dut.tx_data.value = 0xA5
    dut.tx_empty.value = 0
    await ReadOnly()
    assert dut.pull_en.value == 1

    # Release edge: the PULL loads shift_reg and completes.
    cpu.step()
    await RisingEdge(dut.clk)
    await ReadOnly()
    rtl = rtl_state(dut)
    assert not cpu.stalled
    assert rtl == model_state(cpu), f"cycle {cpu.cycle}: RTL={rtl}, model={model_state(cpu)}"
    assert (rtl["shift_reg"], rtl["pc"]) == (0xA5, 1)

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def push_matches_model(dut):
    """PUSH with room in the RX FIFO, cycle by cycle. The FIFO lives outside
    core.v, so the RTL side is the handshake: push_en high with rx_data 0xA5
    leading into the issue edge, then low through the [2] so the byte goes
    out once. The model's rx_fifo gets it on that edge and in_shift_reg keeps
    it. Running off the end checks halted."""
    program = assemble("""
        PUSH [2]
        SET 0, 0
    """)
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program), rx_full=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    # SHIFT_IN fills in_shift_reg; seed it on both sides instead.
    seed = 0xA5
    cpu.in_shift_reg = seed
    dut.in_shift_reg.value = seed
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)
    assert dut.push_en.value == 1
    assert int(dut.rx_data.value) == seed

    cpu.step()
    await RisingEdge(dut.clk)
    await ReadOnly()
    rtl = rtl_state(dut)
    assert rtl == model_state(cpu), f"cycle {cpu.cycle}: RTL={rtl}, model={model_state(cpu)}"
    assert cpu.rx_fifo == [seed]
    assert int(dut.in_shift_reg.value) == seed
    assert dut.push_en.value == 0  # the delay does not push again

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"

    assert cpu.rx_fifo == [seed]


@cocotb.test()
async def push_stall_matches_model(dut):
    """PUSH against a full RX FIFO, then after room opens. With rx_full high
    edges go by with nothing moving and push_en low. rx_full drops between
    edges, push_en rises with rx_data on it, and the next edge completes the
    PUSH. push_en is checked before that edge: a zero-delay PUSH moves the pc
    on it, so after it the core is already decoding the SET. Running off the
    end checks halted."""
    program = assemble("""
        PUSH
        SET 0, 0
    """)
    # The model's FIFO holds one byte and is full, like rx_full on the RTL.
    cpu = CPU(program, rx_depth=1)
    cpu.rx_fifo = [0x00]
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program), rx_full=1)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)

    seed = 0xA5
    cpu.in_shift_reg = seed
    dut.in_shift_reg.value = seed
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    # RX FIFO full: every stalled edge changes nothing.
    for _ in range(2):
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert cpu.stalled
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"
        assert (rtl["pc"], rtl["counter"]) == (0, 0)
        assert dut.push_en.value == 0

    # The outside world pops a byte on the falling edge, between the rising
    # edges that sample rx_full (the read-only phase forbids writes).
    await FallingEdge(dut.clk)
    cpu.rx_fifo.pop(0)
    dut.rx_full.value = 0
    await ReadOnly()
    assert dut.push_en.value == 1
    assert int(dut.rx_data.value) == seed

    # Release edge: the PUSH completes.
    cpu.step()
    await RisingEdge(dut.clk)
    await ReadOnly()
    rtl = rtl_state(dut)
    assert not cpu.stalled
    assert rtl == model_state(cpu), f"cycle {cpu.cycle}: RTL={rtl}, model={model_state(cpu)}"
    assert cpu.rx_fifo == [seed]
    assert rtl["pc"] == 1

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"


@cocotb.test()
async def uart_tx_0x55_matches_model(dut):
    """A real program end to end: programs/uart_tx_0x55.asm, cycle by cycle
    against the model until it halts. Idle, start, 8 data bits and stop is
    11 bit-times of SET [7], 8 clocks each, so 88 clocks, ending with the line
    high."""
    program = load_program(PROGRAMS / "uart_tx_0x55.asm")
    cpu = CPU(program)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program))
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    while not cpu.halted:
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"

    assert cpu.cycle == 88
    assert int(dut.gpio_out.value) & 1 == 1


@cocotb.test()
async def uart_rx_0xa5_matches_model(dut):
    """The receiver end to end: programs/uart_rx.asm, cycle by cycle against
    the model while the bench drives one 8N1 frame of 0xA5 onto gpio_in[0] at
    8 clocks per bit. The WAIT stalls while the line idles high, issues on the
    start edge, the eight SHIFT_INs sample mid-bit, PUSH hands 0xA5 out once
    during the stop bit, and the JMP is back at the WAIT 80 clocks after the
    edge, one frame. The program never halts, so the bench stops it there.
    Word 0 lets go of the RX pad first, so the loop is at pc 1."""
    program = load_program(PROGRAMS / "uart_rx.asm")
    cpu = CPU(program, gpio_in=1)
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=len(program), gpio_in=0b1111, rx_full=0)
    start_clock(dut)
    await reset(dut)
    Imem(dut, program)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)

    pushed = []  # rx_data on every edge push_en led into

    async def cycle(rx):
        """Drive the RX pin between edges (the read-only phase forbids writes),
        note a push leading into the edge, then step both sides across it."""
        await FallingEdge(dut.clk)
        cpu.gpio_in[0] = rx
        dut.gpio_in.value = 0b1110 | rx
        await ReadOnly()
        if dut.push_en.value == 1:
            pushed.append(int(dut.rx_data.value))
        cpu.step()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        model = model_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"
        return rtl

    # Word 0 lets go of the RX pad, then, idle high, the WAIT at 1 stalls.
    rtl = await cycle(1)
    assert rtl["pc"] == 1 and rtl["gpio_oe"][0] == 0
    for _ in range(2):
        rtl = await cycle(1)
        assert cpu.stalled
        assert (rtl["pc"], rtl["counter"]) == (1, 0)

    byte = 0xA5
    frame = [0] + [(byte >> bit) & 1 for bit in range(8)] + [1]  # start, d0..d7 LSB first, stop
    start = cpu.cycle
    for level in frame:
        for _ in range(8):
            await cycle(level)

    # One frame, 80 clocks: back at the WAIT, the byte pushed exactly once.
    assert cpu.cycle - start == 80
    assert pushed == [byte]
    assert cpu.rx_fifo == [byte]
    assert int(dut.in_shift_reg.value) == byte

    # Idle again: the WAIT stalls for the next start bit.
    rtl = await cycle(1)
    assert cpu.stalled
    assert (rtl["pc"], rtl["counter"]) == (1, 0)


# --- REPEAT ---------------------------------------------------------------------------------
#
# The corners tests/test_repeat.py pins on the model, here the RTL against
# the model edge for edge. The FIFOs are inputs on this bench, so the outside
# world is the model's FIFOs: before every edge tx_empty, tx_data and rx_full
# follow them, and a byte fed to or popped from the model reaches the RTL as
# a flag on the next edge, the way top.v's FIFOs would show it.

ISA = load_isa()
BYTE = "        PULL\nbit:    SHIFT_OUT 1, 0 [1]\n        SET 1, 1\n        REPEAT {count}, bit\n        SET 1, 0"


async def cross(dut, cpu):
    """Between edges the RTL's FIFO flags, tx_data and pins follow the model;
    then both cross one edge and every register must agree."""
    dut.tx_empty.value = 0 if cpu.tx_fifo else 1
    dut.tx_data.value = cpu.tx_fifo[0] if cpu.tx_fifo else 0
    dut.rx_full.value = 1 if len(cpu.rx_fifo) >= cpu.rx_depth else 0
    dut.gpio_in.value = sum(level << pin for pin, level in enumerate(cpu.gpio_in))
    cpu.step()
    await RisingEdge(dut.clk)
    await ReadOnly()
    rtl, model = rtl_state(dut), model_state(cpu)
    assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"
    return rtl


async def follow(dut, cpu):
    await FallingEdge(dut.clk)
    return await cross(dut, cpu)


async def load(dut, imem, program, cpu):
    """Reset the core onto `program`, the model at its start; the two agree."""
    await FallingEdge(dut.clk)
    imem.load(program)
    drive_inputs(dut, program_words=len(program), tx_empty=0 if cpu.tx_fifo else 1, tx_data=cpu.tx_fifo[0] if cpu.tx_fifo else 0)
    await reset(dut)
    await ReadOnly()
    assert rtl_state(dut) == model_state(cpu)


async def bench(dut):
    """The clock, a reset, and an instruction memory for load() to fill."""
    dut.imem_word.value = 0
    drive_inputs(dut, program_words=0)
    start_clock(dut)
    await reset(dut)
    return Imem(dut, [])


@cocotb.test()
async def repeat_count_1_2_and_32_match_the_model(dut):
    """A UART-shaped byte: a PULL, then a two-word cell, the shift with its
    clock down and the clock up, REPEATed count times, then the clock down.
    For counts 1, 2 and 32, edge for edge to the halt: 1 + 4 * count + 1
    clocks, rc back at 0."""
    imem = await bench(dut)
    for count in (1, 2, 32):
        program = assemble(BYTE.format(count=count))
        cpu = CPU(program, tx_data=[0x96])
        await load(dut, imem, program, cpu)
        while not cpu.halted:
            await follow(dut, cpu)
        assert cpu.cycle == 1 + 4 * count + 1 and int(dut.rc.value) == 0, count


@cocotb.test()
async def repeat_one_word_body_and_255_word_body_match_the_model(dut):
    """The shortest body, one SHIFT_OUT eight times over, and the longest,
    255 SETs with delays 0, 1, 2 three times over in a 256-word program,
    the operand byte's whole reach: 3 * (255 + 255 + 1) clocks."""
    imem = await bench(dut)
    one = assemble("        PULL\nbit:    SHIFT_OUT [2]\n        REPEAT 8, bit\n        SET 0, 1")
    lines = [f"        SET {i % 4}, {i % 2} [{i % 3}]" for i in range(255)]
    long = assemble("start:" + "\n".join(lines)[6:] + "\n        REPEAT 3, start")
    assert len(long) == 256 and decode(long[-1], ISA).args == (255,)
    for program, tx in ((one, [0x96]), (long, [])):
        cpu = CPU(program, tx_data=tx)
        await load(dut, imem, program, cpu)
        while not cpu.halted:
            await follow(dut, cpu)
    assert cpu.cycle == 3 * (255 + 255 + 1)


@cocotb.test()
async def stalls_inside_a_repeat_body_leave_rc_alone_and_the_repeat_commits_once(dut):
    """A body that PULLs first and PUSHes last, four times over. On the
    second run the byte is withheld 73 clocks at the PULL; the second byte
    PUSHed is left in a one-deep RX FIFO until the third run's PUSH has
    stalled on it 20 clocks. RTL against model every edge; rc moves on
    exactly four edges, the REPEATs', none of them a stall."""
    imem = await bench(dut)
    program = assemble("byte:   PULL 1, 0 [1]\n        SHIFT_OUT 1, 1 [1]\n        SHIFT_IN 0 [1]\n        PUSH 1, 0\n        REPEAT 4, byte\n        SET 2, 0")
    cpu = CPU(program, rx_depth=1)
    await load(dut, imem, program, cpu)
    pushed = withheld = held = 0
    stalls = {"PULL": 0, "PUSH": 0}
    moves = []
    while not cpu.halted:
        at = decode(program[cpu.pc], ISA).op
        issuing = cpu.counter == 0  # not a delay cycle of the same word
        if at == "PULL" and issuing and not cpu.tx_fifo:
            if pushed == 1 and withheld < 73:
                withheld += 1
            else:
                cpu.tx_fifo.append(0x96)
        if cpu.rx_fifo:
            if pushed == 2 and held < 20:
                held += at == "PUSH" and issuing
            else:
                cpu.rx_fifo.pop(0)
        before, rc = len(cpu.rx_fifo), cpu.rc
        rtl = await follow(dut, cpu)
        pushed += len(cpu.rx_fifo) > before
        if cpu.stalled:
            stalls[at] += 1
        if rtl["rc"] != rc:
            moves.append((at, cpu.stalled))
    assert (withheld, held, pushed) == (73, 20, 4)
    assert stalls == {"PULL": 73, "PUSH": 20}
    assert moves == [("REPEAT", False)] * 4


def random_line(rng):
    """One body word of any kind but JMP and REPEAT, a delay of 0..3, a side
    effect half the time on pins 1..3 so a SHIFT_OUT keeps its own pin."""
    d = rng.choice((0, 0, 1, 2, 3))
    side = rng.choice(("", f", {rng.randrange(1, 4)}, {rng.randrange(2)}"))
    return rng.choice((
        f"SET {rng.randrange(4)}, {rng.randrange(2)} [{d}]",
        f"NOP [{d}]",
        f"SHIFT_OUT{side} [{d}]",
        f"SHIFT_IN {rng.randrange(4)}{side} [{d}]",
        f"PULL{side} [{d}]",
        f"PUSH{side} [{d}]",
        f"WAIT {rng.randrange(4)}, {rng.randrange(2)}{side} [{d}]",
        f"SKIP {rng.randrange(8)}, {rng.randrange(2)}{side} [{d}]",
        f"CONFIG shift_dir, {rng.randrange(2)}{side} [{d}]",
    ))


@cocotb.test()
async def random_stalls_inside_random_repeat_bodies_match_the_model(dut):
    """Forty random bodies of one to six words, any word but JMP and REPEAT,
    a SKIP anywhere but last, REPEATed 1..32 times, under an outside world
    that feeds bytes, pops bytes and moves the pins at random, so PULLs,
    PUSHes and WAITs stall inside the body at random moments. RTL against
    model every edge; rc moves only on a REPEAT's edge, never a stalled one;
    and the sweep must stall inside a body with runs still to go."""
    imem = await bench(dut)
    rng = random.Random(5)
    inside = 0
    for seed in range(40):
        body = [random_line(rng) for _ in range(rng.randrange(1, 7))]
        while body[-1].startswith("SKIP"):
            body[-1] = random_line(rng)
        source = "body:   " + "\n        ".join(body) + f"\n        REPEAT {rng.randrange(1, 33)}, body\n        SET 3, 0"
        program = assemble(source)
        cpu = CPU(program, rx_depth=2)
        await load(dut, imem, program, cpu)
        for _ in range(400):
            if cpu.halted:
                break
            if len(cpu.tx_fifo) < 2 and rng.random() < 0.15:
                cpu.tx_fifo.append(rng.randrange(256))
            if cpu.rx_fifo and rng.random() < 0.2:
                cpu.rx_fifo.pop(0)
            cpu.gpio_in = [rng.randrange(2) for _ in range(4)]
            at, rc = decode(program[cpu.pc], ISA).op, cpu.rc
            try:
                rtl = await follow(dut, cpu)
            except AssertionError as e:
                raise AssertionError(f"seed {seed}: {source!r}: {e}") from e
            if rtl["rc"] != rc:
                assert at == "REPEAT" and not cpu.stalled, f"seed {seed}: rc moved on a {at}"
            inside += cpu.stalled and cpu.rc != 0
    assert inside > 50, f"only {inside} stalled edges inside a body with runs to go"


@cocotb.test()
async def reset_in_every_cycle_of_a_loop_matches_the_restarted_model(dut):
    """At every clock t of the byte's 34, reset the core mid-loop, which is
    what top.v's restart does to it: on that edge the RTL is the model
    restarted, rc 0, and the run from there is a fresh run edge for edge,
    34 clocks to the halt."""
    imem = await bench(dut)
    program = assemble(BYTE.format(count=8))
    whole = CPU(program, tx_data=[0x96])
    whole.run()
    total = whole.cycle
    assert total == 34
    for t in range(1, total):
        cpu = CPU(program, tx_data=[0x96, 0x53])
        await load(dut, imem, program, cpu)
        for _ in range(t):
            await follow(dut, cpu)
        await FallingEdge(dut.clk)
        dut.reset.value = 1
        cpu.restart()
        await RisingEdge(dut.clk)
        await ReadOnly()
        rtl = rtl_state(dut)
        assert rtl == model_state(cpu) and rtl["rc"] == 0 and rtl["pc"] == 0, f"reset at clock {t}: {rtl}"
        await FallingEdge(dut.clk)
        dut.reset.value = 0
        await cross(dut, cpu)
        while not cpu.halted:
            await follow(dut, cpu)
        assert cpu.cycle - t == total, f"reset at clock {t}"


@cocotb.test()
async def repeat_reaching_before_word_0_wraps_the_pc_past_the_end_and_halts(dut):
    """Two NOPs then REPEAT 3, five words back: pc 2 - 5 in nine bits is
    509, past any program, halted, rc loaded as any REPEAT loads it. The
    assembler never writes one; the subtract does this on its own."""
    imem = await bench(dut)
    program = [0x0000, 0x0000, encode(Instruction("REPEAT", (5,), 2), ISA), 0x0000]
    cpu = CPU(program)
    await load(dut, imem, program, cpu)
    for _ in range(3):
        rtl = await follow(dut, cpu)
    assert (rtl["pc"], rtl["rc"], rtl["halted"]) == (509, 2, True)


@cocotb.test()
async def repeats_operand_bit_7_is_the_top_of_back_not_a_side_effect_flag(dut):
    """A 240-word body, SET 3, 0 then NOPs, twice over: back is 0xF0, which
    read as every other word's side effect would be pin 3 <- 1 on the
    REPEAT's edge. REPEAT's operand byte is all back: pin 3 stays 0 through
    the loop, as in the model, and the SET after it raises it."""
    imem = await bench(dut)
    program = assemble("start:  SET 3, 0\n" + "        NOP\n" * 239 + "        REPEAT 2, start\n        SET 3, 1")
    assert decode(program[240], ISA) == Instruction("REPEAT", (240,), 1)
    cpu = CPU(program)
    await load(dut, imem, program, cpu)
    while not cpu.halted:
        rtl = await follow(dut, cpu)
        if not cpu.halted:
            assert rtl["gpio"][3] == 0, f"cycle {cpu.cycle}: pin 3 written"
    assert rtl["gpio"][3] == 1 and cpu.cycle == 2 * 241 + 1
