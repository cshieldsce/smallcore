"""SKIP_RUN and SKIP_NORUN, the run test over in_shift_reg, adopted
2026-09-28 (docs/can-candidates.md, "Decided"): the corners pinned on the
model, the way REPEAT's were.

The word: opcode 000, NOP's hole, bits 7:5 = 010, bit 4 the sense, bits 3:1
n - 1, bit 0 the level, a delay in 12:8 as any word, no side effect. The
test: the newest n samples, the n bits at the end SHIFT_IN fills, all
`level`; SKIP_RUN steps over the next word when they are, SKIP_NORUN when
they are not; n = 1 is SKIP on the newest bit. Every register value, every
n, both levels, both shift directions, both senses; the delay holds and
decides on its last cycle; nothing else moves. The assembler writes n - 1
and keeps REPEAT's rules for a run test as for a SKIP. 1024 words that were
rejected are instructions now and no other word changed meaning; every
program in programs/ assembles to the words it did.

Then the programs the word was earned by, on the model as it is now: the
stuffing transmitter's C forms from the candidate round, bit for bit the
baseline's at 8 cycles a bit, and the receiver's, the stream on the pins in
34 words for 56 and through the FIFO at 8 clocks in 27 for 57."""

import copy
import itertools
import random
from pathlib import Path

import pytest

from cpu import CPU, Instruction, assemble, decode, encode, load_isa, load_program
from test_can import BIT, IDENT, STUFF_IDENTS, Bus, Node, bits_to_int, cells, header_bits, header_bytes, stuffed  # noqa: E402
from test_can_rx import AT, BITS_BIT, RX_SAMPLE, frame_bits, frame_on_the_bus, run_rx, stream_from_pins, stuff_positions  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "experiments" / "can"
ISA = load_isa()
RUNS = ("SKIP_RUN", "SKIP_NORUN")


def old_isa():
    """isa.yaml as it was before the run tests: the two gone, NOP's select the flag bit alone."""
    isa = copy.deepcopy(ISA)
    for op in RUNS:
        del isa["instructions"][op]
    isa["instructions"]["NOP"]["select"] = {"name": "side", "lsb": 7, "bits": 1, "value": 0}
    return isa


def word(op, n, level, delay=0):
    return encode(Instruction(op, (n - 1, level), delay), ISA)


def newest(reg, n, shift_dir):
    """The reference: the newest n bits of the register as an integer, oldest at the top."""
    return reg & ((1 << n) - 1) if shift_dir else reg >> (8 - n)


# --- the word ----------------------------------------------------------------------------------


def test_the_words_sit_in_nops_hole():
    """SKIP_RUN 5, 1 is 0x0049: opcode 000, bits 7:5 = 010, bit 4 = 0, n - 1 =
    4 in bits 3:1, the level in bit 0; SKIP_NORUN sets bit 4; a delay goes
    in bits 12:8 as for any word. NOP is still 0x0000 and SET still owns
    the flag bit, so a run test has no side effect: the assembler refuses
    one."""
    assert assemble("SKIP_RUN 5, 1") == [0x0049]
    assert assemble("SKIP_NORUN 5, 1") == [0x0059]
    assert assemble("SKIP_RUN 1, 0 [3]") == [0x0340]
    assert assemble("SKIP_RUN 8, 1") == [0x004F]
    assert assemble("NOP") == [0x0000] and assemble("SET 2, 1") == [0x00D0]
    for bad in ("SKIP_RUN 0, 1", "SKIP_RUN 9, 1", "SKIP_RUN 5", "SKIP_RUN 5, 2", "SKIP_RUN 5, 1, 2, 1", "SKIP_NORUN 5, 1, 0, 0"):
        with pytest.raises(SyntaxError):
            assemble(bad)


def test_the_run_tests_take_1024_rejected_words_and_change_no_other():
    """Every 16-bit word decoded on the ISA as it was and as it is: the words
    that were instructions are the same instructions, 1024 words that were
    rejected are run tests, 2 senses x 8 n x 2 levels x 32 delays, and
    everything else is rejected still."""
    before = old_isa()
    same, new, rejected = 0, 0, 0
    for w in range(1 << 16):
        try:
            was = decode(w, before)
        except ValueError:
            was = None
        try:
            now = decode(w, ISA)
        except ValueError:
            now = None
        if was is not None:
            assert now == was, f"word {w:#06x} changed meaning"
            same += 1
        elif now is not None:
            assert now.op in RUNS and now.side is None, f"word {w:#06x}"
            new += 1
        else:
            rejected += 1
    assert new == 1024 and same + new + rejected == 1 << 16


def test_every_program_assembles_to_the_words_it_did():
    """The programs in programs/ under the ISA as it was and as it is: the same words."""
    before = old_isa()
    for path in sorted((ROOT / "programs").glob("*.asm")):
        assert load_program(path, ISA) == load_program(path, before), path.name


# --- the test ----------------------------------------------------------------------------------


@pytest.mark.parametrize("shift_dir", (0, 1))
@pytest.mark.parametrize("op", RUNS)
def test_the_newest_n_samples_all_the_level_on_every_register_value(op, shift_dir):
    """Every register value, every n 1..8, both levels: after the word's one
    cycle the pc is 2 exactly when the newest n bits are all the level
    (SKIP_RUN) or not all (SKIP_NORUN); the register, the pins, rc and the
    FIFOs untouched; the newest bits are the low n MSB first and the high n
    LSB first."""
    for reg, n, level in itertools.product(range(256), range(1, 9), (0, 1)):
        cpu = CPU([word(op, n, level), 0, 0, 0], isa=ISA)
        cpu.in_shift_reg, cpu.shift_dir = reg, shift_dir
        cpu.step()
        run = newest(reg, n, shift_dir) == (level * ((1 << n) - 1))
        assert cpu.pc == (2 if (run if op == "SKIP_RUN" else not run) else 1), f"{op} {n}, {level} on {reg:#04x}, shift_dir {shift_dir}"
        assert (cpu.in_shift_reg, cpu.gpio, cpu.rc, cpu.tx_fifo, cpu.rx_fifo, cpu.stalled) == (reg, [1, 1, 1, 1], 0, [], [], False)


def test_n_1_is_skip_on_the_newest_bit():
    """SKIP_RUN 1, level steps as SKIP 0, level does MSB first and as SKIP 7,
    level does LSB first, on every register value; SKIP_NORUN 1 as the
    other level's SKIP."""
    for reg, level, shift_dir in itertools.product(range(256), (0, 1), (0, 1)):
        bit = 0 if shift_dir else 7
        for op, skip_level in (("SKIP_RUN", level), ("SKIP_NORUN", 1 - level)):
            a, b = CPU([word(op, 1, level), 0, 0], isa=ISA), CPU([encode(Instruction("SKIP", (bit, skip_level), 0), ISA), 0, 0], isa=ISA)
            a.in_shift_reg = b.in_shift_reg = reg
            a.shift_dir = b.shift_dir = shift_dir
            a.step()
            b.step()
            assert a.pc == b.pc, f"{op} 1, {level} on {reg:#04x}, shift_dir {shift_dir}"


@pytest.mark.parametrize("delay", (0, 1, 7, 31))
def test_the_delay_holds_and_the_pc_moves_on_the_last_cycle(delay):
    """A run test with a delay holds 1 + delay cycles, the pc unmoved until
    its last, then steps by 2 or 1 by the register as it stood, which
    nothing changes meanwhile."""
    for taken in (True, False):
        cpu = CPU([word("SKIP_RUN", 5, 1, delay), 0, 0, 0], isa=ISA)
        cpu.shift_dir, cpu.in_shift_reg = 1, 0x1F if taken else 0x1E
        for _ in range(delay):
            cpu.step()
            assert cpu.pc == 0 and cpu.counter == delay + 1 - cpu.cycle
        cpu.step()
        assert cpu.pc == (2 if taken else 1) and cpu.cycle == delay + 1


def test_the_assembler_keeps_repeats_rules_for_a_run_test():
    """A run test as a body's last word would step over the REPEAT; one
    outside a body stepping into it past its label is refused; inside a
    body, before its last word, it is fine, as is a JMP it steps over."""
    with pytest.raises(SyntaxError, match="last word is a SKIP_NORUN"):
        assemble("body: NOP\nSKIP_NORUN 5, 1\nREPEAT 2, body")
    with pytest.raises(SyntaxError, match="steps into the body"):
        assemble("SKIP_RUN 3, 0\nbody: NOP\nNOP\nREPEAT 2, body")
    assemble("body: SHIFT_IN 0\nSKIP_NORUN 5, 1\nJMP end\nNOP\nend: REPEAT 4, body")


def test_restart_leaves_nothing_of_a_run_test_behind():
    """The run test has no state: after any run of run tests a restart is
    the reset, the register it read cleared with the core as ever."""
    rng = random.Random(1)
    program = [word(rng.choice(RUNS), rng.randrange(1, 9), rng.randrange(2), rng.randrange(4)) for _ in range(20)]
    cpu = CPU(program, isa=ISA)
    cpu.in_shift_reg = 0xA5
    for _ in range(30):
        if cpu.halted:
            break
        cpu.step()
    cpu.restart()
    assert (cpu.pc, cpu.counter, cpu.rc, cpu.in_shift_reg, cpu.halted) == (0, 0, 0, 0, False)


# --- the programs the word was earned by, on the model as it is ------------------------------


STUFF_C = {"can_tx_stuff_C": (8, 4), "can_tx_stuff_C_loop": (8, 3)}  # form -> (cycles a bit, the clock whose level the receiver takes)


@pytest.mark.parametrize("form", sorted(STUFF_C))
@pytest.mark.parametrize("ident", STUFF_IDENTS, ids=lambda i: f"{i:03x}")
def test_the_stuffing_transmitter_with_the_run_test_is_the_baseline_at_eight_cycles_a_bit(form, ident):
    """experiments/can/can_tx_stuff_C.asm and its loop form, the candidate
    round's splices, assembled by the assembler as it is now and run on the
    model as it is now: the stuffed header on the bus bit for bit the
    reference's, every bit 8 cycles, the receiver reading the identifier
    with no stuff error, the host's byte the last eight samples; the same
    words the candidate assembler wrote."""
    bit, sample = STUFF_C[form]
    path = EXPERIMENTS / f"{form}.asm"
    r = Bus(path, header_bytes(ident), [Node(sample, bit=bit, destuff=True)]).go(2000).result()
    bits = stuffed(header_bits(ident))
    sof = r.line.index(0)
    assert cells(r.line, sof, len(bits), bit) == bits
    assert r.nodes[0].seen == [ident] and r.nodes[0].errors == [] and r.cpu.halted
    assert r.received == [bits_to_int(bits[-8:])]
    assert r.owned == [level == 0 for level in r.line]


def test_the_stuffing_forms_by_the_numbers():
    """The words of the C forms as the assembler writes them now: 104 and 46
    for the baseline's 224 and the loop form's 91, 8 cycles a bit for 16."""
    assert (len(load_program(EXPERIMENTS / "can_tx_stuff_C.asm")), len(load_program(EXPERIMENTS / "can_tx_stuff_C_loop.asm"))) == (104, 46)


RX_VECTORS = ((0x5A3, 0x5A), (0x7FF, 0xFF), (0x000, 0x00), (0x07C, 0x00), (0x555, 0xAA), (0x123, 0x01))


@pytest.mark.parametrize("ident, data", RX_VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_the_receiver_with_the_run_test_puts_the_same_stream_on_the_pins(ident, data):
    """experiments/can/can_rx_destuff_C.asm against the bench transmitter at
    8 clocks a bit: the stream on pins 2 and 3 is the frame's, the stuff
    slots where the reference has them, the ACK pulled, the same samples on
    the same clocks as can_rx_destuff.asm's, the same byte to the host."""
    bits, slot = frame_on_the_bus(ident, [data])
    r, tx = run_rx(EXPERIMENTS / "can_rx_destuff_C.asm", ident, [data])
    stream, stuff_slots = stream_from_pins(r, slot - 1)
    assert stream == frame_bits(ident, [data]) and stuff_slots == stuff_positions(ident, [data])
    assert tx.acked is True and r.received == [bits_to_int(bits[slot - 8 : slot])] and r.cpu.halted
    base, _ = run_rx(ROOT / "programs" / "can_rx_destuff.asm", ident, [data])
    assert [i for i, op in enumerate(r.issues) if op == "SHIFT_IN"] == [i for i, op in enumerate(base.issues) if op == "SHIFT_IN"]
    assert r.line == base.line and r.owned == base.owned


@pytest.mark.parametrize("ident, data", RX_VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_the_fifo_receiver_with_the_run_test_is_an_eight_clock_one(ident, data):
    """experiments/can/can_rx_bits_C.asm at 8 clocks a bit, where the tree
    needed 9: bit 0 of the 42 bytes is the destuffed stream, the ACK lands,
    one byte in the FIFO at most with a prompt host, no stall inside the
    frame; the same bytes can_rx_bits.asm gives at 9."""
    r, tx = run_rx(EXPERIMENTS / "can_rx_bits_C.asm", ident, [data], bit=BIT)
    assert [byte & 1 for byte in r.received] == frame_bits(ident, [data]) and len(r.received) == 42
    assert tx.acked is True and r.rx_peak == 1 and not any(r.stalls[AT + 1 :])
    base, _ = run_rx(ROOT / "programs" / "can_rx_bits.asm", ident, [data], bit=BITS_BIT)
    assert r.received == base.received


def test_the_receivers_with_the_run_test_by_the_numbers():
    """34 words for 56 on the pins, a 12-word cell for 23; 27 for 57 through
    the FIFO, a 9-word cell for 24, and 8 clocks a bit for 9; the decision
    two cycles after the sample where the tree took five and six; the
    sample on the sixth clock still, and the host still bound to four bit
    times, 32 cycles now."""
    pins, fifo = load_program(EXPERIMENTS / "can_rx_destuff_C.asm"), load_program(EXPERIMENTS / "can_rx_bits_C.asm")
    assert (len(pins), len(set(pins)), len(fifo), len(set(fifo))) == (34, 26, 27, 21)
    r, _ = run_rx(EXPERIMENTS / "can_rx_bits_C.asm", IDENT, [0x5A], bit=BIT)
    samples = [i for i, op in enumerate(r.issues) if op == "SHIFT_IN"]
    assert [b - a for a, b in zip(samples[1:], samples[2:])] == [BIT] * (len(samples) - 2)
    first = AT + RX_SAMPLE + 1
    for sleep, fine in ((4, True), (5, False)):
        def host(cpu, received, sleep=sleep):
            if cpu.cycle >= first + sleep * BIT and cpu.rx_fifo:
                received.append(cpu.rx_fifo.pop(0))
        r, _ = run_rx(EXPERIMENTS / "can_rx_bits_C.asm", IDENT, [0x5A], bit=BIT, drain=False, host=host)
        assert (not any(r.stalls[AT + 1 :]) and [b & 1 for b in r.received] == frame_bits(IDENT, [0x5A])) == fine, f"asleep {sleep} bit times"
