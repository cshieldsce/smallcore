"""The CAN candidates against the arbitration and stuffing programs:
docs/can-candidates.md.

CAN left two complaints on the post-REPEAT ISA (README, "CAN by the
numbers"). Arbitration: once SHIFT_OUT has put the bit on the pin nothing
can branch on it, so can_tx_arb.asm sees the bus through a transceiver, two
pins, and decides with SKIP, JMP, SKIP, JMP. Stuffing: the last five samples
sit in in_shift_reg, but asking "all one level?" is a tree of single-bit
SKIPs seven cycles deep, so can_tx_stuff.asm runs at 16 cycles a bit.
experiments/can/candidates.py has the reviewer's four shapes as model-only
ISA variants, A a one-cycle conditional branch, B the sent bit exposed, C a
run test over the register, D a run counter, and their combinations, and
experiments/can/gen.py splices each into the exact baseline programs.
programs/can_tx_arb.asm and programs/can_tx_stuff.asm, 95 and 224 words,
stay as they are.

What a candidate has to survive here: the baseline's bus, cycle for cycle
for arbitration (won, lost on every recessive bit, unopposed, a host late
with the second byte) and bit for bit for stuffing at its own bit length
(every identifier of the reference set, a receiver that drops stuff bits,
the same byte to the host); a restart in the middle of a frame; a stall
inside a frame leaving its registers alone; and every existing program
assembling to the same words meaning the same things. The sample point of
every program is probed with a one-cycle glitch, and the words each
candidate adds to the word space are counted, with none changed.
tests/test_can.py's Bus, Node, Competitor and Glitch are the bench; the
candidate's CPU runs in the model's place."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# experiments/repeat/candidates.py is `candidates` to tests/test_repeat_candidates.py; this one is loaded under its own name
_spec = importlib.util.spec_from_file_location("can_candidates", ROOT / "experiments" / "can" / "candidates.py")
candidates = importlib.util.module_from_spec(_spec)
sys.modules["can_candidates"] = candidates
_spec.loader.exec_module(candidates)
ARBITRATION, CANDIDATES, STUFFING, Candidate = candidates.ARBITRATION, candidates.CANDIDATES, candidates.STUFFING, candidates.Candidate
assemble_candidate, load_candidate = candidates.assemble, candidates.load_program

from cpu import CPU, assemble, decode, encode, load_isa, load_program  # noqa: E402
from test_can import (  # noqa: E402
    ARB, ARB_SAMPLE, BIT, CAN_TX, HEADER, HIGHER, ID_BITS, IDENT, IDENTS, LOSSES, NAMES, PROGRAMS, RXD, STUFF, STUFF_BIT,
    STUFF_IDENTS, STUFF_SAMPLE, TX, Bus, Competitor, Glitch, Node, arb, bits_to_int, cells, frame_bits, header_bits, header_bytes,
    pairs, run, stuffed,
)
from test_swd import DATA, DP_READ, OK, READ, SlowHost, Target, Wire, read_bytes  # noqa: E402

BASE = load_isa()

# tag -> (words, distinct, pins on the bus side, the clock of the bit whose level the bus sample takes, cycles after it to decide)
ARB_SPLICED = {"A": (84, 15, 2, 5, 2), "B": (95, 34, 1, 4, 3), "Bc": (84, 33, 1, 4, 3), "AB": (84, 15, 1, 5, 2), "ABc": (73, 14, 1, 5, 2)}
PAIRS = ("A", "B", "AB")  # the host reads (sent, seen) pairs as from the baseline; Bc and ABc sample once a bit: the last eight
LATER_LOSS = ("A", "AB", "ABc")  # the lost exit a cycle later than the baseline's: the sample is a clock later and the decision a cycle shorter

# name -> (candidate, cycles a bit, the clock of the bit whose level the sample takes, words, distinct, cycles after the last bit to the halt)
STUFF_FORMS = {
    "can_tx_stuff_loop": (None, 16, 7, 91, 44, 1),  # today's ISA: the baseline's cell as a REPEAT body
    "can_tx_stuff_A": ("A", 12, 6, 168, 29, 1),
    "can_tx_stuff_A_loop": ("A", 12, 5, 74, 36, 1),
    "can_tx_stuff_C": ("C", 8, 4, 104, 38, 1),
    "can_tx_stuff_C_loop": ("C", 8, 3, 46, 25, 1),
    "can_tx_stuff_AC": ("AC", 8, 5, 97, 37, 2),
    "can_tx_stuff_AC_loop": ("AC", 8, 3, 46, 25, 2),
    "can_tx_stuff_D": ("D", 10, 5, 104, 39, 1),
    "can_tx_stuff_D_loop": ("D", 10, 4, 46, 27, 1),
    "can_tx_stuff_AD": ("AD", 8, 5, 97, 30, 2),
    "can_tx_stuff_AD_loop": ("AD", 8, 3, 46, 26, 2),
}


def candidate_of(name):
    tag = STUFF_FORMS[name][0]
    return Candidate if tag is None else CANDIDATES[tag]


def arb_run(tag, ident, nodes, cycles=200, host=None, tx=None):
    """The arbitration splice on its candidate, `ident` from the host, `nodes` on the bus."""
    cls = CANDIDATES[tag]
    cpu = cls(load_candidate(f"can_tx_arb_{tag}", cls), gpio_in=1, tx_data=header_bytes(ident) if tx is None else list(tx))
    return Bus(None, [], nodes, host=host, rxd=RXD if tag == "A" else None, cpu=cpu).go(cycles).result()


def stuff_run(name, ident, nodes=None, cycles=2000, host=None, tx=None):
    """A stuffing form on its candidate, with a receiver that drops stuff bits unless told otherwise."""
    cls = candidate_of(name)
    _, bit, sample, _, _, _ = STUFF_FORMS[name]
    cpu = cls(load_candidate(name, cls), gpio_in=1, tx_data=header_bytes(ident) if tx is None else list(tx))
    nodes = [Node(sample, bit=bit, destuff=True)] if nodes is None else nodes
    return Bus(None, [], nodes, host=host, cpu=cpu).go(cycles).result()


def stuff_receiver(name):
    _, bit, sample, _, _, _ = STUFF_FORMS[name]
    return Node(sample, bit=bit, destuff=True)


def last_samples(bits, n=8):
    """The byte a program that samples the bus once a bit hands the host after `bits`."""
    return bits_to_int(bits[-n:])


@pytest.fixture(params=ARBITRATION, ids=lambda t: f"candidate {t}")
def tag(request):
    return request.param


@pytest.fixture(params=sorted(STUFF_FORMS), ids=lambda n: n.removeprefix("can_tx_stuff_"))
def form(request):
    return request.param


# --- the splices, word for word --------------------------------------------------------------


def test_spliced_arbitration_word_counts(tag):
    """The numbers the comparison is about, for 95 and 34. The pins: A keeps
    the transceiver's two, the rest put the pad back on the bus."""
    words = load_candidate(f"can_tx_arb_{tag}", CANDIDATES[tag])
    assert (len(words), len(set(words))) == ARB_SPLICED[tag][:2]
    assert (len(load_program(ARB)), len(set(load_program(ARB)))) == (95, 34), "the baseline moved"


def test_spliced_stuffing_word_counts(form):
    """For 224 and 71, at 16 cycles a bit."""
    words = load_candidate(form, candidate_of(form))
    assert (len(words), len(set(words))) == STUFF_FORMS[form][3:5]
    assert (len(load_program(STUFF)), len(set(load_program(STUFF)))) == (224, 71), "the baseline moved"


def test_the_stuffing_loop_is_a_program_for_the_ISA_as_it_is():
    """The correction to stage 4: the assembler lets a JMP in a REPEAT body
    land on the REPEAT itself, so the baseline's cell, its exits all to the
    REPEAT, is a body. can_tx_stuff_loop.asm assembles on the model's own
    assembler, no candidate: 91 words for 224, on today's ISA."""
    source = (ROOT / "experiments" / "can" / "can_tx_stuff_loop.asm").read_text()
    words = assemble(source, BASE)
    assert len(words) == 91 and words == load_candidate("can_tx_stuff_loop", Candidate)
    assert sum(1 for w in words if decode(w, BASE).op == "REPEAT") == 3
    tiny = "bit:    SET 0, 0\n        SKIP 0, 0\n        JMP end\n        SET 0, 1\nend:    REPEAT 3, bit"
    assert len(assemble(tiny, BASE)) == 5, "a JMP to the REPEAT that ends its body is inside it"


# --- arbitration: the bus, cycle for cycle ------------------------------------------------------


def assert_same_bus(a, b, later=0):
    """Cycle for cycle: the bus, and what the node put out; the same view
    from every node; both halted, the candidate `later` cycles after."""
    assert a.cpu.halted and b.cpu.halted
    assert b.cpu.cycle == a.cpu.cycle + later
    assert b.line[: len(a.line)] == a.line, "the bus differs"
    assert b.txd[: len(a.txd)] == a.txd, "what the node put out differs"
    assert b.txd[len(a.txd):] == [1] * later, "let go for the extra cycle: the bus is the other nodes' there"
    for x, y in zip(a.nodes, b.nodes):
        assert (y.seen, getattr(y, "lost", None)) == (x.seen, getattr(x, "lost", None))
    assert b.cpu.tx_fifo == a.cpu.tx_fifo == []


def test_arbitration_won_is_the_baseline(tag):
    """Against a competitor with a higher identifier: the competitor
    withdraws on ID[9], the frame goes out whole, 8 cycles a bit, the same
    100 cycles, the same byte to the host or, sampling once a bit, ID[7:0]."""
    sample = ARB_SPLICED[tag][3]
    a = arb(IDENT, [Competitor(HIGHER, ARB_SAMPLE), Node(ARB_SAMPLE)])
    b = arb_run(tag, IDENT, [Competitor(HIGHER, sample), Node(sample)])
    assert_same_bus(a, b)
    assert b.cpu.cycle == 100 and b.nodes[0].lost == NAMES.index("id9")
    assert b.received == [pairs(header_bits(IDENT)) if tag in PAIRS else IDENT & 0xFF]


@pytest.mark.parametrize("other, k", LOSSES, ids=lambda v: f"{v:03x}" if v > 11 else NAMES[v])
def test_arbitration_lost_on_each_recessive_bit_is_the_baseline(tag, other, k):
    """Against a competitor whose identifier is IDENT with one recessive bit
    dominant: the same bus through the lost bit, nothing put out after it,
    the second byte PULLed away on an early loss, the competitor's frame
    whole. The candidates that sample a clock later and decide a cycle
    faster halt one cycle after the baseline, letting go as it does."""
    sample = ARB_SPLICED[tag][3]
    a = arb(IDENT, [Competitor(other, ARB_SAMPLE), Node(ARB_SAMPLE)], cycles=200)
    b = arb_run(tag, IDENT, [Competitor(other, sample), Node(sample)])
    assert_same_bus(a, b, later=int(tag in LATER_LOSS))
    mine = header_bits(IDENT)
    if tag in PAIRS:
        assert b.received == [pairs(mine[: k + 1]) & ~1], "the pairs through the lost bit, (1, 0) last"
    else:
        assert b.received == [last_samples(header_bits(other)[1 : k + 1])], "the bus as sampled, ID[10] to the lost bit: no sign of the loss"
    assert b.nodes[0].lost is None


@pytest.mark.parametrize("ident", IDENTS, ids=lambda i: f"{i:03x}")
def test_arbitration_unopposed_is_the_baseline(tag, ident):
    """Alone on the bus with a receiver: the identifier whole, the same 100 cycles."""
    sample = ARB_SPLICED[tag][3]
    a = arb(ident, [Node(ARB_SAMPLE)])
    b = arb_run(tag, ident, [Node(sample)])
    assert_same_bus(a, b)
    assert b.nodes[0].seen == [ident] and b.received == [pairs(header_bits(ident)) if tag in PAIRS else ident & 0xFF]


@pytest.mark.parametrize("late", (1, 5, 40))
def test_arbitration_with_a_host_late_with_the_second_byte_is_the_baseline(tag, late):
    """The PULL for {ID[3:0], 0000} still stalls inside ID[4] and stretches it
    by the host's lateness: no candidate touches that. The bus is the
    baseline's, stretched the same."""
    bytes_ = header_bytes(IDENT)
    stalled = arb_run(tag, IDENT, [Node()], tx=bytes_[:1], cycles=200).stalls.index(True)
    base_stalled = run(ARB, bytes_[:1], [Node()], rxd=RXD, cycles=200).stalls.index(True)

    def host_for(at):
        def host(cpu, received):
            if cpu.cycle == at + late:
                cpu.tx_fifo.append(bytes_[1])
        return host

    a = run(ARB, bytes_[:1], [Node(ARB_SAMPLE)], rxd=RXD, host=host_for(base_stalled))
    b = arb_run(tag, IDENT, [Node(ARB_SAMPLE)], tx=bytes_[:1], host=host_for(stalled))  # the same receiver: its view of a stretched bit is its own
    assert_same_bus(a, b)
    assert b.stalls.count(True) == late and b.cpu.cycle == 100 + late
    k = NAMES.index("id4")
    sof = b.line.index(0)
    assert b.line[sof + k * BIT : sof + (k + 1) * BIT + late] == [header_bits(IDENT)[k]] * (BIT + late)


def test_the_arbitration_sample_point(tag):
    """Where each splice samples the bus, probed as the baseline's was: a
    glitch pulls the bus dominant for one cycle of ID[7], a recessive bit,
    at each of its eight cycles in turn; the node loses on that bit exactly
    when the glitch is on the sample clock. The sixth clock where the
    decision is BRANCH's two cycles, the baseline's fifth where it is SKIP
    and JMP's three (the level through the fourth, 50%)."""
    sample = ARB_SPLICED[tag][3]
    sof = arb_run(tag, IDENT, []).line.index(0)
    k = NAMES.index("id7")
    for p in range(BIT):
        r = arb_run(tag, IDENT, [Node(sample), Glitch(sof + k * BIT + p)])
        hit = p == sample - 1
        assert (r.cpu.cycle == sof + (k + 1) * BIT + 2 + int(tag in LATER_LOSS)) == hit, f"glitch on cycle {p + 1}: halted at {r.cpu.cycle}"
        if tag in PAIRS:
            assert r.received == [pairs(header_bits(IDENT)[: k + 1]) & ~1 if hit else pairs(header_bits(IDENT))]


def test_arbitration_by_the_numbers(tag):
    """The pins each splice needs, the cycles it decides in, and that none
    of them gets a REPEAT body: the lost exit leaves it, and a JMP or a
    BRANCH out of a body is what REPEAT forbids."""
    cls = CANDIDATES[tag]
    words, distinct, pins, sample, decision = ARB_SPLICED[tag]
    r = arb_run(tag, IDENT, [Node(sample)])
    assert r.cpu.open_drain == ([0, 1, 0, 0] if pins == 2 else [1, 0, 0, 0]), "TXD push-pull and RXD let go, or the pad on the bus"
    assert sample + 1 + decision == BIT, "the sample's own cycle and the decision fill the bit after the level it takes"
    assert not any(cls.decode(w).op == "REPEAT" for w in load_candidate(f"can_tx_arb_{tag}", cls))
    exit_word = "BRANCH 0, 1, lost" if tag in ("A", "AB", "ABc") else "JMP lost"
    body = f"bit:    SHIFT_OUT\n        SHIFT_IN 0 [5]\n        {exit_word}\n        REPEAT 11, bit\nlost:   PUSH 0, 1"
    with pytest.raises(SyntaxError, match="leaves the body"):
        assemble_candidate(body, cls)


# --- stuffing: the bus, bit for bit ------------------------------------------------------------


@pytest.mark.parametrize("ident", STUFF_IDENTS, ids=lambda i: f"{i:03x}")
def test_stuffing_is_the_baseline_bit_for_bit(form, ident):
    """The same bits on the bus as can_tx_stuff.asm puts there at 16 cycles
    a bit, each held the form's own bit time; the receiver reads the
    identifier with no stuff error; dominant driven, recessive let go; the
    same byte to the host; halted a cycle after the last bit."""
    _, bit, sample, _, _, halt = STUFF_FORMS[form]
    a = run(STUFF, header_bytes(ident), [Node(STUFF_SAMPLE, bit=STUFF_BIT, destuff=True)])
    b = stuff_run(form, ident)
    bits = stuffed(header_bits(ident))
    sof_a, sof_b = a.line.index(0), b.line.index(0)
    assert cells(a.line, sof_a, len(bits), STUFF_BIT) == bits, "the baseline"
    assert cells(b.line, sof_b, len(bits), bit) == bits, "the candidate"
    assert sof_b == sof_a == 3
    assert b.nodes[0].seen == [ident] and b.nodes[0].errors == []
    assert b.owned == [level == 0 for level in b.line]
    end = sof_b + len(bits) * bit
    assert b.line[end:] == [1] * len(b.line[end:]) and b.cpu.halted and b.cpu.cycle == end + halt
    assert b.received == a.received == [bits_to_int(bits[-8:])]


def test_stuffing_across_the_range_is_the_baseline(form):
    """The walking ones and zeros and every 97th identifier, one frame each."""
    walking = [1 << i for i in range(ID_BITS)] + [(1 << ID_BITS) - 1 - (1 << i) for i in range(ID_BITS)]
    _, bit, _, _, _, _ = STUFF_FORMS[form]
    for ident in walking + list(range(0, 1 << ID_BITS, 97)):
        r = stuff_run(form, ident)
        bits = stuffed(header_bits(ident))
        assert cells(r.line, r.line.index(0), len(bits), bit) == bits, f"identifier {ident:03x}"
        assert r.nodes[0].seen == [ident] and r.nodes[0].errors == [] and r.received == [bits_to_int(bits[-8:])], f"identifier {ident:03x}"


def test_the_stuffing_sample_point(form):
    """Where each form samples, probed as the baseline's was: a glitch pulls
    the bus dominant for one cycle of ID[7], a recessive bit of 0x5A3, at
    each cycle of the bit in turn; the host's byte and the receiver's
    identifier lose that bit exactly when the glitch is on the sample clock."""
    _, bit, sample, _, _, _ = STUFF_FORMS[form]
    sof = stuff_run(form, IDENT, []).line.index(0)
    k = NAMES.index("id7")
    for p in range(bit):
        r = stuff_run(form, IDENT, [stuff_receiver(form), Glitch(sof + k * bit + p)])
        hit = p == sample - 1
        assert r.received == [IDENT & 0xFF & ~(hit << 7)], f"the transmitter's sample, glitch on cycle {p + 1} of the bit"
        assert r.nodes[0].seen == [IDENT & ~(hit << 7)], f"the receiver's sample, glitch on cycle {p + 1} of the bit"


@pytest.mark.parametrize("late", (1, 5, 40))
def test_a_host_late_with_the_second_byte_stretches_id4_in_every_form(form, late):
    """The mid-frame PULL is still inside ID[4] in every form: a host late by
    `late` stretches that bit by exactly `late`, the bits before it are on
    time and the rest late, and the candidate's own registers, if it has
    any, do not move while the core stands still."""
    _, bit, sample, _, _, _ = STUFF_FORMS[form]
    bytes_ = header_bytes(IDENT)
    stalled = stuff_run(form, IDENT, [], tx=bytes_[:1], cycles=400).stalls.index(True)
    states = []

    def host(cpu, received):
        states.append((cpu.stalled, cpu.state()))
        if cpu.cycle == stalled + late:
            cpu.tx_fifo.append(bytes_[1])

    r = stuff_run(form, IDENT, tx=bytes_[:1], host=host)
    sof = r.line.index(0)
    k = NAMES.index("id4")
    bits = header_bits(IDENT)
    assert cells(r.line, sof, k, bit) == bits[:k]
    assert r.line[sof + k * bit : sof + (k + 1) * bit + late] == [bits[k]] * (bit + late)
    assert cells(r.line, sof + (k + 1) * bit + late, HEADER - k - 1, bit) == bits[k + 1 :]
    assert r.stalls.count(True) == late and r.received == [IDENT & 0xFF]
    during = [state for stalled_, state in states if stalled_]
    assert len(during) == late and len(set(during)) == 1, "the candidate's registers moved during the stall"


def test_restart_in_the_middle_of_a_frame_starts_clean(form):
    """The chip's restart at cycle 60, inside ID[10]'s or ID[9]'s bit: the
    core back to reset, the candidate's registers with it, the FIFOs kept;
    the run from there, with both bytes queued again, is a fresh run."""
    cls = candidate_of(form)
    r = stuff_run(form, 0x7FF, cycles=60)
    cpu = r.cpu
    assert not cpu.halted and cpu.pc != 0
    cpu.restart()
    assert cpu.pc == 0 and cpu.counter == 0 and cpu.rc == 0 and not cpu.stalled and cpu.gpio == [1] * 4
    assert cpu.state() == cls(cpu.program).state(), "restart left the candidate's registers"
    cpu.tx_fifo.clear()
    cpu.rx_fifo.clear()
    cpu.tx_fifo.extend(header_bytes(0x7FF))
    again = Bus(None, [], [stuff_receiver(form)], cpu=cpu).go(2000).result()
    fresh = stuff_run(form, 0x7FF)
    assert again.cpu.halted and again.cpu.cycle - 60 == fresh.cpu.cycle
    assert again.line == fresh.line and again.received == fresh.received and again.nodes[0].seen == [0x7FF]


def test_stuffing_by_the_numbers(form):
    """Each form measured: the words, the bit time, the sample clock, the
    cycles for an identifier with no run and for 0x7FF with two stuff bits,
    the host's part, and whether the checked bits are REPEAT bodies."""
    cls = candidate_of(form)
    _, bit, sample, words, distinct, halt = STUFF_FORMS[form]
    program = load_candidate(form, cls)
    assert (len(program), len(set(program))) == (words, distinct)
    none, two = stuff_run(form, IDENT), stuff_run(form, 0x7FF)
    assert none.cpu.cycle == 3 + HEADER * bit + halt
    assert two.cpu.cycle == 3 + (HEADER + 2) * bit + halt
    assert (none.tx_peak, none.rx_peak, len(none.received)) == (2, 1, 1)
    repeats = sum(1 for w in program if cls.decode(w).op == "REPEAT")
    assert repeats == (3 if form.endswith("loop") else 1), "the first four bits are always a body; the checked bits are two more in the loop forms"


# --- the existing programs -------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CANDIDATES), ids=lambda t: f"candidate {t}")
def test_every_existing_program_means_the_same_under_the_candidate(name):
    """A candidate adds words; it changes none. Every program in programs/,
    REPEAT's included, assembles to the same words under the candidate's
    ISA and every word decodes to the same instruction."""
    cls = CANDIDATES[name]
    for path in sorted(PROGRAMS.glob("*.asm")):
        source = path.read_text()
        words = assemble(source, BASE)
        assert assemble_candidate(source, cls) == words, path.name
        for word in words:
            assert cls.decode(word) == decode(word, BASE), f"{path.name}: {word:#06x}"


NEW_WORDS = {"A": 1008, "B": 1152, "Bc": 256, "C": 0, "D": 256, "AB": 2160, "ABc": 1768, "AC": 2016, "AD": 2272}  # C's 1024 are the ISA's since 2026-09-28: SKIP_RUN and SKIP_NORUN adopted; AC adds BRANCH and BRANCH_RUN


@pytest.mark.parametrize("name", sorted(CANDIDATES), ids=lambda t: f"candidate {t}")
def test_what_each_candidate_adds_to_the_word_space(name):
    """Of the 65,536 words the ISA accepts 28,384. Each candidate accepts
    those, meaning the same, and these more, each re-encoding to itself:
    BRANCH 63 distances by 16 conditions; SHIFT_SENT 4 pins by 9 side
    effects by 32 delays; SKIP_SENT 8 by 32; SKIP_SAME 8 by 32; and a second
    branch kind another 1008. SKIP_RUN and SKIP_NORUN, 16 by 32 each, were
    C's until 2026-09-28 and are the ISA's now: C adds nothing."""
    cls = CANDIDATES[name]
    new, changed = 0, 0
    for word in range(1 << 16):
        try:
            base = decode(word, BASE)
        except ValueError:
            base = None
        try:
            mine = cls.decode(word)
        except ValueError:
            mine = None
        if base is not None:
            changed += mine != base
        elif mine is not None:
            new += 1
            assert encode(mine, cls.isa()) == word, f"{word:#06x} re-encodes differently"
    assert (new, changed) == (NEW_WORDS[name], 0)


def test_the_copied_step_is_the_model():
    """Candidate is cpu.CPU's step written out with hooks; on the baseline
    programs it must be the model to the cycle. Here on the arbitration won
    and lost and on the stuffing of 0x7FF; suite.py runs the whole suite on it."""
    for other in (HIGHER, LOSSES[0][0]):
        a = arb(IDENT, [Competitor(other, ARB_SAMPLE), Node(ARB_SAMPLE)], cycles=200)
        cpu = Candidate(load_program(ARB), gpio_in=1, tx_data=header_bytes(IDENT))
        b = Bus(None, [], [Competitor(other, ARB_SAMPLE), Node(ARB_SAMPLE)], rxd=RXD, cpu=cpu).go(200).result()
        assert_same_bus(a, b)
        assert a.received == b.received
    a = run(STUFF, header_bytes(0x7FF), [Node(STUFF_SAMPLE, bit=STUFF_BIT, destuff=True)])
    cpu = Candidate(load_program(STUFF), gpio_in=1, tx_data=header_bytes(0x7FF))
    b = Bus(None, [], [Node(STUFF_SAMPLE, bit=STUFF_BIT, destuff=True)], cpu=cpu).go(2000).result()
    assert (a.line, a.owned, a.received, a.cpu.cycle) == (b.line, b.owned, b.received, b.cpu.cycle)


# --- the words' own corners ---------------------------------------------------------------------


@pytest.mark.parametrize("bad, message", [
    ("bit:    SET 0, 0\n        BRANCH 0, 0, out\n        REPEAT 2, bit\nout:    SET 0, 1", "leaves the body"),
    ("        BRANCH 0, 0, in\nbit:    SET 0, 0\nin:     SET 0, 1\n        REPEAT 2, bit", "lands inside the body"),
    ("        SKIP_RUN 2, 0\nbit:    SET 0, 0\n        SET 0, 1\n        REPEAT 2, bit", "steps into the body"),
    ("bit:    SET 0, 0\n        SKIP_RUN 2, 0\n        REPEAT 2, bit\n        SET 0, 1", "last word is a SKIP_RUN"),
    ("        BRANCH 0, 0, far\n" + "        NOP\n" * 63 + "far:    NOP", "64 words ahead"),
    ("back:   NOP\n        BRANCH 0, 0, back", "-1 words ahead"),
    ("        BRANCH 0, 0, 0", "0 words ahead"),
    ("        BRANCH 0, 0, x [1]\nx:      NOP", "takes no delay"),
    ("        SKIP_RUN 9, 0\n        NOP", "outside 1..8"),
    ("        BRANCH_RUN 0, 1, x\nx:      NOP", "outside 1..8"),
])
def test_the_assembler_refuses_what_the_hardware_would_do_something_odd_with(bad, message):
    """The branch family keeps REPEAT's rules as a JMP does, reaches 1 to 63
    words ahead and never back, takes no delay; a run test's n is 1 to 8."""
    with pytest.raises(SyntaxError, match=message):
        assemble_candidate(bad, CANDIDATES["AC"])


def test_branch_is_one_cycle_taken_or_not_and_skip_plus_jmp_is_not():
    """The shape the two complaints share, measured on one word: after a
    sample, BRANCH lands on its target or the next word on the very next
    cycle either way; SKIP and JMP land on the next cycle when the SKIP
    steps over and a cycle later when the JMP is taken."""
    cls = CANDIDATES["A"]
    for level in (0, 1):
        branch = cls(assemble_candidate("        SHIFT_IN 0\n        BRANCH 7, 1, one\n        SET 1, 0\n        JMP end\none:    SET 2, 0\nend:    NOP", cls), gpio_in=level)
        skip = cls(assemble_candidate("        SHIFT_IN 0\n        SKIP 7, 0\n        JMP one\n        SET 1, 0\n        JMP end\none:    SET 2, 0\nend:    NOP", cls), gpio_in=level)
        for cpu in (branch, skip):
            cpu.run_cycles(3)
        assert branch.gpio[1 + level] == 0, "landed on the third cycle"
        assert skip.gpio[1 + level] == (level and 1), "the taken side a cycle behind"


def test_run_tests_and_the_counter_agree_with_the_register_on_every_history():
    """C reads the register, D counts as it fills: on every 8-sample history,
    LSB or MSB first, SKIP_RUN n, level is 'the newest n samples are all
    level', SKIP_NORUN its negation, and SKIP_SAME n is 'the newest n are all
    the same' for n up to 7, the counter's reach."""
    for shift_dir in (0, 1):
        for history in range(256):
            bits = [(history >> i) & 1 for i in range(8)]  # oldest first
            c, d = CANDIDATES["C"]([0]), CANDIDATES["D"]([0])
            c.shift_dir = d.shift_dir = shift_dir
            for bit in bits:
                c.sample(bit)
                d.sample(bit)
            for n in range(1, 9):
                newest = bits[-n:]
                for level in (0, 1):
                    assert c.test("SKIP_RUN", n - 1, level) == all(b == level for b in newest)
                    assert c.test("SKIP_NORUN", n - 1, level) != c.test("SKIP_RUN", n - 1, level)
                if n < 8:
                    assert d.test("SKIP_SAME", n - 1, 0) == (len(set(newest)) == 1), f"{bits} n {n} same {d.same}"
                else:
                    assert not d.test("SKIP_SAME", 7, 0), "three bits saturate at 7: a run of eight is never seen"
            assert d.same == min(7, max(k for k in range(1, 9) if len(set(bits[-k:])) == 1))


# --- the existing protocols -------------------------------------------------------------------


def test_a_serves_swd_and_i2c_where_the_decision_goes_ahead_and_not_where_it_goes_back():
    """Cross-protocol applicability of A. SWD's first decision, `SKIP 5, 0`
    then `JMP data`, is one BRANCH: the read is 102 words for 103 and,
    with a target that says OK, one cycle shorter, because the baseline's
    OK path spent the SKIP and the JMP, two cycles with SWCLK high, where
    its WAIT and FAULT path spent the SKIP alone: the asymmetry CAN
    measured, present in SWD all along. The bytes are the same. SWD's
    second decision, `SKIP 6, 0` then `JMP request`, goes back to word 1,
    and BRANCH goes ahead only: refused, so it keeps SKIP and JMP. I²C's
    ACK decision goes ahead, to the STOP: one word."""
    cls = CANDIDATES["A"]
    source = READ.read_text()
    assert any(line.startswith("        SKIP 5, 0 ") for line in source.splitlines()) and any(line.startswith("        JMP data ") for line in source.splitlines())
    lines = [line for line in source.splitlines() if not line.startswith("        JMP data ")]
    lines = [line.replace("        SKIP 5, 0 ", "        BRANCH 5, 1, data ", 1) if line.startswith("        SKIP 5, 0 ") else line for line in lines]
    words = assemble_candidate("\n".join(lines) + "\n", cls)
    assert len(words) == 102 and len(load_program(READ)) == 103
    base = Wire(READ, DP_READ, Target([OK], DATA), host=SlowHost(DP_READ)).go(3000)
    a = Wire(None, DP_READ, Target([OK], DATA), host=SlowHost(DP_READ), cpu=cls(words, gpio_in=1, tx_data=[DP_READ])).go(3000)
    assert base.cpu.halted and a.cpu.halted and base.cpu.cycle == 379 and a.cpu.cycle == 378
    assert a.received == base.received == read_bytes(OK, DATA)
    assert sum(base.swclk) - sum(a.swclk) == 1, "the cycle that goes is one with SWCLK high, the JMP's"
    back = [line for line in source.splitlines() if not line.startswith("        JMP request ")]
    back = [line.replace("        SKIP 6, 0 ", "        BRANCH 6, 1, request ", 1) if line.startswith("        SKIP 6, 0 ") else line for line in back]
    with pytest.raises(SyntaxError, match="words ahead"):
        assemble_candidate("\n".join(back) + "\n", cls)
    i2c = (PROGRAMS / "i2c_write_addr_data.asm").read_text()
    assert any(line.startswith("        SKIP 0, 0 ") for line in i2c.splitlines()) and any(line.startswith("        JMP stop ") for line in i2c.splitlines())
    lines = [line for line in i2c.splitlines() if not line.startswith("        JMP stop ")]
    lines = [line.replace("        SKIP 0, 0 ", "        BRANCH 0, 1, stop ", 1) if line.startswith("        SKIP 0, 0 ") else line for line in lines]
    assert len(assemble_candidate("\n".join(lines) + "\n", cls)) == 63 and len(load_program(PROGRAMS / "i2c_write_addr_data.asm")) == 64

