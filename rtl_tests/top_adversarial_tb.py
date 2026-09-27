"""Adversarial cocotb tests for rtl/top.v: the core with its TX and RX FIFOs
under a hostile outside world. Run through test_top_adversarial.py.

Four families, after tests/test_adversarial.py for the model. Stall
invariance: an empty TX FIFO holds a PULL, a full RX FIFO holds a PUSH and a
pin level holds a WAIT for as long as the host likes, nothing moves
meanwhile, and the missing byte, room or level lets the instruction issue
exactly once. Delay one-shot: `X [d]` does X once, on its first edge, then
only holds for d more; a delayed PULL pops one byte, a delayed PUSH pushes
one. Metamorphic pairs: LSB first of a byte is MSB first of its reversal on
the pin, a side effect adds one pin to an instruction and nothing else, a
stall only prepends held cycles to an otherwise identical run. Host
pressure: seeded random programs under random host pushes and pops and
random input pins, cycle for cycle against the golden CPU and its FIFOs.

Every run goes through top's host ports and pins; internals are read only
to compare them. Runs share one simulation: the clock and the instruction
memory task start once per test, each run reloads the memory and resets.
"""

import random

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from cpu import CPU, Instruction, assemble, decode, encode, load_isa
from tb import Imem, drive_host, model_state, reset, rtl_state, start_clock

ISA = load_isa()
OPS = tuple(ISA["instructions"])
DELAY_MAX = (1 << ISA["fields"]["delay"]["bits"]) - 1
DEPTH = 4  # both FIFOs in top.v
STALL = 37  # clocks a stall is held for: longer than any delay, not a multiple of anything
CORE = ("pc", "counter", "gpio", "halted", "shift_dir", "open_drain", "gpio_oe", "shift_reg", "in_shift_reg")
HELD = ("gpio", "open_drain", "gpio_oe", "shift_reg", "in_shift_reg", "shift_dir", "tx_count", "tx_head", "rx_count", "rx_head")


def top_state(dut):
    """The architectural state of top: the core's as tb.rtl_state reads it,
    plus each FIFO as the core and the host see it, count and head. A head
    is read only while the FIFO holds something; empty, it is stale memory."""
    tx, rx = int(dut.tx_fifo.count.value), int(dut.rx_fifo.count.value)
    return {
        **rtl_state(dut.core_i),
        "tx_count": tx, "tx_head": int(dut.tx_fifo.head_data.value) if tx else None,
        "rx_count": rx, "rx_head": int(dut.rx_data.value) if rx else None,
    }


def model_top_state(cpu):
    return {
        **model_state(cpu),
        "tx_count": len(cpu.tx_fifo), "tx_head": cpu.tx_fifo[0] if cpu.tx_fifo else None,
        "rx_count": len(cpu.rx_fifo), "rx_head": cpu.rx_fifo[0] if cpu.rx_fifo else None,
    }


def held(state):
    """What a hold or stall cycle may not touch: everything but the pc, the counter and halted."""
    return {k: state[k] for k in HELD}


def core(state):
    return {k: state[k] for k in CORE}


def pins(levels):
    return [(levels >> pin) & 1 for pin in range(4)]


async def begin(dut, imem, program, tx=(), gpio_in=0):
    """Load `program`, reset top, preload the TX FIFO with `tx` through the
    host port while program_words is 0 holds the core, drive the input pins,
    then release the core. Returns between edges: the next rising edge is
    the program's first."""
    await FallingEdge(dut.clk)
    imem.load(program)
    drive_host(dut, program_words=0)
    dut.gpio_in.value = gpio_in
    await reset(dut)
    for byte in tx:
        await FallingEdge(dut.clk)
        dut.tx_data.value = byte
        dut.tx_push.value = 1
    await FallingEdge(dut.clk)
    dut.tx_push.value = 0
    dut.program_words.value = len(program)


async def run(dut, before=None, limit=400):
    """Cross rising edges until the core halts; return top_state after each.
    `before(i)` is called between edges, before edge i, for the host to act.
    Fails if the program is still running after `limit` edges."""
    states = []
    for i in range(limit):
        if before:
            before(i)
        await RisingEdge(dut.clk)
        await ReadOnly()
        states.append(top_state(dut))
        await FallingEdge(dut.clk)
        if states[-1]["halted"]:
            return states
    raise AssertionError(f"core still running after {limit} clocks")


class Lockstep:
    """top and the golden CPU crossing the same edges. edge() steps both
    across one and compares them. push(byte) and pop() queue host actions
    for the coming edge and pins(levels) sets the input pins for it, on both
    sides. A host action reaches the model after its step across that edge,
    which is when the core sees it too: a byte pushed on an edge is in the
    FIFO from the next edge on, a byte popped on an edge is the head before
    it. pulls and pushes count the edges pull_en and push_en led into."""

    def __init__(self, dut, cpu):
        self.dut, self.cpu = dut, cpu
        self.push_byte, self.pop_now = None, False
        self.pulls = self.pushes = 0
        self.popped = []  # bytes the host took, as rx_data showed them

    def push(self, byte):
        self.push_byte = byte

    def pop(self):
        self.pop_now = True

    def pins(self, levels):
        self.dut.gpio_in.value = levels
        self.cpu.gpio_in = pins(levels)

    async def edge(self):
        dut, cpu = self.dut, self.cpu
        dut.tx_push.value = self.push_byte is not None
        if self.push_byte is not None:
            dut.tx_data.value = self.push_byte
        dut.rx_pop.value = self.pop_now
        popped = int(dut.rx_data.value) if self.pop_now else None
        self.pulls += int(dut.core_i.pull_en.value)
        self.pushes += int(dut.core_i.push_en.value)
        cpu.step()
        await RisingEdge(dut.clk)
        if self.push_byte is not None:
            cpu.tx_fifo.append(self.push_byte)
        if self.pop_now:
            self.popped.append(popped)
            assert cpu.rx_fifo.pop(0) == popped, "the host read a different head than the model's"
        self.push_byte, self.pop_now = None, False
        await ReadOnly()
        rtl, model = top_state(dut), model_top_state(cpu)
        assert rtl == model, f"cycle {cpu.cycle}: RTL={rtl}, model={model}"
        await FallingEdge(dut.clk)
        dut.tx_push.value = 0
        dut.rx_pop.value = 0
        return rtl


# --- Stall invariance ----------------------------------------------------------


@cocotb.test()
async def pull_holds_on_an_empty_tx_fifo_until_the_host_pushes_once(dut):
    """The PULL is up against an empty TX FIFO for STALL clocks with the host
    idle: the whole of top is frozen, pull_en never rises. One host push and
    the PULL issues on the edge after the byte lands, once: shift_reg takes
    the byte, the FIFO is empty again, its side effect drops the pin, the
    delay holds, and pull_en led into exactly one edge in the whole run."""
    program = assemble("SET 3, 0\nPULL 2, 0 [2]\nSHIFT_OUT\nSET 1, 0")
    imem, cpu = Imem(dut, []), CPU(program)
    start_clock(dut)
    await begin(dut, imem, program)
    ls = Lockstep(dut, cpu)
    await ls.edge()  # SET
    frozen = await ls.edge()  # the PULL finds nothing
    assert cpu.stalled and frozen["pc"] == 1 and frozen["tx_count"] == 0

    for _ in range(STALL):
        assert await ls.edge() == frozen
        assert cpu.stalled
    assert ls.pulls == 0

    ls.push(0xA3)
    landed = await ls.edge()  # the byte lands; the core saw an empty FIFO on this edge
    assert cpu.stalled and landed == {**frozen, "tx_count": 1, "tx_head": 0xA3}
    issued = await ls.edge()
    assert not cpu.stalled
    assert (issued["shift_reg"], issued["tx_count"], issued["gpio"]) == (0xA3, 0, [1, 1, 0, 0])
    assert (issued["pc"], issued["counter"]) == (1, 2)
    while not cpu.halted:
        await ls.edge()
    assert ls.pulls == 1
    assert (top_state(dut)["tx_count"], top_state(dut)["shift_reg"]) == (0, 0xA3 >> 1)


@cocotb.test()
async def push_holds_on_a_full_rx_fifo_until_the_host_pops_once(dut):
    """Four PUSHes fill the RX FIFO, the fifth is up against it for STALL
    clocks with the host idle: frozen, push_en never rises. One host pop
    and the PUSH issues on the edge after the room appears, once: the FIFO
    is full again with the same byte, its side effect drops the pin, and
    push_en led into exactly five edges in the whole run."""
    program = assemble("SHIFT_IN 0\nPUSH\nPUSH\nPUSH\nPUSH\nSET 3, 0\nPUSH 1, 0 [2]\nSET 0, 0")
    imem, cpu = Imem(dut, []), CPU(program, rx_depth=DEPTH)
    start_clock(dut)
    await begin(dut, imem, program)
    ls = Lockstep(dut, cpu)
    ls.pins(0b0001)  # SHIFT_IN 0 makes in_shift_reg 0x80: the byte every PUSH sends
    for _ in range(6):
        await ls.edge()  # SHIFT_IN, four PUSHes, SET
    frozen = await ls.edge()  # the fifth PUSH finds no room
    assert cpu.stalled and frozen["pc"] == 6 and (frozen["rx_count"], frozen["rx_head"]) == (DEPTH, 0x80)

    for _ in range(STALL):
        assert await ls.edge() == frozen
        assert cpu.stalled
    assert ls.pushes == 4

    ls.pop()
    room = await ls.edge()  # the head leaves; the core saw a full FIFO on this edge
    assert cpu.stalled and room == {**frozen, "rx_count": DEPTH - 1} and ls.popped == [0x80]
    issued = await ls.edge()
    assert not cpu.stalled
    assert (issued["rx_count"], issued["rx_head"], issued["gpio"]) == (DEPTH, 0x80, [1, 0, 1, 0])
    assert (issued["pc"], issued["counter"]) == (6, 2)
    while not cpu.halted:
        await ls.edge()
    assert ls.pushes == 5
    assert top_state(dut)["rx_count"] == DEPTH


@cocotb.test()
async def wait_holds_on_a_pin_level_until_it_arrives_then_issues_once(dut):
    """The WAIT is up against gpio_in[2] low for STALL clocks: frozen. The
    level arrives and the WAIT issues on the next edge, once: its side
    effect drops gpio[1] on that edge and never again, the delay holds."""
    program = assemble("SET 3, 0\nWAIT 2, 1, 1, 0 [2]\nSET 0, 0")
    imem, cpu = Imem(dut, []), CPU(program)
    start_clock(dut)
    await begin(dut, imem, program)
    ls = Lockstep(dut, cpu)
    ls.pins(0b0000)
    await ls.edge()  # SET
    frozen = await ls.edge()  # the WAIT finds the pin low
    assert cpu.stalled and frozen["pc"] == 1 and frozen["gpio"] == [1, 1, 1, 0]

    for _ in range(STALL):
        assert await ls.edge() == frozen
        assert cpu.stalled

    ls.pins(0b0100)
    issued = await ls.edge()
    assert not cpu.stalled
    assert (issued["gpio"], issued["pc"], issued["counter"]) == ([1, 0, 1, 0], 1, 2)
    falls = 0
    previous = issued
    while not cpu.halted:
        state = await ls.edge()
        falls += previous["gpio"][1] == 1 and state["gpio"][1] == 0
        previous = state
    assert falls == 0, "gpio[1] fell once, on the issue edge, and not again"
    assert top_state(dut)["gpio"] == [0, 0, 1, 0]
