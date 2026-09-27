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
HELD = ("gpio", "open_drain", "gpio_oe", "shift_reg", "in_shift_reg", "shift_dir", "tx", "rx")


def fifo_queue(fifo):
    """Every byte a FIFO holds, oldest first, read out of its memory from the
    read pointer: what the core or the host will get, not just the head. A
    slot past the count is stale memory and is not read."""
    count, rd_ptr = int(fifo.count.value), int(fifo.rd_ptr.value)
    return [int(fifo.mem[(rd_ptr + i) % DEPTH].value) for i in range(count)]


def top_state(dut):
    """The architectural state of top: the core's as tb.rtl_state reads it,
    plus every byte each FIFO holds, oldest first."""
    return {**rtl_state(dut.core_i), "tx": fifo_queue(dut.tx_fifo), "rx": fifo_queue(dut.rx_fifo)}


def model_top_state(cpu):
    return {**model_state(cpu), "tx": list(cpu.tx_fifo), "rx": list(cpu.rx_fifo)}


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
    across one and compares them, every register and every queued byte.
    push(byte), pop(), restart() and reset() queue host actions for the
    coming edge; pins(levels) sets the input pins for it. Whatever drives
    dut.gpio_in before an edge, pins() or a pad model, the model reads the
    same levels for its step. A push or pop reaches the model after its step
    across that edge, which is when the core sees it too: a byte pushed on
    an edge is in the FIFO from the next edge on, a byte popped on an edge is
    the head before it. The host may misbehave, as fifo.v lets it: a push
    into a full FIFO is dropped unless the core pulls on that edge, a pop of
    an empty one is nothing, and both are counted. A restart is the model
    built afresh with the FIFOs kept, a reset with them emptied; the core is
    frozen on that edge, so it pops and pushes nothing, and a reset drops the
    host's push too. The model holds still once halted, as the core does.
    pulls and pushes count the edges the FIFOs popped for a PULL and pushed
    for a PUSH; the host's dropped pushes and idle pops are counted too."""

    def __init__(self, dut, cpu):
        self.dut, self.cpu = dut, cpu
        self.push_byte, self.pop_now, self.restart_now, self.reset_now = None, False, False, False
        self.pulls = self.pushes = self.dropped = self.idle_pops = self.edges = 0
        self.popped = []  # bytes the host took, as rx_data showed them

    def push(self, byte):
        self.push_byte = byte

    def pop(self):
        self.pop_now = True

    def restart(self):
        self.restart_now = True

    def reset(self):
        self.reset_now = True

    def pins(self, levels):
        self.dut.gpio_in.value = levels
        self.cpu.gpio_in = pins(levels)

    def fresh(self, tx, rx):
        cpu = CPU(self.cpu.program, rx_depth=DEPTH)
        cpu.tx_fifo, cpu.rx_fifo, cpu.gpio_in = list(tx), list(rx), list(self.cpu.gpio_in)
        return cpu

    async def edge(self):
        dut, cpu = self.dut, self.cpu
        dut.tx_push.value = self.push_byte is not None
        if self.push_byte is not None:
            dut.tx_data.value = self.push_byte
        dut.rx_pop.value = self.pop_now
        dut.restart.value = self.restart_now
        dut.reset.value = self.reset_now
        await ReadOnly()  # the inputs as the edge will find them, a pad model's included
        cpu.gpio_in = pins(int(dut.gpio_in.value))
        head, had_rx = int(dut.rx_data.value), bool(cpu.rx_fifo)
        self.pulls += int(dut.tx_fifo.pop.value)
        self.pushes += int(dut.rx_fifo.push.value)
        if self.reset_now:
            cpu = self.cpu = self.fresh(tx=(), rx=())
        elif self.restart_now:
            cpu = self.cpu = self.fresh(tx=cpu.tx_fifo, rx=cpu.rx_fifo)
        elif not cpu.halted:
            cpu.step()
        await RisingEdge(dut.clk)
        self.edges += 1
        if self.push_byte is not None and not self.reset_now:
            if len(cpu.tx_fifo) < DEPTH:
                cpu.tx_fifo.append(self.push_byte)
            else:
                self.dropped += 1
        if self.pop_now and not self.reset_now:
            if had_rx:
                self.popped.append(head)
                assert cpu.rx_fifo.pop(0) == head, "the host read a different head than the model's"
            else:
                self.idle_pops += 1
        self.push_byte, self.pop_now, self.restart_now, self.reset_now = None, False, False, False
        await ReadOnly()
        rtl, model = top_state(dut), model_top_state(cpu)
        assert rtl == model, f"edge {self.edges}: RTL={rtl}, model={model}"
        await FallingEdge(dut.clk)
        dut.tx_push.value = 0
        dut.rx_pop.value = 0
        dut.restart.value = 0
        dut.reset.value = 0
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
    assert cpu.stalled and frozen["pc"] == 1 and frozen["tx"] == []

    for _ in range(STALL):
        assert await ls.edge() == frozen
        assert cpu.stalled
    assert ls.pulls == 0

    ls.push(0xA3)
    landed = await ls.edge()  # the byte lands; the core saw an empty FIFO on this edge
    assert cpu.stalled and landed == {**frozen, "tx": [0xA3]}
    issued = await ls.edge()
    assert not cpu.stalled
    assert (issued["shift_reg"], issued["tx"], issued["gpio"]) == (0xA3, [], [1, 1, 0, 0])
    assert (issued["pc"], issued["counter"]) == (1, 2)
    while not cpu.halted:
        await ls.edge()
    assert ls.pulls == 1
    assert (top_state(dut)["tx"], top_state(dut)["shift_reg"]) == ([], 0xA3 >> 1)


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
    assert cpu.stalled and frozen["pc"] == 6 and frozen["rx"] == [0x80] * DEPTH

    for _ in range(STALL):
        assert await ls.edge() == frozen
        assert cpu.stalled
    assert ls.pushes == 4

    ls.pop()
    room = await ls.edge()  # the head leaves; the core saw a full FIFO on this edge
    assert cpu.stalled and room == {**frozen, "rx": [0x80] * (DEPTH - 1)} and ls.popped == [0x80]
    issued = await ls.edge()
    assert not cpu.stalled
    assert (issued["rx"], issued["gpio"]) == ([0x80] * DEPTH, [1, 0, 1, 0])
    assert (issued["pc"], issued["counter"]) == (6, 2)
    while not cpu.halted:
        await ls.edge()
    assert ls.pushes == 5
    assert top_state(dut)["rx"] == [0x80] * DEPTH


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
        assert (a[-1]["shift_reg"], b[-1]["shift_reg"], a[-1]["tx"], b[-1]["tx"]) == (0, 0, [], [])


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


# --- Host pressure ---------------------------------------------------------------


def random_instruction(rng, n_words, ops=OPS):
    """A valid instruction, drawn as tests/test_adversarial.py draws them:
    an opcode from `ops`, operands in range, a JMP target inside the program
    or its halt address, a side effect half the time and never SHIFT_OUT's
    on pin 0."""
    op = rng.choice(ops)
    spec = ISA["instructions"][op]
    delay = rng.choice((0, 0, 0, 1, 2, 3, DELAY_MAX))
    if op == "JMP":
        return Instruction(op, (rng.randrange(n_words + 1),), delay)
    if op == "CONFIG":
        cfg = rng.choice(list(ISA["config"].values()))
        args = (cfg["field"], rng.randrange(1 << cfg["bits"]))
    else:
        args = tuple(rng.randrange(1 << o["bits"]) for o in spec["operands"])
    side = None
    if spec.get("side_effect") and rng.random() < 0.5:
        side = (rng.choice((1, 2, 3)) if op == "SHIFT_OUT" else rng.randrange(4), rng.randrange(2))
    return Instruction(op, args, delay, side)


RECEIVER = OPS + ("PUSH",) * 6  # PUSH seven times in sixteen


def random_program(rng):
    """Two to eleven words. A quarter of the programs are receivers, heavy
    on PUSH: the RX FIFO is four deep, so only a program that PUSHes four
    times under a host that does not pop ever stalls a PUSH."""
    n = rng.randrange(2, 12)
    ops = RECEIVER if rng.random() < 0.25 else OPS
    return [encode(random_instruction(rng, n, ops), ISA) for _ in range(n)]


SEEDS = 100
CYCLES = 200
TEMPERAMENTS = (0.0, 0.05, 0.3, 0.8)  # how often a host acts per edge: from never to most edges


@cocotb.test()
async def random_programs_under_host_pressure_match_the_model(dut):
    """SEEDS random programs, each for CYCLES clocks or until it halts,
    against the golden CPU with a DEPTH-deep RX FIFO, edge for edge: the
    core's registers, every byte in both FIFOs after every edge, and every
    byte the host pops. The outside world is the same seed on both
    sides. Each seed draws a host temperament: how often it pushes when the
    TX FIFO is not full and how often it pops when the RX FIFO is not
    empty, from never to most edges, so some runs starve the PULLs and
    some let the PUSHes fill the FIFO. New input levels on every edge, so
    WAITs stall and release at random. The sweep must reach every kind of
    cycle for every kind of word to count."""
    imem = Imem(dut, [])
    start_clock(dut)
    seen = {"stall": set(), "issue": set(), "hold": set()}
    pushed = popped = halted = 0
    for seed in range(SEEDS):
        rng = random.Random(seed)
        program = random_program(rng)
        preload = [rng.randrange(256) for _ in range(rng.randrange(3))]
        push_often, pop_often = rng.choice(TEMPERAMENTS), rng.choice(TEMPERAMENTS)
        levels = rng.randrange(16)
        await begin(dut, imem, program, tx=preload, gpio_in=levels)
        cpu = CPU(program, tx_data=preload, rx_depth=DEPTH)
        ls = Lockstep(dut, cpu)
        ls.pins(levels)
        for _ in range(CYCLES):
            if cpu.halted:
                halted += 1
                break
            op, counter = decode(program[cpu.pc], ISA).op, cpu.counter
            if int(dut.tx_full.value) == 0 and rng.random() < push_often:
                ls.push(rng.randrange(256))
                pushed += 1
            if int(dut.rx_empty.value) == 0 and rng.random() < pop_often:
                ls.pop()
            ls.pins(rng.randrange(16))
            try:
                await ls.edge()
            except AssertionError as e:
                raise AssertionError(f"seed {seed}, program {[f'{w:#06x}' for w in program]}: {e}") from e
            seen["stall" if cpu.stalled else "issue" if counter == 0 else "hold"].add(op)
        popped += len(ls.popped)
    assert seen["stall"] == {"PULL", "PUSH", "WAIT"}, seen
    assert seen["issue"] == seen["hold"] == set(OPS), seen
    assert pushed > 0 and popped > 0 and 0 < halted < SEEDS, (pushed, popped, halted)


async def matched(dut, imem, program, tx=(), gpio_in=0, limit=400):
    """Run `program` to its halt in lockstep with the model, the host idle and
    the pins held at `gpio_in`, and return top_state after each edge."""
    await begin(dut, imem, program, tx, gpio_in)
    ls = Lockstep(dut, CPU(program, tx_data=tx, rx_depth=DEPTH))
    ls.pins(gpio_in)
    states = []
    while not ls.cpu.halted:
        states.append(await ls.edge())
        assert len(states) <= limit, f"still running after {limit} clocks"
    return states


# --- Stalls against delays ---------------------------------------------------------

# A word that stalls, with a side effect and a delay, and what releases it.
STALLED = (("PULL 2, 0 [7]", "push"), ("PUSH 1, 0 [7]", "pop"), ("WAIT 2, 1, 1, 0 [7]", "level"))
FILL_RX = "SHIFT_IN 0\nPUSH\nPUSH\nPUSH\nPUSH\n"  # with gpio_in[0] high: four 0x80s, the RX FIFO full


@cocotb.test()
async def a_stall_and_a_delay_never_share_a_cycle(dut):
    """Three things a stall and a delay must not do to each other, for a
    PULL, a PUSH and a WAIT with a side effect and a [7]. The stall does not
    eat the delay: held STALL clocks, the word still holds its full 7 after
    it issues, and the pins change on three edges only, the SET before it,
    its own issue edge and the SET after. The delay does not re-check the
    stall: the byte, the room or the level the word issued on is gone during
    its hold, and the hold runs out on time. And a hold ending on a word that
    must stall: the stall begins on the edge after the hold's last, the pc
    on the stalling word and the counter at 0, and the release issues it
    once."""
    imem = Imem(dut, [])
    start_clock(dut)

    # (1) SET 3, 0, the word stalled STALL clocks, released, then SET 0, 0.
    for line, release in STALLED:
        program = assemble(f"{FILL_RX if release == 'pop' else ''}SET 3, 0\n{line}\nSET 0, 0")
        await begin(dut, imem, program, gpio_in=0b0001)  # pin 0 high for the fill, the WAIT's pin 2 low
        ls = Lockstep(dut, CPU(program, rx_depth=DEPTH))
        ls.pins(0b0001)
        changes, previous = [], top_state(dut)["gpio"]

        async def step():
            nonlocal previous
            state = await ls.edge()
            if state["gpio"] != previous:
                changes.append(ls.edges)
            previous = state["gpio"]
            return state

        n = len(program) - 2  # the stalling word's address, and the edges before it
        for _ in range(n):
            await step()
        frozen = await step()
        assert ls.cpu.stalled and (frozen["pc"], frozen["counter"]) == (n, 0), line
        for _ in range(STALL):
            assert await step() == frozen and ls.cpu.stalled, line
        if release == "push":
            ls.push(0x96)
            assert await step() == {**frozen, "tx": [0x96]} and ls.cpu.stalled, line
        elif release == "pop":
            ls.pop()
            assert await step() == {**frozen, "rx": [0x80] * (DEPTH - 1)} and ls.cpu.stalled, line
        else:
            ls.pins(0b0101)
        issued = await step()
        issue_edge = ls.edges
        assert not ls.cpu.stalled and (issued["pc"], issued["counter"]) == (n, 7), line
        for i in range(7):
            state = await step()
            assert held(state) == held(issued), f"{line}: hold edge {i} moved {state}"
            assert (state["pc"], state["counter"]) == ((n, 6 - i) if i < 6 else (n + 1, 0)), f"{line}: hold edge {i}"
        last = await step()
        assert last["halted"], line
        assert changes == [n, issue_edge, ls.edges], f"{line}: the pins changed on edges {changes}"
        assert (ls.pulls, ls.pushes) == ((1, 0) if release == "push" else (0, 5) if release == "pop" else (0, 0)), line

    # (2) The word issues, then what it waited for goes away during its hold.
    gone = (
        ("WAIT 2, 1 [7]\nSET 0, 0", (), 0b0100, 0),  # the level leaves on the first hold edge
        ("PULL [7]\nSET 0, 0", (0x96,), 0, 0),  # the only byte is taken: the FIFO is empty through the hold
        ("SHIFT_IN 0\nPUSH\nPUSH\nPUSH\nPUSH [7]\nSET 0, 0", (), 0b0001, 4),  # the fourth PUSH fills the FIFO on its edge and holds against it full
    )
    for source, tx, gpio_in, n in gone:
        program = assemble(source)
        await begin(dut, imem, program, tx=tx, gpio_in=gpio_in)
        ls = Lockstep(dut, CPU(program, tx_data=tx, rx_depth=DEPTH))
        ls.pins(gpio_in)
        for _ in range(n):
            await ls.edge()
        issued = await ls.edge()
        assert not ls.cpu.stalled and (issued["pc"], issued["counter"]) == (n, 7), source
        ls.pins(0)
        for i in range(7):
            state = await ls.edge()
            assert held(state) == held(issued), f"{source}: hold edge {i} moved {state}"
            assert (state["pc"], state["counter"]) == ((n, 6 - i) if i < 6 else (n + 1, 0)), f"{source}: hold edge {i}"
        assert (await ls.edge())["halted"], source

    # (3) NOP [3] then a word that must stall: the stall starts where the hold ends.
    for line, release in (("PULL", "push"), ("PUSH", "pop"), ("WAIT 2, 1", "level")):
        program = assemble(f"{FILL_RX if release == 'pop' else ''}NOP [3]\n{line}\nSET 0, 0")
        await begin(dut, imem, program, gpio_in=0b0001)
        ls = Lockstep(dut, CPU(program, rx_depth=DEPTH))
        ls.pins(0b0001)
        f = len(program) - 3  # the NOP's address
        for _ in range(f):
            await ls.edge()
        state = await ls.edge()
        assert (state["pc"], state["counter"]) == (f, 3), line
        for i in range(3):
            state = await ls.edge()
            assert (state["pc"], state["counter"]) == ((f, 2 - i) if i < 2 else (f + 1, 0)), f"{line}: hold edge {i}"
        assert not ls.cpu.stalled, line
        frozen = await ls.edge()
        assert ls.cpu.stalled and core(frozen) == core(state), f"{line}: the stall changed {frozen}"
        for _ in range(STALL):
            assert await ls.edge() == frozen and ls.cpu.stalled, line
        if release == "push":
            ls.push(0x96)
            await ls.edge()
        elif release == "pop":
            ls.pop()
            await ls.edge()
        else:
            ls.pins(0b0101)
        issued = await ls.edge()
        assert not ls.cpu.stalled and (issued["pc"], issued["counter"]) == (f + 2, 0), line
        assert (await ls.edge())["halted"], line
        assert (ls.pulls, ls.pushes) == ((1, 0) if release == "push" else (0, 5) if release == "pop" else (0, 0)), line


# --- Branches ------------------------------------------------------------------------


@cocotb.test()
async def a_skip_right_after_a_sample_decides_on_that_sample(dut):
    """SHIFT_IN 1 then SKIP on the bit the sample landed in, bit 7 LSB first
    and bit 0 MSB first. The pin holds the sampled level before the
    SHIFT_IN's edge only and the opposite before every other edge, so a
    sample one edge early or late, or a SKIP reading the pin instead of the
    register, decides the other way. With a [3] on the SHIFT_IN, on the SKIP
    and on both, the pin keeps the opposite level through the holds. Then two
    samples back to back and a SKIP on each: the first lands in bit 7 and is
    shifted to bit 6 by the second."""
    imem = Imem(dut, [])
    start_clock(dut)
    for shift_dir in (0, 1):
        bit = 7 if shift_dir == 0 else 0
        head = "CONFIG shift_dir, 1\n" if shift_dir else ""
        e = len(assemble(head))  # the SHIFT_IN's address, and the edge it issues on
        for d1, d2 in ((0, 0), (3, 0), (0, 3), (3, 3)):
            for s in (0, 1):
                program = assemble(f"{head}SHIFT_IN 1 [{d1}]\nSKIP {bit}, 1 [{d2}]\nSET 0, 0\nSET 2, 0")
                await begin(dut, imem, program, gpio_in=(1 - s) << 1)
                ls = Lockstep(dut, CPU(program, rx_depth=DEPTH))
                which = f"shift_dir {shift_dir}, [{d1}] [{d2}], sample {s}"
                while not ls.cpu.halted:
                    ls.pins((s if ls.edges == e else 1 - s) << 1)
                    state = await ls.edge()
                    if ls.edges == e + 1:
                        assert state["in_shift_reg"] == s << bit, which
                    if ls.edges == e + 2 + d1 + d2:  # the SKIP's last edge
                        assert state["pc"] == e + 2 + s, f"{which}: pc {state['pc']} after the SKIP"
                assert state["gpio"] == [s, 1, 0, 1], which  # SET 0, 0 skipped on a 1
                assert ls.edges == e + 2 + d1 + d2 + 2 - s, which

    program = assemble("SHIFT_IN 1\nSHIFT_IN 1\nSKIP 6, 1\nSET 0, 0\nSKIP 7, 1\nSET 2, 0\nSET 3, 0")
    for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
        await begin(dut, imem, program, gpio_in=a << 1)
        ls = Lockstep(dut, CPU(program, rx_depth=DEPTH))
        while not ls.cpu.halted:
            ls.pins({0: a, 1: b}.get(ls.edges, 1 - b) << 1)
            state = await ls.edge()
        assert state["in_shift_reg"] == (b << 7) | (a << 6), (a, b)
        assert state["gpio"] == [a, 1, b, 0], (a, b)  # each SET skipped on its own sample


@cocotb.test()
async def a_branch_moves_the_pc_on_its_last_edge_only(dut):
    """For d in 0, 1, 5 and 31. `JMP 2 [d]` over a SET keeps the pc on the
    JMP through the delay and the SET never runs. `JMP 1 [d]` to the next
    word runs edge for edge like `NOP [d]`. After a SHIFT_IN that put a 1 in
    bit 7, `SKIP 7, 1 [d]` runs like `JMP 3 [d]`; after a 0, like `NOP [d]`.
    `JMP 0 [d]` at address 0 loops with period d + 1 and never halts. A JMP
    to the halt address halts after its delay, a SKIP over the last word
    halts and that word never runs."""
    imem = Imem(dut, [])
    start_clock(dut)
    tail = "SET 3, 0\nSET 2, 0"
    for d in (0, 1, 5, DELAY_MAX):
        states = await matched(dut, imem, assemble(f"JMP 2 [{d}]\n{tail}"))
        assert [s["pc"] for s in states] == [0] * d + [2, 3], d
        assert all(s["gpio"][3] == 1 for s in states) and states[-1]["gpio"] == [1, 1, 0, 1], d

        nop = await matched(dut, imem, assemble(f"NOP [{d}]\n{tail}"))
        assert await matched(dut, imem, assemble(f"JMP 1 [{d}]\n{tail}")) == nop, d

        one = await matched(dut, imem, assemble(f"SHIFT_IN 0\nSKIP 7, 1 [{d}]\n{tail}"), gpio_in=1)
        assert one == await matched(dut, imem, assemble(f"SHIFT_IN 0\nJMP 3 [{d}]\n{tail}"), gpio_in=1), d
        assert one[-1]["gpio"] == [1, 1, 0, 1] and len(one) == d + 3, d
        zero = await matched(dut, imem, assemble(f"SHIFT_IN 0\nSKIP 7, 1 [{d}]\n{tail}"), gpio_in=0)
        assert zero == await matched(dut, imem, assemble(f"SHIFT_IN 0\nNOP [{d}]\n{tail}"), gpio_in=0), d
        assert zero[-1]["gpio"] == [1, 1, 0, 0] and len(zero) == d + 4, d

        program = assemble(f"JMP 0 [{d}]\nSET 3, 0")
        await begin(dut, imem, program)
        ls = Lockstep(dut, CPU(program, rx_depth=DEPTH))
        for _ in range(3 * (d + 1)):
            state = await ls.edge()
            assert (state["pc"], state["gpio"][3], state["halted"]) == (0, 1, False), d
            assert state["counter"] == d - (ls.edges - 1) % (d + 1), (d, ls.edges)

        states = await matched(dut, imem, assemble(f"JMP 1 [{d}]"))
        assert len(states) == d + 1 and states[-1]["pc"] == 1, d
        states = await matched(dut, imem, assemble(f"SHIFT_IN 0\nSKIP 7, 1 [{d}]\nSET 3, 0"), gpio_in=1)
        assert len(states) == d + 2 and (states[-1]["pc"], states[-1]["gpio"][3]) == (3, 1), d


# --- Configuration next to the pins ---------------------------------------------------


def oe(gpio, open_drain):
    return [0 if od and level else 1 for od, level in zip(open_drain, gpio)]


@cocotb.test()
async def a_config_next_to_a_pin_write_settles_the_pad_on_that_edge(dut):
    """gpio_oe follows open_drain and the level together, on the edge either
    lands. Each CONFIG mask bit reaches its own pin and no other. `CONFIG
    open_drain01, 1, 0, 1` makes pin 0 open-drain and writes it 1 on one
    edge: released at once; with `0, 0` it drives its 0. A 0 then open-drain
    keeps driving, a 1 then releases, push-pull again while 1 drives high,
    and push-pull with a 0 written on the same edge drives low at once. A
    shift_dir change with a side effect between two SHIFT_OUTs, or two
    SHIFT_INs, turns the byte around mid-way: the bits then come from, or
    go to, the other end."""
    imem = Imem(dut, [])
    start_clock(dut)
    for pin in range(4):
        field, mask = ("open_drain01", "open_drain23")[pin // 2], 1 << (pin % 2)
        states = await matched(dut, imem, assemble(f"CONFIG {field}, {mask}"))
        assert states[-1]["gpio_oe"] == [0 if k == pin else 1 for k in range(4)], pin
        assert states[-1]["open_drain"] == [1 if k == pin else 0 for k in range(4)], pin

    for value, gpio_oe in ((1, [0, 1, 1, 1]), (0, [1, 1, 1, 1])):
        states = await matched(dut, imem, assemble(f"CONFIG open_drain01, 1, 0, {value}"))
        assert (states[-1]["gpio"], states[-1]["gpio_oe"]) == ([value, 1, 1, 1], gpio_oe), value

    states = await matched(dut, imem, assemble("SET 0, 0\nCONFIG open_drain01, 1\nSET 0, 1\nCONFIG open_drain01, 0\nSET 0, 0"))
    assert [(s["gpio"][0], s["gpio_oe"][0]) for s in states] == [(0, 1), (0, 1), (1, 0), (1, 1), (0, 1)]

    states = await matched(dut, imem, assemble("CONFIG open_drain23, 2\nSET 3, 0\nSET 3, 1\nCONFIG open_drain23, 0, 3, 0"))
    assert [(s["gpio"][3], s["gpio_oe"][3]) for s in states] == [(1, 0), (0, 1), (1, 0), (0, 1)]
    assert all(s["gpio_oe"][:3] == [1, 1, 1] for s in states)
    assert all(s["gpio_oe"] == oe(s["gpio"], s["open_drain"]) for s in states)

    # 0x96 LSB first: bit 0 out, then the register turned around MSB first: bit 7 of 0x4B, then of 0x96.
    states = await matched(dut, imem, assemble("PULL\nSHIFT_OUT 1, 0\nCONFIG shift_dir, 1, 1, 1\nSHIFT_OUT 1, 0\nSHIFT_OUT"), tx=(0x96,))
    assert [s["gpio"][0] for s in states] == [1, 0, 0, 0, 1]
    assert [s["gpio"][1] for s in states] == [1, 0, 1, 0, 0]
    assert [s["shift_reg"] for s in states] == [0x96, 0x4B, 0x4B, 0x96, 0x2C]

    # Two 1s in at bit 7 LSB first, then a 1 and a 0 in at bit 0 MSB first.
    program = assemble("SHIFT_IN 2\nSHIFT_IN 2\nCONFIG shift_dir, 1, 2, 0\nSHIFT_IN 2\nSHIFT_IN 2")
    await begin(dut, imem, program, gpio_in=0b0100)
    ls = Lockstep(dut, CPU(program, rx_depth=DEPTH))
    regs = []
    for level in (1, 1, 1, 1, 0):
        ls.pins(level << 2)
        regs.append((await ls.edge())["in_shift_reg"])
    assert ls.cpu.halted and regs == [0x80, 0xC0, 0xC0, 0x81, 0x02]
