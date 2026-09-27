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


# --- Delay one-shot --------------------------------------------------------------

# Every run below starts the same way: PULL 3, 0 takes 0xA5 into shift_reg
# and drops gpio[3], SHIFT_IN 1 with gpio_in[1] high puts 0x80 into
# in_shift_reg, and two more bytes, 0x3C and 0x77, wait in the TX FIFO: one
# for a PULL under test to take and one for it to leave, so a PULL that
# pulled again on a hold cycle would show in the count. The word under test
# comes third, at address 2, and is the last word.
PREFIX = "PULL 3, 0\nSHIFT_IN 1\n"
PRELOAD = (0xA5, 0x3C, 0x77)
GPIO_IN = 0b0010
AT = 2  # the edge the word under test issues on

ONE_SHOT = (
    "PULL", "PULL 2, 0", "PUSH", "PUSH 1, 0", "SHIFT_OUT", "SHIFT_OUT 2, 0", "SHIFT_IN 2", "SHIFT_IN 2, 1, 0",
    "SET 0, 0", "CONFIG shift_dir, 1", "CONFIG open_drain01, 3", "WAIT 1, 1", "SKIP 7, 1", "NOP", "JMP 3",
)


async def trace_of(dut, imem, program, tx=PRELOAD, gpio_in=GPIO_IN):
    await begin(dut, imem, program, tx, gpio_in)
    return await run(dut)


@cocotb.test()
async def a_delay_does_the_operation_once_then_only_holds(dut):
    """`X [d]` against `X`, from the same state, for every kind of X and
    d in 1, 7 and 31. On X's edge the two agree on everything but the pc
    and the counter: the operation, the pin write, the FIFO pop or push,
    all land there. For d more edges nothing moves but the counter: the
    FIFO counts in particular, so a delayed PULL pops one byte and a delayed
    PUSH pushes one. Then the slow run is exactly where the quick one is,
    d edges later."""
    imem = Imem(dut, [])
    start_clock(dut)
    for line in ONE_SHOT:
        quick = await trace_of(dut, imem, assemble(PREFIX + line))
        assert len(quick) == AT + 1 and quick[-1]["halted"], f"{line}: the word under test must be the last edge"
        for delay in (1, 7, DELAY_MAX):
            slow = await trace_of(dut, imem, assemble(f"{PREFIX}{line} [{delay}]"))
            assert len(slow) == len(quick) + delay, f"{line} [{delay}]"
            assert slow[:AT] == quick[:AT]
            for j in range(AT, AT + delay):
                assert held(slow[j]) == held(quick[AT]), f"{line} [{delay}] edge {j}: {slow[j]} vs {quick[AT]}"
                assert (slow[j]["pc"], slow[j]["counter"], slow[j]["halted"]) == (AT, delay - (j - AT), False)
            assert slow[AT + delay] == quick[AT], f"{line} [{delay}]: not where the quick run ended"


# --- Metamorphic pairs -----------------------------------------------------------


def reverse(byte):
    return int(f"{byte:08b}"[::-1], 2)


def wire_lsb(byte):
    return [(byte >> i) & 1 for i in range(8)]


@cocotb.test()
async def shift_out_lsb_first_is_msb_first_of_the_reversed_byte_on_the_pin(dut):
    """For every byte: CONFIG shift_dir 0, PULL, eight SHIFT_OUTs put the
    same levels on gpio[0], edge for edge, as shift_dir 1 does with the
    byte's bit reversal: the reset 1 through CONFIG and PULL, then the bits
    from bit 0 up. Both leave shift_reg empty and the byte consumed."""
    imem = Imem(dut, [])
    start_clock(dut)
    lsb, msb = (assemble(f"CONFIG shift_dir, {d}\nPULL\n" + "SHIFT_OUT\n" * 8) for d in (0, 1))
    for byte in range(256):
        a = await trace_of(dut, imem, lsb, tx=(byte,), gpio_in=0)
        b = await trace_of(dut, imem, msb, tx=(reverse(byte),), gpio_in=0)
        pin = [[s["gpio"][0] for s in states] for states in (a, b)]
        assert pin[0] == pin[1] == [1, 1] + wire_lsb(byte), f"{byte:#04x}: {pin}"
        assert (a[-1]["shift_reg"], b[-1]["shift_reg"], a[-1]["tx_count"], b[-1]["tx_count"]) == (0, 0, 0, 0)


SIDE = (  # a bare word, the same word with a side effect, and the pin and value that adds
    ("PULL", "PULL 2, 0", 2, 0), ("PUSH", "PUSH 1, 0", 1, 0), ("SHIFT_OUT", "SHIFT_OUT 2, 0", 2, 0),
    ("SHIFT_IN 2", "SHIFT_IN 2, 3, 1", 3, 1), ("WAIT 1, 1", "WAIT 1, 1, 0, 0", 0, 0), ("SKIP 7, 1", "SKIP 7, 1, 2, 0", 2, 0),
    ("CONFIG shift_dir, 1", "CONFIG shift_dir, 1, 1, 0", 1, 0), ("NOP", "SET 0, 0", 0, 0),
)


@cocotb.test()
async def a_side_effect_adds_exactly_one_pin_and_nothing_else(dut):
    """`SHIFT_IN 2, 3, 1` runs exactly like `SHIFT_IN 2` and differs only in
    gpio[3], from its edge on; SET is NOP plus the pin. For every kind of
    word, with and without a delay, top's state edge for edge is the bare
    run's with that one pin written and gpio_oe following it."""
    imem = Imem(dut, [])
    start_clock(dut)
    for bare, side, pin, value in SIDE:
        for delay in (0, 5):
            plain = await trace_of(dut, imem, assemble(f"{PREFIX}{bare} [{delay}]"))
            extra = await trace_of(dut, imem, assemble(f"{PREFIX}{side} [{delay}]"))
            expected = [dict(s) for s in plain]
            for s in expected[AT:]:
                s["gpio"] = list(s["gpio"])
                s["gpio"][pin] = value
                s["gpio_oe"] = [0 if od and level else 1 for od, level in zip(s["open_drain"], s["gpio"])]
            assert extra == expected, f"{side} [{delay}]"


def prepends(prompt, late, s, k):
    """`late` is `prompt` with k held edges before edge s: the same pins with
    the levels after edge s - 1 repeated k times, the core frozen through
    them, and every state from the release on the prompt run's, k edges
    later."""
    gp = [[st["gpio"] for st in states] for states in (prompt, late)]
    assert len(late) == len(prompt) + k
    assert gp[1] == gp[0][:s] + [gp[0][s - 1]] * k + gp[0][s:]
    assert all(core(st) == core(late[s - 1]) for st in late[s:s + k])
    assert late[s + k:] == prompt[s:]


@cocotb.test()
async def a_stall_only_prepends_held_cycles(dut):
    """A PULL whose byte the host pushes k stall cycles in ends where one
    whose byte was preloaded ends, k edges later, its pins the same after k
    copies of the held levels. Same for a PUSH and the room the host makes
    by popping, and a WAIT and the level that arrives. The stalled core is
    frozen meanwhile; the delay and the words after run unchanged."""
    imem = Imem(dut, [])
    start_clock(dut)
    for k in (1, 3, 17):
        # PULL at address 1: the byte preloaded, or pushed to land on edge s + k - 1.
        program, s = assemble("SET 1, 0\nPULL 2, 0 [2]\nSHIFT_OUT 3, 1\nSHIFT_IN 0"), 1
        await begin(dut, imem, program, tx=(0xA3,))
        prompt = await run(dut)

        def push(i, t=s + k - 1):
            dut.tx_push.value = i == t
            dut.tx_data.value = 0xA3

        await begin(dut, imem, program)
        prepends(prompt, await run(dut, before=push), s, k)

        # PUSH at address 6, after four PUSHes fill the FIFO: the host pops on
        # the SET's edge, or k stall cycles in.
        program, s = assemble("SHIFT_IN 0\nPUSH\nPUSH\nPUSH\nPUSH\nSET 1, 0\nPUSH 2, 0 [2]\nSHIFT_OUT 3, 1\nSHIFT_IN 0"), 6

        def pop(i, t):
            dut.rx_pop.value = i == t

        await begin(dut, imem, program, gpio_in=0b0001)
        prompt = await run(dut, before=lambda i: pop(i, s - 1))
        await begin(dut, imem, program, gpio_in=0b0001)
        prepends(prompt, await run(dut, before=lambda i, t=s + k - 1: pop(i, t)), s, k)

        # WAIT at address 1: the level there from the start, or before edge s + k.
        program, s = assemble("SET 1, 0\nWAIT 3, 1, 2, 0 [2]\nSHIFT_OUT 3, 1\nSHIFT_IN 0"), 1
        await begin(dut, imem, program, gpio_in=0b1000)
        prompt = await run(dut)

        def level(i, t=s + k):
            if i == t:
                dut.gpio_in.value = 0b1000

        await begin(dut, imem, program, gpio_in=0)
        prepends(prompt, await run(dut, before=level), s, k)
