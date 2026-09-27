"""cocotb tests for rtl/core.v. Run through test_core.py, not directly: each
@cocotb.test() runs inside the Verilator simulation, `dut` is the top-level
module, and `await` hands control back to the simulator until the trigger
(a clock edge, a time step) happens.

The core runs NOP and its delay counter, so the tests check reset and then
step the RTL and the model together, one cycle at a time, comparing state.
"""

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from cpu import CPU, assemble, load_program  # sim/cpu.py, the golden model
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
