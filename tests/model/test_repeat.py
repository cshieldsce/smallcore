"""REPEAT on the model: opcode 111, `REPEAT count, label`, the counted backward
branch chosen in docs/repeat-candidates.md. The corners pinned there on a
model-only candidate (tests/model/test_repeat_candidates.py, candidate A) are pinned
here on model/cpu.py itself, with the assembler's rules.

Two oracles. `unroll` is what a REPEAT program means as a program for the ISA
without REPEAT: each body count times over, a NOP after each for the REPEAT's
cycle. `lockstep` runs two CPUs under one random outside world, the same pins
every cycle, the same bytes into the TX FIFO at random moments, the same pops
of the RX FIFO, and fails on the first cycle the pins, the pads, the stall or
a FIFO differ. The other oracle is a canonical program where a variant of it
with REPEAT exists: experiments/repeat/<program>_A.asm against
programs/<program>.asm for the ROM's eleven, and the SWD variants against
swd_read.asm and swd_write.asm on the SWD bench, a target and a host on the
wire. The canonical programs stay as they are: they are the evidence."""

import random
import sys
from pathlib import Path

import pytest

from cpu import CPU, Instruction, assemble, decode, encode, load_isa, load_program
from test_swd import DATA, DP_READ, DP_WRITE, FAULT, OK, PROGRAMS, READ, WAIT, WRITE, SlowHost, Target, Wire, rising_edges

ROOT = Path(__file__).resolve().parent.parent.parent
VARIANTS = ROOT / "experiments" / "repeat"
ISA = load_isa()
COUNT_MAX = 1 << ISA["fields"]["delay"]["bits"]
BACK_MAX = (1 << next(o["bits"] for o in ISA["instructions"]["REPEAT"]["operands"])) - 1


def unroll(words, isa=ISA):
    """A REPEAT program as a program without REPEAT: each body count times
    over, a NOP after each for the REPEAT's cycle. Bodies must hold no JMP:
    the addresses move."""
    out = []
    for word in words:
        instr = decode(word, isa)
        if instr.op == "REPEAT":
            back, count = instr.args[0], instr.delay + 1
            body = out[-back:]
            out.append(0)
            for _ in range(count - 1):
                out.extend(body + [0])
        else:
            out.append(word)
    return out


def lockstep(a, b, seed, cycles=4000, feed=0.05, pop=0.3):
    """Step `a` and `b` together under one random outside world; return the
    cycles `a` stalled on. Fails on the first cycle they differ."""
    rng = random.Random(seed)
    stalls = []
    for _ in range(cycles):
        if a.halted or b.halted:
            break
        pins = [rng.randrange(2) for _ in range(4)]
        a.gpio_in, b.gpio_in = list(pins), list(pins)
        if rng.random() < feed:
            byte = rng.randrange(256)
            a.tx_fifo.append(byte)
            b.tx_fifo.append(byte)
        if rng.random() < pop and a.rx_fifo and b.rx_fifo:
            a.rx_fifo.pop(0)
            b.rx_fifo.pop(0)
        a.step()
        b.step()
        assert (a.gpio, a.gpio_oe, a.stalled, a.rx_fifo, a.tx_fifo) == (b.gpio, b.gpio_oe, b.stalled, b.rx_fifo, b.tx_fifo), f"cycle {a.cycle}"
        if a.stalled:
            stalls.append(a.cycle)
    assert a.halted == b.halted and a.cycle == b.cycle
    return stalls


def against_unrolled(source, seeds=10, **kw):
    words = assemble(source)
    for seed in range(seeds):
        lockstep(CPU(words), CPU(unroll(words)), seed, **kw)
    return words


# --- The word and the cycle ------------------------------------------------------------------

BYTE = "        PULL\nbit:    SHIFT_OUT 1, 0 [1]\n        SET 1, 1\n        REPEAT 8, bit\n        SET 1, 0"


def test_repeat_runs_the_body_count_times_in_one_cycle_each():
    """A UART-shaped byte: a PULL, then a two-word cell, the shift with its
    clock down and the clock up, eight times over, then the clock down. 34
    cycles: the PULL, eight cells of 2 + 1 + 1 with the REPEAT's own cycle,
    and the SET. 0x96 LSB first on pin 0, held 4 cycles a bit; the clock on
    pin 1, low 2 high 2."""
    cpu = CPU(assemble(BYTE), tx_data=[0x96])
    cpu.run()
    assert cpu.cycle == 1 + 8 * 4 + 1 and cpu.halted and cpu.rc == 0
    bits = [(0x96 >> i) & 1 for i in range(8)]
    assert cpu.pin_trace(0) == [1] + [b for b in bits for _ in range(4)] + [1]
    assert cpu.pin_trace(1) == [1] + [0, 0, 1, 1] * 8 + [0]


def test_the_word_holds_count_less_one_where_the_delay_goes_and_the_distance_back():
    """`REPEAT 8, bit` at address 3 with bit at 1: opcode 111, 7 in bits
    12:8, 2 in the operand byte. The assembler writes the distance; the
    Instruction carries it, count - 1 in `delay`."""
    words = assemble(BYTE)
    assert words[3] == 0b111_00111_00000010 == 0xE702
    assert decode(words[3], ISA) == Instruction("REPEAT", (2,), 7, None)
    assert encode(Instruction("REPEAT", (255,), 31), ISA) == 0xFFFF
    assert decode(0xE001, ISA) == Instruction("REPEAT", (1,), 0, None)


def test_rc_is_the_runs_still_to_go_and_moves_on_the_repeats_cycle_only():
    """A two-word body, the first with a delay, three times. (pc, rc) after
    every cycle: rc is 0 until the first REPEAT commits, then 2, 1, 0, the
    runs still to go; it never moves on a body word's cycle or a delay's."""
    cpu = CPU(assemble("bit:    SET 0, 0 [1]\n        SET 0, 1\n        REPEAT 3, bit\n        SET 1, 0"))
    seen = []
    while not cpu.halted:
        cpu.step()
        seen.append((cpu.pc, cpu.rc))
    assert seen == [(0, 0), (1, 0), (2, 0), (0, 2),
                    (0, 2), (1, 2), (2, 2), (0, 1),
                    (0, 1), (1, 1), (2, 1), (3, 0),
                    (4, 0)]


@pytest.mark.parametrize("count", (1, 2, 32))
def test_count_1_to_32_encoded_as_count_less_one(count):
    """`REPEAT count, label` runs the body count times, 1..32, the word
    holding count - 1 in bits 12:8: 32 in five bits with no rule about
    zero. Against the unrolled program, under ten outside worlds."""
    source = f"        PULL\nbit:    SHIFT_OUT 1, 0 [1]\n        SET 1, 1\n        REPEAT {count}, bit\n        SET 1, 0"
    words = against_unrolled(source)
    assert decode(words[3], ISA) == ("REPEAT", (2,), count - 1, None)
    assert len(unroll(words)) == 1 + 3 * count + 1, "a PULL, then the two-word body and a NOP count times, then a SET"


def test_count_1_is_one_run_and_no_branch():
    cpu = CPU(assemble("bit:    SET 0, 0\n        REPEAT 1, bit\n        SET 0, 1"))
    cpu.run()
    assert cpu.pin_trace(0) == [0, 0, 1] and cpu.cycle == 3


def test_the_shortest_body_is_one_word():
    words = against_unrolled("        PULL\nbit:    SHIFT_OUT [2]\n        REPEAT 8, bit\n        SET 0, 1")
    assert decode(words[2], ISA).args == (1,)


def test_the_longest_body_is_255_words_and_256_is_refused():
    """255 back is the operand byte's reach; with the REPEAT the program is
    256 words, the memory. One more word of body is refused."""
    lines = [f"        SET {i % 4}, {i % 2} [{i % 3}]" for i in range(256)]
    source = "start:" + "\n".join(lines[:255])[6:] + "\n        REPEAT 3, start"
    words = against_unrolled(source, seeds=3, cycles=3000)
    assert len(words) == 256 and decode(words[-1], ISA).args == (BACK_MAX,)
    longer = "start:" + "\n".join(lines)[6:] + "\n        REPEAT 3, start"
    with pytest.raises(SyntaxError, match="256 words back"):
        assemble(longer)


def test_the_label_may_be_an_address_as_jmps_target_may():
    assert assemble("SET 0, 0\nSET 0, 1\nREPEAT 4, 0") == assemble("a: SET 0, 0\nSET 0, 1\nREPEAT 4, a")
    assert decode(assemble("SET 0, 0\nSET 0, 1\nREPEAT 4, 0")[-1], ISA) == Instruction("REPEAT", (2,), 3)


# --- The assembler's rules -------------------------------------------------------------------


@pytest.mark.parametrize("bad, message", [
    ("bit:    SET 0, 0\n        REPEAT 0, bit", "count 0"),
    ("bit:    SET 0, 0\n        REPEAT 33, bit", "count 33"),
    ("bit:    SET 0, 0\n        REPEAT bit, bit", "not a number"),
    ("        REPEAT 2, ahead\nahead:  SET 0, 0", "words back"),
    ("self:   REPEAT 2, self", "0 words back"),
    ("        SET 0, 0\n        REPEAT 2, nowhere", "unknown label"),
    ("bit:    SET 0, 0\n        REPEAT 2, bit [1]", "takes no delay"),
    ("bit:    SET 0, 0\n        REPEAT 2, bit, 1, 0", "takes a count and a label"),
    ("bit:    SET 0, 0\n        REPEAT bit", "takes a count and a label"),
    ("bit:    SET 0, 0\n        REPEAT 2, bit\n        REPEAT 2, bit", "inside its body"),
    ("outer:  SET 0, 0\ninner:  SET 0, 1\n        REPEAT 2, inner\n        REPEAT 2, outer", "inside its body"),
    ("bit:    SET 0, 0\n        JMP out\n        REPEAT 2, bit\nout:    SET 0, 1", "leaves the body"),
    ("bit:    SET 0, 0\n        SKIP 0, 0\n        REPEAT 2, bit\n        SET 0, 1", "last word is a SKIP"),
    ("        JMP in\nbit:    SET 0, 0\nin:     SET 0, 1\n        REPEAT 2, bit", "lands inside the body"),
    ("        JMP on\nbit:    SET 0, 0\n        SET 0, 1\non:     REPEAT 2, bit", "lands inside the body"),
    ("        SKIP 0, 0\nbit:    SET 0, 0\n        SET 0, 1\n        REPEAT 2, bit", "steps into the body"),
])
def test_the_assembler_refuses_what_the_hardware_would_do_something_odd_with(bad, message):
    """The control-flow corners are closed by the assembler, not by
    machinery: a count outside 1..32, a label ahead or on the REPEAT itself,
    a delay or a side effect on the REPEAT, a REPEAT inside a body, a JMP out
    of a body, a SKIP as the body's last word, a JMP or SKIP into a body past
    its label, the REPEAT itself included."""
    with pytest.raises(SyntaxError, match=message):
        assemble(bad)


def test_what_the_assembler_allows_around_a_body():
    """A SKIP just before the label landing on it; two bodies one after the
    other; a JMP in a body landing on its label or on its REPEAT: allowed,
    and the first two run as unrolled."""
    against_unrolled("        SKIP 0, 0\n        SET 0, 1\nbit:    SET 0, 0\n        SET 1, 1\n        REPEAT 3, bit\n"
                     "two:    SET 2, 0\n        SET 2, 1\n        REPEAT 2, two\n        SET 3, 0", seeds=5)
    assemble("bit:    SET 0, 0\n        SHIFT_IN 0\n        SKIP 7, 1\n        JMP bit\n        SET 0, 1\n        REPEAT 2, bit")
    assemble("bit:    SET 0, 0\n        SHIFT_IN 0\n        SKIP 7, 1\n        JMP on\n        SET 0, 1\non:     REPEAT 2, bit")


def test_entering_at_the_label_from_outside_is_the_ordinary_entry():
    """The SWD retry's shape: a loop finishes, a JMP from after it lands on
    its label, and the loop runs its full count again, rc being 0 since the
    first loop finished. Three runs of the body, a sample of pin 0 deciding
    whether to go round again, three more, done: six pulses on pin 0, 14
    cycles for the first pass and 13 for the second, the SKIP taken."""
    source = ("        SET 2, 0\nreq:    SET 0, 0\n        SET 0, 1\n        REPEAT 3, req\n        SET 2, 1\n"
              "        SHIFT_IN 0\n        SKIP 7, 1\n        JMP req\n        SET 3, 0")
    cpu = CPU(assemble(source))
    cpu.gpio_in[0] = 0
    cpu.run_cycles(14)  # the first pass, the sample a 0: back to req
    assert (cpu.pc, cpu.rc) == (1, 0)
    cpu.gpio_in[0] = 1
    cpu.run()
    assert cpu.cycle == 27 and cpu.gpio == [1, 1, 1, 0]
    trace = cpu.pin_trace(0)
    assert sum(1 for a, b in zip(trace, trace[1:]) if (a, b) == (0, 1)) == 6


# --- Stalls, restart, reset ------------------------------------------------------------------


def test_a_stall_on_the_bodys_first_and_last_word_leaves_the_count_alone():
    """The body starts with a PULL and ends with a PUSH, the outside world
    handing over a byte only once the FIFO is empty and slow to pop: both
    stall, again and again over 32 iterations, and the run is the unrolled
    program's. rc is watched: it changes only on the REPEAT's cycle, never
    during a stall or a delay."""
    words = assemble("byte:   PULL 1, 0 [1]\n        SHIFT_OUT 1, 1 [1]\n        SHIFT_IN 0 [1]\n        PUSH 1, 0\n        REPEAT 32, byte\n        SET 2, 0")
    cpu, ref = CPU(words), CPU(unroll(words))
    rng = random.Random(3)
    seen, first, last = [], 0, 0
    while not cpu.halted and cpu.cycle < 8000:
        pins = [rng.randrange(2) for _ in range(4)]
        cpu.gpio_in, ref.gpio_in = list(pins), list(pins)
        if not cpu.tx_fifo and rng.random() < 0.05:
            byte = rng.randrange(256)
            cpu.tx_fifo.append(byte)
            ref.tx_fifo.append(byte)
        if rng.random() < 0.02 and cpu.rx_fifo and ref.rx_fifo:
            cpu.rx_fifo.pop(0)
            ref.rx_fifo.pop(0)
        at = decode(cpu.program[cpu.pc], ISA).op
        rc_before = cpu.rc
        cpu.step()
        ref.step()
        assert (cpu.gpio, cpu.gpio_oe, cpu.stalled, cpu.rx_fifo, cpu.tx_fifo) == (ref.gpio, ref.gpio_oe, ref.stalled, ref.rx_fifo, ref.tx_fifo), f"cycle {cpu.cycle}"
        if cpu.stalled:
            first += at == "PULL"
            last += at == "PUSH"
            assert cpu.rc == rc_before, "rc moved during a stall"
        elif at != "REPEAT":
            assert cpu.rc == rc_before, f"rc moved on a {at}"
        seen.append(cpu.rc)
    assert cpu.halted and ref.halted
    assert first > 100 and last > 100, f"stalls on the first word {first}, on the last {last}"
    assert sorted(set(seen)) == list(range(32))


def test_restart_in_every_cycle_of_a_loop_starts_clean_and_a_slot_change_too():
    """At every cycle t of a run, restart: the core back to reset, rc 0, the
    FIFOs kept, and the run from there is a fresh run with those FIFOs. And
    at every t, a slot change to another program: a fresh run of that one."""
    words = assemble("        PULL\nbit:    SHIFT_OUT 1, 0 [2]\n        SET 1, 1 [1]\n        REPEAT 4, bit\n        SET 1, 0")
    other = assemble("        SET 3, 0 [2]\nbit:    SHIFT_OUT [1]\n        REPEAT 3, bit\n        SET 3, 1")
    whole = CPU(words, tx_data=[0x96])
    whole.run()
    total = whole.cycle
    for t in range(1, total):
        for program in (None, other):
            cpu = CPU(words, tx_data=[0x96, 0x53])
            cpu.run_cycles(t)
            cpu.restart(program)
            assert cpu.pc == 0 and cpu.rc == 0 and cpu.counter == 0 and not cpu.stalled and cpu.gpio == [1] * 4 and cpu.cycle == t
            fresh = CPU(words if program is None else program, tx_data=list(cpu.tx_fifo))
            fresh.rx_fifo = list(cpu.rx_fifo)
            cpu.run()
            fresh.run()
            assert cpu.trace[t:] == fresh.trace, f"restart at cycle {t}"
            assert cpu.rx_fifo == fresh.rx_fifo and cpu.cycle - t == fresh.cycle


def test_reset_and_restart_clear_rc_and_a_restart_keeps_the_fifos():
    cpu = CPU(assemble("bit:    PULL\n        PUSH\n        REPEAT 5, bit"), tx_data=[1, 2, 3], gpio_in=1)
    cpu.run_cycles(3)  # PULL, PUSH, REPEAT: rc 4, one byte pulled, one pushed
    assert (cpu.rc, cpu.tx_fifo, cpu.rx_fifo) == (4, [2, 3], [0])
    cpu.restart()
    assert (cpu.rc, cpu.pc, cpu.tx_fifo, cpu.rx_fifo, cpu.gpio_in, cpu.cycle) == (0, 0, [2, 3], [0], [1, 1, 1, 1], 3)
    assert CPU([0xE001]).rc == 0


def test_a_back_past_word_0_wraps_the_nine_bit_pc_past_the_end_and_halts():
    """The assembler never writes one; the hardware's subtract wraps at nine
    bits, so the model does: pc 2 - 5 is 509, past any program, halted, rc
    loaded as any REPEAT loads it."""
    cpu = CPU([0x0000, 0x0000, encode(Instruction("REPEAT", (5,), 2), ISA), 0x0000])
    cpu.run_cycles(3)
    assert (cpu.pc, cpu.rc, cpu.halted) == (509, 2, True)


def test_repeat_has_no_side_effect_bits_to_reserve():
    """Opcode 3, count 5, back 8: sixteen. Nothing left for a side effect,
    nothing to declare reserved: bit 7 is the top of `back`, 0xE080 is
    REPEAT with 128 back, and a side effect written on a REPEAT is refused."""
    spec = ISA["instructions"]["REPEAT"]
    assert not spec.get("side_effect") and spec["operands"] == [{"name": "back", "lsb": 0, "bits": 8, "min": 1}]
    assert decode(0xE080, ISA) == Instruction("REPEAT", (128,), 0, None)
    with pytest.raises(ValueError):
        decode(0xE000, ISA)  # back 0: a REPEAT cannot reach itself
    with pytest.raises(SyntaxError):
        assemble("bit:    SET 0, 0\n        REPEAT 2, bit, 1, 0")


# --- The canonical programs as the oracle ----------------------------------------------------

CANONICAL = {  # programs/<name>.asm words -> experiments/repeat/<name>_A.asm words
    "uart_tx_0x55": (11, 4), "uart_tx_pull": (11, 5), "uart_tx_loop": (12, 6), "uart_rx": (12, 6),
    "spi_tx_lsb": (21, 8), "spi_tx_msb": (21, 8), "spi_duplex_lsb": (22, 9), "spi_duplex_msb": (22, 9),
    "i2c_write": (34, 14), "i2c_write_stretch": (45, 18), "i2c_write_addr_data": (64, 24),
}


@pytest.mark.parametrize("name", sorted(CANONICAL))
def test_every_variant_with_repeat_is_its_canonical_program_under_any_outside_world(name):
    """The ROM's eleven programs with REPEAT spliced in, assembled by the
    assembler and run on the model, each in lockstep with its canonical
    program under ten random outside worlds, agreeing every cycle. UART 11,
    11, 12, 12 to 4, 5, 6, 6; SPI 21 and 22 to 8 and 9; I2C 34, 45, 64 to
    14, 18, 24: 275 words to 111."""
    canonical = load_program(PROGRAMS / name.split("_")[0] / f"{name}.asm")
    variant = load_program(VARIANTS / f"{name}_A.asm")
    assert (len(canonical), len(variant)) == CANONICAL[name]
    assert any(decode(w, ISA).op == "REPEAT" for w in variant)
    for seed in range(10):
        stalls = lockstep(CPU(variant), CPU(canonical), seed, cycles=3000)
        if name == "uart_rx":
            assert stalls, "the receiver never waited for a start bit"
    assert sum(c for c, _ in CANONICAL.values()) == 275 and sum(a for _, a in CANONICAL.values()) == 111


SWD = {"read": (READ, DP_READ, 103), "write": (WRITE, DP_WRITE, 106)}


def swd(kind, target, host=None, drain=True, cycles=3000, variant=True):
    path, request, _ = SWD[kind]
    program = load_program(VARIANTS / f"swd_{kind}_A.asm") if variant else load_program(path)
    cpu = CPU(program, gpio_in=1, tx_data=[request])
    return Wire(None, request, target, drain=drain, host=host, cpu=cpu).go(cycles)


def swd_host(kind, **kw):
    return SlowHost(SWD[kind][1], data=DATA if kind == "write" else None, **kw)


def assert_same_wire(a, b):
    assert a.cpu.halted and b.cpu.halted and a.cpu.cycle == b.cpu.cycle
    assert a.swclk == b.swclk, "SWCLK differs"
    assert a.swdio == b.swdio, "SWDIO differs"
    assert a.owned == b.owned, "who drove SWDIO differs"
    assert (a.driven, a.received) == (b.driven, b.received)
    assert a.target.seen == b.target.seen and a.target.written == b.target.written


class PopsAt:
    """A host that pops one byte at each of the given cycles and never otherwise."""

    def __init__(self, cycles):
        self.cycles = set(cycles)

    def __call__(self, cpu, received):
        if cpu.cycle in self.cycles and cpu.rx_fifo:
            received.append(cpu.rx_fifo.pop(0))


class Watch:
    """A host wrapper that records (stalled, rc) every cycle."""

    def __init__(self, host):
        self.host = host
        self.seen = []

    def __call__(self, cpu, received):
        self.seen.append((cpu.stalled, cpu.rc))
        self.host(cpu, received)


@pytest.mark.parametrize("kind", ("read", "write"))
def test_the_swd_programs_with_repeat_are_the_103_and_106_word_ones_on_the_wire(kind):
    """40 words for 103 and 106. On the SWD bench, cycle for cycle the
    canonical program's wire: a target that says OK with a prompt host (379
    or 384 cycles, 46 rises); WAIT then OK with the host 100 cycles late
    pushing the request again, the retry entering the request loop at its
    label; FAULT; and a stall inside a repeated body with runs of it still to
    go, the read's fifth PUSH with a host that pops only at cycles 500 and
    700, the write's PULL at the top of a data byte with the data queued 300
    cycles late."""
    assert len(load_program(VARIANTS / f"swd_{kind}_A.asm")) == 40 and len(load_program(SWD[kind][0])) == SWD[kind][2]
    stalled_host = (lambda: PopsAt((500, 700))) if kind == "read" else (lambda: swd_host(kind, late=300))
    for acks, host, drain in (
        ([OK], lambda: swd_host(kind), True),
        ([WAIT, OK], lambda: swd_host(kind, delay=100), True),
        ([FAULT], lambda: swd_host(kind), True),
        ([OK], stalled_host, kind == "write"),
    ):
        watch = Watch(host())
        a = swd(kind, Target(acks, DATA), host(), drain, variant=False)
        b = swd(kind, Target(acks, DATA), watch, drain)
        assert_same_wire(a, b)
        if host is stalled_host:
            assert sum(1 for stalled, rc in watch.seen if stalled and rc) > 100, "no stall inside a body with runs to go"
    ok = swd(kind, Target([OK], DATA), swd_host(kind))
    assert ok.cpu.cycle == (379 if kind == "read" else 384) and len(rising_edges(ok.swclk)) == 46
