"""Adversarial sweep of the ISA and the core's semantics, no protocols.

Three attacks. The exhaustive one walks every 16-bit word: each is either a
valid instruction that survives decode -> encode -> assemble unchanged, or is
rejected on purpose. The random one runs seeded programs against an outside
world that feeds and drains the FIFOs and wiggles the inputs at random, and
checks per-cycle invariants: what a stall, a delay cycle and each operation
may and may not touch. The metamorphic one compares pairs of programs that
must agree: a delay only holds, a side effect only adds one pin, LSB and MSB
first mirror each other, a stall only prepends hold cycles."""

import itertools
import random

import pytest

from cpu import Instruction, assemble, cycles, decode, encode, load_isa
from cpu import CPU as _CPU

ISA = load_isa()


class CPU(_CPU):
    """The simulator on the one ISA loaded above: this bench builds thousands of CPUs."""

    def __init__(self, program, **kwargs):
        super().__init__(program, **{"isa": ISA, **kwargs})


OPS = tuple(ISA["instructions"])
WORD_BITS = ISA["word_bits"]
DELAY_MAX = (1 << ISA["fields"]["delay"]["bits"]) - 1
STATE = ("pc", "gpio", "shift_reg", "in_shift_reg", "shift_dir", "tx_fifo", "rx_fifo", "counter", "halted")


def to_asm(instr):
    """Instruction -> one assembly line, the inverse of assemble() for one word."""
    args = ", ".join(str(a) for a in instr.args + (instr.side or ()))
    return f"{instr.op} {args} [{instr.delay}]"


def every_instruction():
    """Every valid Instruction, enumerated from isa.yaml's operand ranges,
    independently of decode()."""
    side_pins, side_values = [o["bits"] for o in ISA["side_effect"]["operands"]]
    for op, spec in ISA["instructions"].items():
        ranges = [range(1 << o["bits"]) for o in spec["operands"]]
        sides = [None]
        if spec.get("side_effect"):
            sides += [(p, v) for p in range(1 << side_pins) for v in range(1 << side_values)
                      if not (op == "SHIFT_OUT" and p == 0)]
        for args in itertools.product(*ranges):
            if op == "CONFIG":
                field, value = args
                cfg = next((c for c in ISA["config"].values() if c["field"] == field), None)
                if cfg is None or value >> cfg["bits"]:
                    continue
            for side in sides:
                for delay in range(DELAY_MAX + 1):
                    yield Instruction(op, args, delay, side)


INSTRUCTIONS = list(every_instruction())
WORDS = [encode(i, ISA) for i in INSTRUCTIONS]
assert len(WORDS) == len(set(WORDS)), "two instructions encode to one word: the shared opcodes' select bits collide"
VALID = dict(zip(WORDS, INSTRUCTIONS))


# --- Exhaustive: every 16-bit word -------------------------------------------


def test_every_word_decodes_or_is_rejected_deliberately():
    """Each of the 65,536 words is a valid instruction that round-trips through
    encode and the assembler unchanged, or decode raises ValueError. Nothing
    else may happen: no other exception, no silent acceptance."""
    accepted = {}
    for word in range(1 << WORD_BITS):
        try:
            instr = decode(word, ISA)
        except ValueError:
            continue
        accepted[word] = instr
        assert encode(instr, ISA) == word, f"{word:#06x} re-encodes differently"
        assert assemble(to_asm(instr), ISA) == [word], f"{word:#06x}: {to_asm(instr)} assembles differently"
        assert instr.delay == (word >> ISA["fields"]["delay"]["lsb"]) & DELAY_MAX
    assert accepted == VALID, "decode accepts a different set of words than the ISA's operand ranges enumerate"


def test_valid_word_count_per_instruction():
    """The claim, in numbers: 13,312 of 65,536 words mean something."""
    counts = {op: sum(1 for i in VALID.values() if i.op == op) for op in OPS}
    assert counts == {
        "NOP": 32,          # delay only
        "SET": 8 * 32,      # pin x value
        "SHIFT_OUT": 7 * 32,        # no side, or side on pins 1..3 x value
        "SHIFT_IN": 4 * 9 * 32,     # pin x (no side or 4 pins x 2 values)
        "PULL": 9 * 32,
        "PUSH": 9 * 32,
        "JMP": 256 * 32,
        "CONFIG": 2 * 9 * 32,       # shift_dir 0 or 1 x side
        "WAIT": 4 * 2 * 9 * 32,     # pin x level x side
    }
    assert len(VALID) == 13312


def test_words_wider_than_16_bits_are_rejected():
    for word in (1 << WORD_BITS, -1, 1 << 32):
        with pytest.raises(ValueError):
            decode(word, ISA)


def test_unused_opcodes_are_rejected_whatever_the_operand_bits():
    used = {spec["opcode"] for spec in ISA["instructions"].values()}
    for opcode in range(1 << ISA["fields"]["opcode"]["bits"]):
        if opcode in used:
            continue
        for low in (0x0000, 0x1FFF, 0x0080, 0x1F00, 0x00FF):
            assert (opcode << 13 | low) not in VALID


def test_every_instruction_has_every_delay():
    valid = set(VALID.values())
    for instr in VALID.values():
        assert all(instr._replace(delay=d) in valid for d in (0, DELAY_MAX))


# --- Random walk under invariants --------------------------------------------


def snapshot(cpu):
    return {
        "pc": cpu.pc, "gpio": list(cpu.gpio), "shift_reg": cpu.shift_reg, "in_shift_reg": cpu.in_shift_reg,
        "shift_dir": cpu.shift_dir, "tx_fifo": list(cpu.tx_fifo), "rx_fifo": list(cpu.rx_fifo),
        "counter": cpu.counter, "halted": cpu.halted,
    }


def checked_step(cpu):
    """One cpu.step() under the ISA's invariants. Returns 'stall', 'issue' or 'hold'."""
    before = snapshot(cpu)
    gpio_in = list(cpu.gpio_in)
    instr = decode(cpu.program[cpu.pc], cpu.isa)
    cycle, n_trace = cpu.cycle, len(cpu.trace)
    cpu.step()
    after = snapshot(cpu)
    changed = {k for k in STATE if before[k] != after[k]}

    # Every cycle: the clock ticks once, the trace records the pins once, and every value stays in range.
    assert cpu.cycle == cycle + 1 and len(cpu.trace) == n_trace + 1
    assert cpu.trace[-1] == tuple(after["gpio"])
    assert all(level in (0, 1) for level in after["gpio"])
    assert 0 <= after["shift_reg"] <= 0xFF and 0 <= after["in_shift_reg"] <= 0xFF
    assert after["shift_dir"] in (0, 1)
    assert len(after["rx_fifo"]) <= cpu.rx_depth

    stalling = before["counter"] == 0 and (
        (instr.op == "PULL" and not before["tx_fifo"]) or (instr.op == "PUSH" and len(before["rx_fifo"]) >= cpu.rx_depth)
        or (instr.op == "WAIT" and gpio_in[instr.args[0]] != instr.args[1])
    )
    if stalling:
        # Stall: nothing architectural moves, the pins hold, the pc stays on the PULL / PUSH / WAIT.
        assert cpu.stalled
        assert changed == set(), f"stalled {instr.op} changed {changed}"
        return "stall"

    assert not cpu.stalled
    if before["counter"] == 0:
        # Issue cycle: the operation and the pin write land, both on this edge, nothing else.
        expected = dict(before, gpio=list(before["gpio"]), tx_fifo=list(before["tx_fifo"]), rx_fifo=list(before["rx_fifo"]))
        if instr.op == "SHIFT_OUT":
            reg = before["shift_reg"]
            if before["shift_dir"] == 0:
                expected["gpio"][0], expected["shift_reg"] = reg & 1, reg >> 1
            else:
                expected["gpio"][0], expected["shift_reg"] = reg >> 7, (reg << 1) & 0xFF
        elif instr.op == "SHIFT_IN":
            bit = gpio_in[instr.args[0]]  # what the pin held before this edge
            reg = before["in_shift_reg"]
            expected["in_shift_reg"] = (reg >> 1) | (bit << 7) if before["shift_dir"] == 0 else ((reg << 1) & 0xFF) | bit
        elif instr.op == "PULL":
            expected["shift_reg"] = before["tx_fifo"][0]
            expected["tx_fifo"] = before["tx_fifo"][1:]
        elif instr.op == "PUSH":
            expected["rx_fifo"] = before["rx_fifo"] + [before["in_shift_reg"]]
        elif instr.op == "CONFIG":
            field, value = instr.args
            if field == ISA["config"]["shift_dir"]["field"]:
                expected["shift_dir"] = value
        pin_write = instr.args if instr.op == "SET" else instr.side
        if pin_write is not None:
            pin, value = pin_write
            expected["gpio"][pin] = value
        expected["counter"] = instr.delay
        kind = "issue"
    else:
        # Hold cycle: the operation does not happen again, only the counter moves.
        expected = dict(before, counter=before["counter"] - 1)
        assert changed <= {"counter", "pc", "halted"}, f"hold cycle of {instr.op} changed {changed}"
        kind = "hold"
    if expected["counter"] == 0:
        # Last cycle: the pc moves, JMP to its target and everything else to the next word.
        expected["pc"] = instr.args[0] if instr.op == "JMP" else before["pc"] + 1
        expected["halted"] = expected["pc"] >= len(cpu.program)
    assert after == expected, f"{kind} cycle of {to_asm(instr)}: {after} != {expected}"
    assert cpu.counter == expected["counter"]
    return kind


def random_instruction(rng, n_words):
    op = rng.choice(OPS)
    spec = ISA["instructions"][op]
    delay = rng.choice((0, 0, 0, 1, 2, 3, DELAY_MAX))
    if op == "JMP":
        return Instruction(op, (rng.randrange(n_words + 1),), delay)  # n_words is the halt address
    if op == "CONFIG":
        args = (ISA["config"]["shift_dir"]["field"], rng.randrange(2))
    else:
        args = tuple(rng.randrange(1 << o["bits"]) for o in spec["operands"])
    side = None
    if spec.get("side_effect") and rng.random() < 0.5:
        side = (rng.choice((1, 2, 3)) if op == "SHIFT_OUT" else rng.randrange(4), rng.randrange(2))
    return Instruction(op, args, delay, side)


def random_program(rng):
    n = rng.randrange(2, 12)
    return [encode(random_instruction(rng, n), ISA) for _ in range(n)]


def outside_world(rng, cpu, tx_max=6):
    """One cycle of the environment: bytes arrive, bytes leave, inputs move."""
    if len(cpu.tx_fifo) < tx_max and rng.random() < 0.3:
        cpu.tx_fifo.append(rng.randrange(256))
    if cpu.rx_fifo and rng.random() < 0.3:
        cpu.rx_fifo.pop(0)
    for pin in range(len(cpu.gpio_in)):
        cpu.gpio_in[pin] = rng.randrange(2)


@pytest.mark.parametrize("seed", range(300))
def test_random_program_under_invariants(seed):
    rng = random.Random(seed)
    program = random_program(rng)
    cpu = CPU(program, gpio=rng.randrange(2), gpio_in=rng.randrange(2), rx_depth=rng.randrange(1, 5))
    assert all(w in VALID for w in program)
    kinds = set()
    for _ in range(300):
        if cpu.halted:
            break
        outside_world(rng, cpu)
        kinds.add(checked_step(cpu))
    assert kinds <= {"stall", "issue", "hold"}


def test_random_walk_reaches_every_kind_of_cycle():
    """The sweep is only worth something if the programs actually stall, hold and halt."""
    kinds, halted, ops = set(), 0, set()
    for seed in range(300):
        rng = random.Random(seed)
        program = random_program(rng)
        cpu = CPU(program, gpio=rng.randrange(2), gpio_in=rng.randrange(2), rx_depth=rng.randrange(1, 5))
        ops |= {decode(w, ISA).op for w in program}
        for _ in range(300):
            if cpu.halted:
                halted += 1
                break
            outside_world(rng, cpu)
            kinds.add((decode(program[cpu.pc], ISA).op, checked_step(cpu)))
    assert ops == set(OPS)
    assert {k for _, k in kinds} == {"stall", "issue", "hold"}
    assert {op for op, k in kinds if k == "stall"} == {"PULL", "PUSH", "WAIT"}
    assert {op for op, k in kinds if k == "hold"} == set(OPS)
    assert 50 < halted < 300


def test_reset_state():
    for gpio, gpio_in in itertools.product((0, 1), (0, 1)):
        cpu = CPU([0x0000], gpio=gpio, gpio_in=gpio_in)
        assert snapshot(cpu) == {
            "pc": 0, "gpio": [gpio] * 4, "shift_reg": 0, "in_shift_reg": 0, "shift_dir": 0,
            "tx_fifo": [], "rx_fifo": [], "counter": 0, "halted": False,
        }
        assert (cpu.gpio_in, cpu.cycle, cpu.stalled, cpu.trace) == ([gpio_in] * 4, 0, False, [])
    assert CPU([]).halted


# --- Metamorphic pairs -------------------------------------------------------


def fresh(word, rng, program=None):
    """A CPU on `word` alone (or `program`) in a random but stall-free state."""
    cpu = CPU(program or [word], gpio=rng.randrange(2), gpio_in=rng.randrange(2), rx_depth=4)
    cpu.shift_reg, cpu.in_shift_reg, cpu.shift_dir = rng.randrange(256), rng.randrange(256), rng.randrange(2)
    cpu.gpio = [rng.randrange(2) for _ in cpu.gpio]
    cpu.gpio_in = [rng.randrange(2) for _ in cpu.gpio_in]
    cpu.tx_fifo = [rng.randrange(256) for _ in range(rng.randrange(1, 4))]
    cpu.rx_fifo = [rng.randrange(256) for _ in range(rng.randrange(0, 4))]
    if word is not None and VALID[word].op == "WAIT":
        pin, level = VALID[word].args
        cpu.gpio_in[pin] = level  # the level is already there: no stall
    return cpu


def state(cpu):
    return {k: v for k, v in snapshot(cpu).items() if k != "counter"}


BASE = sorted(w for w, i in VALID.items() if i.delay == 0)


@pytest.mark.parametrize("word", BASE, ids=lambda w: to_asm(VALID[w]).replace(" ", "").replace(",", "_"))
def test_a_delay_only_holds_the_state_the_first_cycle_produced(word):
    """`X [31]` performs exactly X's mutation on its first cycle, then holds
    that state 31 cycles longer. Same for every delay in between."""
    rng = random.Random(word)
    for delay in (1, 7, DELAY_MAX):
        for _ in range(2):
            seed = rng.random()
            quick = fresh(word, random.Random(seed))
            slow = fresh(encode(VALID[word]._replace(delay=delay), ISA), random.Random(seed))
            assert state(quick) == state(slow)
            quick.step()
            slow.step()
            held = state(slow)
            assert {k: v for k, v in state(quick).items() if k not in ("pc", "halted")} == \
                   {k: v for k, v in held.items() if k not in ("pc", "halted")}
            assert (slow.pc, slow.halted) == (0, False)  # still on the instruction
            for _ in range(delay):
                slow.step()
                assert {k: v for k, v in state(slow).items() if k not in ("pc", "halted")} == \
                       {k: v for k, v in held.items() if k not in ("pc", "halted")}
            assert state(slow) == state(quick)
            assert slow.trace == [quick.trace[0]] * (delay + 1)


WITH_SIDE = sorted(w for w, i in VALID.items() if i.delay == 0 and i.side is not None) + \
            sorted(w for w, i in VALID.items() if i.delay == 0 and i.op == "SET")


def strip_side(instr):
    if instr.op == "SET":
        return Instruction("NOP", (), instr.delay), instr.args
    return instr._replace(side=None), instr.side


@pytest.mark.parametrize("word", WITH_SIDE, ids=lambda w: to_asm(VALID[w]).replace(" ", "").replace(",", "_"))
def test_a_side_effect_changes_exactly_one_pin_and_nothing_else(word):
    """`SHIFT_IN 3, 1, 0` leaves in_shift_reg exactly as `SHIFT_IN 3` would
    and differs only in gpio[1]. SET is NOP plus the pin. And the pin the
    side effect drives is the only pin that may differ."""
    bare, (pin, value) = strip_side(VALID[word])
    rng = random.Random(word)
    for _ in range(4):
        seed = rng.random()
        plain = fresh(encode(bare, ISA), random.Random(seed))
        side = fresh(word, random.Random(seed))
        for _ in range(cycles(bare)):
            plain.step()
            side.step()
        expected = state(plain)
        expected["gpio"][pin] = value
        assert state(side) == expected
        assert side.halted and plain.halted


@pytest.mark.parametrize("byte", range(256), ids=lambda b: f"{b:#04x}")
def test_shift_out_lsb_first_mirrors_msb_first_of_the_reversed_byte(byte):
    reverse = int(f"{byte:08b}"[::-1], 2)
    lsb = CPU(assemble("CONFIG shift_dir, 0\nPULL\n" + "SHIFT_OUT\n" * 8), tx_data=[byte])
    msb = CPU(assemble("CONFIG shift_dir, 1\nPULL\n" + "SHIFT_OUT\n" * 8), tx_data=[reverse])
    lsb.run()
    msb.run()
    assert lsb.pin_trace(0) == msb.pin_trace(0) == [1, 1] + [(byte >> i) & 1 for i in range(8)]
    assert lsb.shift_reg == msb.shift_reg == 0, "eight shifts empty the register either way"


@pytest.mark.parametrize("byte", range(256), ids=lambda b: f"{b:#04x}")
def test_shift_in_lsb_first_mirrors_msb_first_into_the_reversed_byte(byte):
    """The same eight levels on the wire land as `byte` LSB first and as its
    bit reversal MSB first."""
    wire = [(byte >> i) & 1 for i in range(8)]
    results = []
    for shift_dir in (0, 1):
        cpu = CPU(assemble(f"CONFIG shift_dir, {shift_dir}\n" + "SHIFT_IN 2\n" * 8))
        cpu.step()
        for bit in wire:
            cpu.gpio_in[2] = bit
            cpu.step()
        assert cpu.halted and cpu.gpio == [1, 1, 1, 1] and cpu.shift_reg == 0
        results.append(cpu.in_shift_reg)
    assert results == [byte, int(f"{byte:08b}"[::-1], 2)]


@pytest.mark.parametrize("op", ("PULL", "PUSH", "WAIT"))
@pytest.mark.parametrize("stall", (1, 3, 17))
def test_a_stall_only_prepends_hold_cycles(op, stall):
    """A PULL whose byte arrives after k stall cycles ends in the same state,
    with the same trace after k copies of the held pins, as one whose byte was
    there from the start. Same for PUSH and the room it waits for, and for
    WAIT and the level it waits for."""
    line = {"PULL": "PULL 2, 0 [2]", "PUSH": "PUSH 2, 0 [2]", "WAIT": "WAIT 3, 1, 2, 0 [2]"}[op]
    program = assemble(f"SET 1, 0\n{line}\nSHIFT_OUT 3, 1\nSHIFT_IN 0")
    prompt, late = CPU(program, rx_depth=1), CPU(program, rx_depth=1)
    for cpu in (prompt, late):
        cpu.in_shift_reg = 0x5C
        cpu.tx_fifo = [0xA3]
        cpu.gpio_in[3] = 1
    if op == "PULL":
        late.tx_fifo = []  # the byte arrives after the stall
    elif op == "PUSH":
        late.rx_fifo = [0x11]  # the room appears after the stall
    else:
        late.gpio_in[3] = 0  # the level arrives after the stall
    prompt.run_cycles(1)
    late.run_cycles(1 + stall)
    assert late.stalled and late.pc == 1 and late.gpio == [1, 0, 1, 1]
    if op == "PULL":
        late.tx_fifo.append(0xA3)
    elif op == "PUSH":
        late.rx_fifo.pop(0)
    else:
        late.gpio_in[3] = 1
    prompt.run_cycles(3)
    late.run_cycles(3)
    assert not late.stalled and state(prompt) == state(late)
    prompt.run()
    late.run()
    assert prompt.halted and late.halted
    assert late.trace == prompt.trace[:1] + [prompt.trace[0]] * stall + prompt.trace[1:]
    assert state(prompt) == state(late)
    assert late.cycle == prompt.cycle + stall


@pytest.mark.parametrize("delay", (0, 1, 5, DELAY_MAX))
def test_jmp_to_the_next_word_is_a_nop(delay):
    """`JMP 1 [d]` at address 0 is `NOP [d]`: same pins, same state, same
    cycle count, from any machine state. The instruction under test sits at
    the known execution point; only the state around it is random."""
    tail = [encode(Instruction("SET", (3, 0)), ISA), 0x0000]
    rng = random.Random(delay)
    for _ in range(20):
        seed = rng.random()
        nop = fresh(None, random.Random(seed), [encode(Instruction("NOP", (), delay), ISA)] + tail)
        jmp = fresh(None, random.Random(seed), [encode(Instruction("JMP", (1,), delay), ISA)] + tail)
        assert state(nop) == state(jmp)
        nop.step()
        jmp.step()
        assert state(nop) == state(jmp) and (jmp.pc, jmp.halted) == ((1, False) if delay == 0 else (0, False))
        nop.run()
        jmp.run()
        assert nop.trace == jmp.trace and state(nop) == state(jmp) and nop.cycle == jmp.cycle == delay + 3


def test_delays_add_up():
    """`NOP [a]; NOP [b]` is `NOP [a + b + 1]`, and a delayed SET holds like a SET then NOPs."""
    for a, b in ((0, 0), (0, 5), (3, 4), (15, 15)):
        split = CPU(assemble(f"SET 0, 0\nNOP [{a}]\nNOP [{b}]\nSET 0, 1")).run()
        whole = CPU(assemble(f"SET 0, 0\nNOP [{a + b + 1}]\nSET 0, 1")).run()
        assert split == whole
        assert CPU(assemble(f"SET 2, 0 [{a}]\nNOP [{b}]\nSET 0, 1")).run() == \
               CPU(assemble(f"SET 2, 0 [{a + b + 1}]\nSET 0, 1")).run()


def test_config_is_idempotent_and_a_rewrite_of_the_current_value_is_a_nop():
    for value in (0, 1):
        once = CPU(assemble(f"CONFIG shift_dir, {value}\nPULL\nSHIFT_OUT\nSHIFT_IN 1"), tx_data=[0xA5], gpio_in=1)
        twice = CPU(assemble(f"CONFIG shift_dir, {value}\nCONFIG shift_dir, {value}\nPULL\nSHIFT_OUT\nSHIFT_IN 1"),
                    tx_data=[0xA5], gpio_in=1)
        once.run()
        twice.run()
        assert state(once) == {**state(twice), "pc": once.pc}
        assert twice.trace == once.trace[:1] + once.trace
        # Rewriting the reset value is a NOP.
        nop = CPU(assemble("PULL\nNOP\nSHIFT_OUT"), tx_data=[0x81]).run()
        rewrite = CPU(assemble("PULL\nCONFIG shift_dir, 0\nSHIFT_OUT"), tx_data=[0x81]).run()
        assert nop == rewrite


def test_push_repeats_the_same_byte_and_pull_never_touches_the_input_side():
    cpu = CPU(assemble("SHIFT_IN 0\nPUSH\nPUSH\nPULL\nPUSH"), gpio_in=1, tx_data=[0x3C])
    cpu.run()
    assert cpu.rx_fifo == [0x80, 0x80, 0x80]
    assert (cpu.in_shift_reg, cpu.shift_reg) == (0x80, 0x3C)


def test_shift_out_and_shift_in_never_see_each_others_register():
    """A random interleaving of both shifters: the output register only ever
    loses bits at the wire end, the input register only ever gains them."""
    rng = random.Random(7)
    for _ in range(50):
        cpu = CPU([encode(random_instruction(rng, 0)._replace(delay=0), ISA) for _ in range(20)],
                  gpio_in=rng.randrange(2))
        cpu.tx_fifo = [rng.randrange(256) for _ in range(20)]
        cpu.shift_dir = rng.randrange(2)
        while not cpu.halted:
            op = decode(cpu.program[cpu.pc], ISA).op
            if op == "JMP":
                break
            before = snapshot(cpu)
            cpu.gpio_in = [rng.randrange(2) for _ in cpu.gpio_in]
            if cpu.rx_fifo:
                cpu.rx_fifo.pop(0)
            cpu.step()
            if op in ("SHIFT_OUT", "PULL"):
                assert cpu.in_shift_reg == before["in_shift_reg"]
            if op in ("SHIFT_IN", "PUSH"):
                assert cpu.shift_reg == before["shift_reg"]
            if op == "SHIFT_OUT" and cpu.shift_dir == 0:
                assert cpu.shift_reg == before["shift_reg"] >> 1
            if op == "SHIFT_OUT" and cpu.shift_dir == 1:
                assert cpu.shift_reg == (before["shift_reg"] << 1) & 0xFF
            if op in ("SET", "NOP", "CONFIG", "JMP", "WAIT"):
                assert (cpu.shift_reg, cpu.in_shift_reg) == (before["shift_reg"], before["in_shift_reg"])


# --- What an input pin can reach ---------------------------------------------


def control_trace(program, fifo_seed, pin_seed, cycles=400):
    """(pc, counter, stalled, gpio) per cycle under FIFO traffic from one seed
    and input levels from another: everything but the input side."""
    fifo_rng, pin_rng = random.Random(fifo_seed), random.Random(pin_seed)
    cpu = CPU(program, gpio=1)
    trace = []
    while not cpu.halted and cpu.cycle < cycles:
        if len(cpu.tx_fifo) < 6 and fifo_rng.random() < 0.3:
            cpu.tx_fifo.append(fifo_rng.randrange(256))
        if cpu.rx_fifo and fifo_rng.random() < 0.3:
            cpu.rx_fifo.pop(0)
        cpu.gpio_in = [pin_rng.randrange(2) for _ in cpu.gpio_in]
        cpu.step()
        trace.append((cpu.pc, cpu.counter, cpu.stalled, tuple(cpu.gpio)))
    return trace


@pytest.mark.parametrize("seed", range(100))
def test_only_wait_lets_an_input_reach_the_pc_the_counter_or_a_pin(seed):
    """Without a WAIT, the same FIFO traffic under any two input histories
    gives the same pc, counter, stalls and output pins, cycle for cycle: an
    input reaches in_shift_reg and the RX FIFO, nothing else. A WAIT is the
    one instruction that lets an input hold the machine."""
    rng = random.Random(seed)
    program = [w for w in random_program(rng) if VALID[w].op != "WAIT"] or [0x0000]
    assert control_trace(program, seed, seed + 1) == control_trace(program, seed, seed + 2)
    pin, level = rng.randrange(4), rng.randrange(2)
    held, free = (CPU([encode(Instruction("WAIT", (pin, level), 0), ISA)] + program) for _ in range(2))
    held.gpio_in[pin], free.gpio_in[pin] = 1 - level, level
    held.step()
    free.step()
    assert held.stalled and not free.stalled
