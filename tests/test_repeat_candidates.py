"""The repeat candidates against the SWD programs: docs/repeat-candidates.md.

SWD's complaint was one thing only: the same two-word bit cell 32 times over,
64 of each program's words. experiments/repeat/candidates.py has four ways to
say "again" as model-only ISA variants, A a counted backward branch, B a
one-word repeat, C a counter with a load and a decrement-and-branch, D a
SHIFT that does eight cells, and the two SWD programs with each spliced in
wherever a body repeats, the loop word's cycle taken from a delay next to it.
programs/swd_read.asm and programs/swd_write.asm, 103 and 106 words, are the
baseline and stay as they are.

What a candidate has to survive here: the baseline's wire cycle for cycle
with a target that says OK, WAIT then OK, or FAULT, with a host late to push
the request again, with a host that reads nothing until the FIFO is full or
queues the data late so a PUSH or PULL stalls inside the repeated body (the
count must not move while the core stands still); a restart in the middle of
a loop; and every existing program assembling to the same words meaning the
same things. The word counts are pinned. tests/test_swd.py's Wire, Target and
SlowHost are the bench; the candidate's CPU runs in the model's place."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
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
    base = CPU(load_program(PROGRAMS / "uart_tx_pull.asm"), tx_data=[0x96])
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
    assembles to the same words under the candidate's ISA and every word
    decodes to the same instruction. The candidate's model, run as the
    model, passes the existing suite except the tests that pin the free
    opcode or the spare bit free: experiments/repeat/suite.py."""
    cls = CANDIDATES[tag]
    isa, base = cls.isa(), load_isa()
    for path in sorted(PROGRAMS.glob("*.asm")):
        source = path.read_text()
        words = assemble(source, base)
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
