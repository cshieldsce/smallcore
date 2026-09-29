"""The repeat candidates against the SWD programs: docs/repeat-candidates.md.

SWD's complaint was one thing only: the same two-word bit cell 32 times over,
64 of each program's words. experiments/repeat/candidates.py has four ways to
say "again" as model-only ISA variants, A a counted backward branch, B a
one-word repeat, C a counter with a load and a decrement-and-branch, D a
SHIFT that does eight cells, and the two SWD programs with each spliced in
wherever a body repeats, the loop word's cycle taken from a delay next to it.
programs/swd/swd_read.asm and programs/swd/swd_write.asm, 103 and 106 words, are the
baseline and stay as they are.

What a candidate has to survive here: the baseline's wire cycle for cycle
with a target that says OK, WAIT then OK, or FAULT, with a host late to push
the request again, with a host that reads nothing until the FIFO is full or
queues the data late so a PUSH or PULL stalls inside the repeated body (the
count must not move while the core stands still); a restart in the middle of
a loop; and every existing program assembling to the same words meaning the
same things. The word counts are pinned. tests/model/test_swd.py's Wire, Target and
SlowHost are the bench; the candidate's CPU runs in the model's place."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "experiments" / "repeat"))

from candidates import CANDIDATES, Candidate, assemble as assemble_candidate, load_program as load_candidate  # noqa: E402
from cpu import CPU, assemble, decode, load_isa, load_program  # noqa: E402
from test_swd import (  # noqa: E402
    DATA, DP_READ, DP_WRITE, FAULT, OK, PROGRAMS, READ, WAIT, WRITE, SlowHost, Target, Wire, read_bytes, rising_edges,
)

SPLICED = {"A": (40, 40), "C": (43, 43), "D": (33, 36)}  # words for the read and the write; B has no splice, see below
REQ = {"read": DP_READ, "write": DP_WRITE}
BASE = {"read": READ, "write": WRITE}


def baseline(kind, target, host=None, drain=True, cycles=3000):
    return Wire(BASE[kind], REQ[kind], target, drain=drain, host=host).go(cycles)


def candidate(tag, kind, target, host=None, drain=True, cycles=3000):
    cls = CANDIDATES[tag]
    cpu = cls(load_candidate(f"swd_{kind}_{tag}", cls), gpio_in=1, tx_data=[REQ[kind]])
    return Wire(None, REQ[kind], target, drain=drain, host=host, cpu=cpu).go(cycles)


def host_for(kind, **kw):
    return SlowHost(REQ[kind], data=DATA if kind == "write" else None, **kw)


def assert_same_wire(a, b):
    """Cycle for cycle: the wire, who owned it, what the target drove, SWCLK;
    the same bytes to the host, the same view from the target, the same
    cycle count, both halted."""
    assert a.cpu.halted and b.cpu.halted
    assert a.cpu.cycle == b.cpu.cycle
    assert a.swclk == b.swclk, "SWCLK differs"
    assert a.swdio == b.swdio, "SWDIO differs"
    assert a.owned == b.owned, "who drove SWDIO differs"
    assert a.driven == b.driven
    assert a.received == b.received
    assert a.target.seen == b.target.seen and a.target.written == b.target.written


class PopsAt:
    """A host that pops one byte at each of the given cycles and never otherwise."""

    def __init__(self, cycles):
        self.cycles = set(cycles)

    def __call__(self, cpu, received):
        if cpu.cycle in self.cycles and cpu.rx_fifo:
            received.append(cpu.rx_fifo.pop(0))


class Watch:
    """A host wrapper that records the candidate's own registers every cycle."""

    def __init__(self, host=None):
        self.host = host
        self.states, self.stalls = [], []

    def __call__(self, cpu, received):
        self.states.append(cpu.state())
        self.stalls.append(cpu.stalled)
        if self.host:
            self.host(cpu, received)


@pytest.fixture(params=sorted(SPLICED), ids=lambda t: f"candidate {t}")
def tag(request):
    return request.param


@pytest.fixture(params=("read", "write"))
def kind(request):
    return request.param


# --- the splices, word for word --------------------------------------------------------------


def test_spliced_program_word_counts(tag, kind):
    """The number the comparison is about. Read: A 40, C 43, D 33 for 103.
    Write: A 40, C 43, D 36 for 106."""
    words = load_candidate(f"swd_{kind}_{tag}", CANDIDATES[tag])
    assert len(words) == SPLICED[tag][0 if kind == "read" else 1]
    assert len(load_program(BASE[kind])) == (103 if kind == "read" else 106), "the baseline moved"


def test_b_has_no_one_word_cell_to_repeat_in_swd():
    """B repeats one word. Every cell in the SWD programs is two words, a
    shift and its clock, and no word is followed by itself anywhere, so B
    saves nothing there: 103 and 106 stay 103 and 106."""
    for program in (READ, WRITE):
        words = load_program(program)
        assert all(a != b for a, b in zip(words, words[1:])), "a one-word cell: B could repeat it"


def test_b_and_d_on_the_uart_where_the_cell_is_one_word():
    """For the record, where B does apply: uart_tx_pull.asm's eight SHIFT_OUT
    [7] become REPEAT_NEXT 8 and one, 5 words for 11, the frame the same to
    the cycle. D does the same byte in one word, 4 for 11."""
    base = CPU(load_program(PROGRAMS / "uart" / "uart_tx_pull.asm"), tx_data=[0x96])
    base.run()
    for name, tag, words in (("uart_tx_B", "B", 5), ("uart_tx_D", "D", 4)):
        cls = CANDIDATES[tag]
        program = load_candidate(name, cls)
        assert len(program) == words
        cpu = cls(program, tx_data=[0x96])
        cpu.run()
        assert cpu.trace == base.trace and cpu.cycle == base.cycle


# --- the wire, cycle for cycle ---------------------------------------------------------------


def test_ok_is_the_baseline_cycle_for_cycle(tag, kind):
    """A target that says OK and a prompt host: the same 379 or 384 cycles,
    the same 46 rises, the same wire, the same bytes."""
    a, b = baseline(kind, Target([OK], DATA), host_for(kind)), candidate(tag, kind, Target([OK], DATA), host_for(kind))
    assert_same_wire(a, b)
    assert len(rising_edges(b.swclk)) == 46


def test_wait_then_ok_is_the_baseline(tag, kind):
    """WAIT then OK: the retry goes back through the request loop with the
    count at rest, and everything is as before, 13 + 46 rises."""
    a = baseline(kind, Target([WAIT, OK], DATA), host_for(kind))
    b = candidate(tag, kind, Target([WAIT, OK], DATA), host_for(kind))
    assert_same_wire(a, b)
    assert len(rising_edges(b.swclk)) == 13 + 46


def test_fault_is_the_baseline(tag, kind):
    a, b = baseline(kind, Target([FAULT], DATA), host_for(kind)), candidate(tag, kind, Target([FAULT], DATA), host_for(kind))
    assert_same_wire(a, b)
    assert len(rising_edges(b.swclk)) == 13


def test_a_host_late_with_the_request_again_is_the_baseline(tag, kind):
    """The retry's PULL stalls at the top of the request loop, 100 cycles."""
    a = baseline(kind, Target([WAIT, OK], DATA), host_for(kind, delay=100))
    b = candidate(tag, kind, Target([WAIT, OK], DATA), host_for(kind, delay=100))
    assert_same_wire(a, b)


def test_a_stall_inside_the_repeated_body_leaves_the_count_alone(tag, kind):
    """The strict one. Read: a host that pops only at cycles 500 and 700, so
    the fifth PUSH, the last word of the byte body, stalls with three bytes
    to go on the count. Write: a host that queues data byte 0 on the OK and
    the rest 300 cycles later, so the PULL at the end of the first byte body
    stalls with three bytes to go on the count. Cycle for cycle the baseline;
    and the candidate's own registers do not move while the core stands
    still."""
    if kind == "read":
        a = baseline(kind, Target([OK], DATA), PopsAt((500, 700)), drain=False)
        host = Watch(PopsAt((500, 700)))
        b = candidate(tag, kind, Target([OK], DATA), host, drain=False)
    else:
        a = baseline(kind, Target([OK], DATA), host_for(kind, late=300))
        host = Watch(host_for(kind, late=300))
        b = candidate(tag, kind, Target([OK], DATA), host)
    assert_same_wire(a, b)
    stalled = [i for i, s in enumerate(host.stalls) if s]
    assert len(stalled) > 100, "no stall to speak of"
    runs = []
    for i in stalled:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    for run in runs:
        assert len({host.states[i] for i in run}) == 1, f"the candidate's registers moved during a stall at cycles {run[0]}..{run[-1]}"
    if tag in "AC":
        inside = [run for run in runs if host.states[run[0]][0] != 0]
        assert inside, "no stall happened inside a loop with a count outstanding"


def test_restart_in_the_middle_of_a_loop_starts_clean(tag, kind):
    """The chip's restart: at cycle 200, inside the data loop (a read) or the
    request loop's stall on the retry (a write with WAIT), the core goes back
    to reset with the FIFOs kept. The candidate's registers must too: the run
    from there, with a request pushed again, is a fresh run cycle for cycle."""
    cls = CANDIDATES[tag]
    target = Target([OK], DATA) if kind == "read" else Target([WAIT, OK], DATA)
    w = candidate(tag, kind, target, host_for(kind), cycles=200)
    cpu = w.cpu
    assert not cpu.halted and (cpu.pc != 0 or cpu.stalled)
    if kind == "read":
        assert cpu.state() != tuple(cls(cpu.program).state()), "the read had no loop state at cycle 200: pick another cycle"
    cpu.restart()
    assert cpu.pc == 0 and cpu.counter == 0 and not cpu.stalled and cpu.gpio == [1] * 4
    assert cpu.state() == tuple(cls(cpu.program).state()), "restart left the candidate's registers"
    cpu.tx_fifo.clear()
    cpu.rx_fifo.clear()
    cpu.tx_fifo.append(REQ[kind])
    again = Wire(None, REQ[kind], Target([OK], DATA), host=host_for(kind), cpu=cpu).go(3000)
    fresh = candidate(tag, kind, Target([OK], DATA), host_for(kind))
    assert again.cpu.halted and fresh.cpu.halted
    assert again.cpu.cycle - 200 == fresh.cpu.cycle
    assert again.swdio == fresh.swdio, "SWDIO after the restart differs from a fresh run's"
    assert again.cpu.pin_trace(1)[200:] == fresh.swclk, "SWCLK after the restart differs from a fresh run's"  # the trace is kept across the restart
    assert again.owned == fresh.owned
    assert again.received == fresh.received
    if kind == "read":
        assert again.received == read_bytes(OK, DATA)


# --- the existing programs -------------------------------------------------------------------


@pytest.mark.parametrize("tag", sorted(CANDIDATES), ids=lambda t: f"candidate {t}")
def test_every_existing_program_means_the_same_under_the_candidate(tag):
    """A candidate adds words; it changes none. Every program in programs/
    from before the decision assembles to the same words under the
    candidate's ISA and every word decodes to the same instruction. A program
    written since (can_tx.asm on) uses REPEAT, the opcode the candidates
    were competing for, and is not their business. The candidate's model,
    run as the model, passes the existing suite except the tests that pin
    the free opcode or the spare bit free: experiments/repeat/suite.py."""
    cls = CANDIDATES[tag]
    isa, base = cls.isa(), load_isa()
    for path in sorted(PROGRAMS.rglob("*.asm")):
        source = path.read_text()
        words = assemble(source, base)
        if any(decode(word, base).op == "REPEAT" for word in words):
            continue
        assert assemble_candidate(source, cls) == words, path.name
        for word in words:
            assert decode(word, isa) == decode(word, base), f"{path.name}: {word:#06x}"


def test_the_copied_step_is_the_model():
    """Candidate is cpu.CPU's step written out with hooks; on the baseline
    programs it must be the model to the cycle. Here on the SWD read with
    OK; suite.py runs the whole suite on it."""
    a = baseline("read", Target([OK], DATA), host_for("read"))
    cpu = Candidate(load_program(READ), gpio_in=1, tx_data=[DP_READ])
    b = Wire(None, DP_READ, Target([OK], DATA), host=host_for("read"), cpu=cpu).go(3000)
    assert_same_wire(a, b)


# --- a rule the candidates with a loop word impose ---------------------------------------------


@pytest.mark.parametrize("tag", ("A", "C"), ids=lambda t: f"candidate {t}")
def test_a_loop_word_right_after_a_stalling_word_moves_the_stall_by_a_cycle(tag):
    """Why the write loops start with the PULL. The first splice had the body
    end `SET 1, 1 [1]`, `PULL`, then the loop word, the loop word's cycle
    taken from the SET: a prompt host sees the baseline's wire. A host that
    is late with a byte does not: the PULL stalls a cycle earlier than the
    baseline's, the byte lands when it lands, and the loop word's cycle now
    follows the stall, so SWCLK stays high a cycle longer and the write is
    one cycle longer. With the PULL first in the body and the loop word
    before it, the stall begins and ends as the baseline's. Rule: never take
    a loop word's cycle from the word before a word that can stall."""
    cls = CANDIDATES[tag]
    source = (ROOT / "experiments" / "repeat" / f"swd_write_{tag}.asm").read_text()
    loop = "REPEAT 4, data" if tag == "A" else "DJNZ data"
    code = [line.partition("#")[0].rstrip() for line in source.splitlines()]
    i = code.index("data:   PULL")
    j = next(k for k, line in enumerate(code) if line.strip() == loop)
    assert code[j + 1].strip() == "PULL" and code[j - 1].strip() == "SET 1, 1 [1]"
    code[i] = "data:   PULL"
    code[i + 1] = "byte:   " + code[i + 1].strip()
    code[j], code[j + 1] = "        PULL", "        " + loop.replace("data", "byte")
    first_splice = assemble_candidate("\n".join(code), cls)
    assert len(first_splice) == SPLICED[tag][1]
    for late, longer in ((0, 0), (300, 1)):
        a = baseline("write", Target([OK], DATA), host_for("write", late=late))
        cpu = cls(first_splice, gpio_in=1, tx_data=[DP_WRITE])
        b = Wire(None, DP_WRITE, Target([OK], DATA), host=host_for("write", late=late), cpu=cpu).go(3000)
        assert a.cpu.halted and b.cpu.halted and b.target.written == [(DATA, True)]
        assert b.cpu.cycle - a.cpu.cycle == longer, f"late by {late}: {b.cpu.cycle - a.cpu.cycle} cycles longer"
        if longer:
            assert sum(b.swclk) - sum(a.swclk) == longer, "the extra cycle is SWCLK high"


# --- A alone: the spec's corners, and the other protocols -------------------------------------
#
# The reviewer's last model-only round for A. Two oracles: `A.unroll`, what a
# REPEAT program means as a program for the ISA as it is (each body count
# times, a NOP after each for the REPEAT's cycle), and the canonical program
# itself where a variant of it is spliced. Either is run against the A program
# in lockstep under the same random outside world: the same pins every cycle,
# the same bytes into the TX FIFO at random moments, the same pops of the RX
# FIFO, and every cycle the pins, the pads, the stall and both FIFOs must
# agree, to the halt or for as long as the run goes.

import random  # noqa: E402

A_ = CANDIDATES["A"]


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


def a_program(source, tx=()):
    words = assemble_candidate(source, A_)
    return A_(words, tx_data=list(tx)), words


def unrolled(words, tx=()):
    return CPU(A_.unroll(words), tx_data=list(tx))


CANONICAL = {  # programs/<name>.asm words -> experiments/repeat/<name>_A.asm words
    "uart_tx_0x55": (11, 4), "uart_tx_pull": (11, 5), "uart_tx_loop": (12, 6), "uart_rx": (12, 6),
    "spi_tx_lsb": (21, 8), "spi_tx_msb": (21, 8), "spi_duplex_lsb": (22, 9), "spi_duplex_msb": (22, 9),
    "i2c_write": (34, 14), "i2c_write_stretch": (45, 18), "i2c_write_addr_data": (64, 24),
}


@pytest.mark.parametrize("name", sorted(CANONICAL))
def test_a_on_the_other_protocols_is_the_canonical_program_under_any_outside_world(name):
    """Cross-protocol applicability. REPEAT spliced into every program in the
    ROM's manifest, the canonical program untouched: the variant and the
    canonical run in lockstep under ten random outside worlds and agree every
    cycle. The words: UART 11, 11, 12, 12 to 4, 5, 6, 6; SPI 21 and 22 to 8
    and 9; I²C 34, 45, 64 to 14, 18, 24. The eleven programs: 275 words to
    111."""
    canonical = load_program(PROGRAMS / name.split("_")[0] / f"{name}.asm")
    variant = load_candidate(f"{name}_A", A_)
    assert (len(canonical), len(variant)) == CANONICAL[name]
    for seed in range(10):
        stalls = lockstep(A_(variant), CPU(canonical), seed, cycles=3000)
        if name == "uart_rx":
            assert stalls, "the receiver never waited for a start bit"


def test_the_rom_would_be_275_words_to_111():
    assert sum(c for c, _ in CANONICAL.values()) == 275 and sum(a for _, a in CANONICAL.values()) == 111


@pytest.mark.parametrize("count", (1, 2, 32))
def test_count_1_to_32_encoded_as_count_less_one(count):
    """REPEAT count, label runs the body count times, 1..32, the word holding
    count - 1 in bits 12:8: 32 in five bits with no rule about zero. Against
    the unrolled program, under ten outside worlds."""
    source = f"        PULL\nbit:    SHIFT_OUT 1, 0 [1]\n        SET 1, 1\n        REPEAT {count}, bit\n        SET 1, 0"
    _, words = a_program(source)
    assert decode(words[3], A_.isa()) == ("REPEAT", (2,), count - 1, None)
    assert len(A_.unroll(words)) == 1 + 3 * count + 1, "a PULL, then the two-word body and a NOP count times, then a SET"
    for seed in range(10):
        lockstep(a_program(source)[0], unrolled(words), seed)


def test_the_shortest_body_is_one_word():
    source = "        PULL\nbit:    SHIFT_OUT [2]\n        REPEAT 8, bit\n        SET 0, 1"
    _, words = a_program(source)
    assert decode(words[2], A_.isa()).args == (1,)
    for seed in range(10):
        lockstep(a_program(source)[0], unrolled(words), seed)


def test_the_longest_body_is_255_words_and_256_is_refused():
    """255 back is the operand byte's reach; with the REPEAT the program is
    256 words, the memory. One more word of body is refused."""
    lines = [f"        SET {i % 4}, {i % 2} [{i % 3}]" for i in range(256)]
    source = "start:" + "\n".join(lines[:255])[6:] + "\n        REPEAT 3, start"
    _, words = a_program(source)
    assert len(words) == 256 and decode(words[-1], A_.isa()).args == (255,)
    for seed in range(3):
        lockstep(a_program(source)[0], unrolled(words), seed, cycles=3000)
    longer = "start:" + "\n".join(lines)[6:] + "\n        REPEAT 3, start"
    with pytest.raises(SyntaxError, match="256 words back"):
        a_program(longer)


@pytest.mark.parametrize("bad, message", [
    ("bit:    SET 0, 0\n        REPEAT 0, bit", "count 0"),
    ("bit:    SET 0, 0\n        REPEAT 33, bit", "count 33"),
    ("        REPEAT 2, ahead\nahead:  SET 0, 0", "words back"),
    ("bit:    SET 0, 0\n        REPEAT 2, bit\n        REPEAT 2, bit", "inside its body"),
    ("outer:  SET 0, 0\ninner:  SET 0, 1\n        REPEAT 2, inner\n        REPEAT 2, outer", "inside its body"),
    ("bit:    SET 0, 0\n        JMP out\n        REPEAT 2, bit\nout:    SET 0, 1", "leaves the body"),
    ("bit:    SET 0, 0\n        SKIP 0, 0\n        REPEAT 2, bit\n        SET 0, 1", "last word is a SKIP"),
    ("        JMP in\nbit:    SET 0, 0\nin:     SET 0, 1\n        REPEAT 2, bit", "lands inside the body"),
    ("        SKIP 0, 0\nbit:    SET 0, 0\n        SET 0, 1\n        REPEAT 2, bit", "steps into the body"),
])
def test_the_assembler_refuses_what_the_hardware_would_do_something_odd_with(bad, message):
    """The control-flow corners are closed by the assembler, not by machinery:
    count outside 1..32, a label ahead, a REPEAT inside a body, a JMP out
    of a body, a SKIP as the body's last word, a JMP or SKIP into a body
    past its label."""
    with pytest.raises(SyntaxError, match=message):
        a_program(bad)


def test_what_the_assembler_allows_around_a_body():
    """A SKIP just before the label landing on it, and two bodies one after
    the other: fine, and the unrolled program."""
    source = ("        SKIP 0, 0\n        SET 0, 1\nbit:    SET 0, 0\n        SET 1, 1\n        REPEAT 3, bit\n"
              "two:    SET 2, 0\n        SET 2, 1\n        REPEAT 2, two\n        SET 3, 0")
    _, words = a_program(source)
    for seed in range(5):
        lockstep(a_program(source)[0], unrolled(words), seed)


def test_a_stall_on_the_bodys_first_and_last_word_leaves_the_count_alone():
    """The body starts with a PULL and ends with a PUSH, the outside world
    handing over a byte only once the FIFO is empty and slow to pop: both
    stall, again and again over 32 iterations, and the run is the unrolled
    program's. rc is watched: it changes only on the REPEAT's cycle, never
    during a stall or a delay."""
    source = "byte:   PULL 1, 0 [1]\n        SHIFT_OUT 1, 1 [1]\n        SHIFT_IN 0 [1]\n        PUSH 1, 0\n        REPEAT 32, byte\n        SET 2, 0"
    cpu, words = a_program(source)
    ref = unrolled(words)
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
        at = decode(cpu.program[cpu.pc], A_.isa()).op
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
    loop = "        PULL\nbit:    SHIFT_OUT 1, 0 [2]\n        SET 1, 1 [1]\n        REPEAT 4, bit\n        SET 1, 0"
    other = "        SET 3, 0 [2]\nbit:    SHIFT_OUT [1]\n        REPEAT 3, bit\n        SET 3, 1"
    _, words = a_program(loop)
    _, other_words = a_program(other)
    whole = A_(words, tx_data=[0x96])
    whole.run()
    total = whole.cycle
    for t in range(1, total):
        for program in (None, other_words):
            cpu = A_(words, tx_data=[0x96, 0x53])
            cpu.run_cycles(t)
            cpu.restart(program)
            assert cpu.pc == 0 and cpu.rc == 0 and cpu.counter == 0 and not cpu.stalled and cpu.gpio == [1] * 4 and cpu.cycle == t
            fresh = A_(words if program is None else program, tx_data=list(cpu.tx_fifo))
            fresh.rx_fifo = list(cpu.rx_fifo)
            cpu.run()
            fresh.run()
            assert cpu.trace[t:] == fresh.trace, f"restart at cycle {t}"
            assert cpu.rx_fifo == fresh.rx_fifo and cpu.cycle - t == fresh.cycle


def test_repeat_has_no_side_effect_bits_to_reserve():
    """Opcode 3, count 5, back 8: sixteen. Nothing left for a side effect,
    nothing to declare reserved; a side effect written on a REPEAT is refused."""
    spec = A_.isa()["instructions"]["REPEAT"]
    assert not spec.get("side_effect") and spec["operands"] == load_isa()["instructions"]["REPEAT"]["operands"]
    with pytest.raises(SyntaxError):
        a_program("bit:    SET 0, 0\n        REPEAT 2, bit, 1, 0")
