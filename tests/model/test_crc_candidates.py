"""The CRC state candidates: docs/crc-candidates.md.

The CRC baselines (docs/crc-baselines.md) left one wall, the width of the
state: in_shift_reg is the eight bits a program both writes and reads, and
CRC-15 wants fifteen, thirty in the form the core can execute, since every
input bit takes a slot beside its feedback bit. RX left the same wall from
the other side: the raw history the run test reads and the destuffed data
the host wants cannot share the one register. So this round compares state
architectures, not CRC opcodes, on the model only
(experiments/crc/candidates.py):

  W16, W32  in_shift_reg carried on: the bit that leaves its wire end goes
            into a second stage, 8 or 24 bits more of the sample's history,
            and SKIP's index reaches them through the bits its shape rejects
  Pin8      SKIP_PIN pin, level: the pad as a condition, no shift, no slot
  Pin16     both: the window the input does not enter, at sixteen bits
  Lanes     a second in_shift_reg, lane 1: SHIFT_IN1, SHIFT_IN01 (both lanes
            from one sample), SKIP1, PUSH1
  Acc       a 16-bit accumulator with a 16-bit polynomial: ACC_IN pin shifts
            the pad in with the polynomial's feedback, ACC_OUT pin puts its
            top bit out, ACC_PUSH hands a byte to the host, ACC_LOAD takes a
            polynomial byte from shift_reg

What each has to show: the words it adds and none changed, every program
the same; its own semantics on every corner; CRC-15 against the oracle where
it fits and the widest CRC it holds where it does not; the destuffing
receiver handing the host bytes at eight clocks a bit where it can; and the
numbers for the table, words, cycles a bit, state."""

import importlib.util
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("crc_candidates", ROOT / "experiments" / "crc" / "candidates.py")
candidates = importlib.util.module_from_spec(_spec)
sys.modules["crc_candidates"] = candidates
_spec.loader.exec_module(candidates)
CANDIDATES, Variant = candidates.CANDIDATES, candidates.Variant
assemble_candidate, load_candidate, listing = candidates.assemble, candidates.load_program, candidates.listing

from cpu import CPU, LINE_RE, Instruction, decode, encode, load_isa, load_program  # noqa: E402
from test_can import BIT, GAP, IDENT, PROGRAMS, Glitch, before_the_accumulator, bits_to_int, frame_bits  # noqa: E402
from test_can_rx import AT, RX_SAMPLE, frame_on_the_bus, run_rx, stuff_positions  # noqa: E402
from test_crc import CRC4, VECTORS, bits_of, crc  # noqa: E402

ISA = candidates.can.round_isa()  # the ISA the round ran on: the accumulator came after
EXPERIMENTS = ROOT / "experiments" / "crc"
CRC_PIN = 1  # the pin every CRC program here puts the CRC's bits on, MSB first, one per run of the `crc` body
ZERO_PIN = 3  # the pin the tree forms hold at 0 and sample for the feedback the CRC's emission forces to 0
POLY15, POLY8 = 0x4599, 0x07  # CAN's, and x^8 + x^2 + x + 1 for the widest CRC the eight-bit shapes hold
# name -> (candidate, polynomial, width, new words the candidate takes)
NEW_WORDS = {"W16": 512, "W32": 1536, "Pin8": 256, "Pin16": 768, "Lanes": 3104, "Acc": 320}
PROGRAMS_CRC = {
    "crc15_w32": ("W32", POLY15, 15),
    "crc15_pin16": ("Pin16", POLY15, 15),
    "crc15_acc": ("Acc", POLY15, 15),
    "crc8_w16": ("W16", POLY8, 8),
    "crc8_pin8": ("Pin8", POLY8, 8),
    "crc8_lanes": ("Lanes", POLY8, 8),
}
RX_VECTORS = ((0x5A3, 0x5A), (0x7FF, 0xFF), (0x000, 0x00), (0x07C, 0x00), (0x555, 0xAA), (0x123, 0x01))


def cpu_of(tag, program=(), **kw):
    cls = CANDIDATES[tag]
    return cls(list(program) or [0, 0, 0, 0], **kw)


def word(tag, source):
    return assemble_candidate(source, CANDIDATES[tag])


@pytest.fixture(params=sorted(CANDIDATES), ids=lambda t: f"candidate {t}")
def tag(request):
    return request.param


# --- the words -------------------------------------------------------------------------------


def test_the_new_words_as_written():
    """The encodings: a far SKIP is SKIP's opcode with the flag clear and
    the index's high part in bits 6:4, which SKIP rejects; SKIP1 is bits
    6:4 = 001 on the lanes; the pin test and the accumulator's words sit in
    NOP's hole, bits 7:5 = 011 and 001; the lanes' shifts and push take the
    spare bit of their words."""
    assert word("W16", "SKIP 12, 1") == [0xC019] and word("W16", "SKIP 3, 0  1, 1") == [0xC0B6]
    assert word("W32", "SKIP 21, 0 [2]") == [0xC22A] and word("W32", "SKIP 31, 1") == [0xC03F]
    assert word("Lanes", "SKIP1 3, 0") == [0xC016] and word("Lanes", "SHIFT_IN1 1") == [0x2007]
    assert word("Lanes", "SHIFT_IN01 0") == [0x2001] and word("Lanes", "PUSH1") == [0x4003] and word("Lanes", "PUSH1 2, 1") == [0x40D3]
    assert word("Pin8", "SKIP_PIN 2, 1") == [0x0065] and word("Pin16", "SKIP_PIN 0, 0 [1]") == [0x0160]
    assert word("Acc", "ACC_IN 0") == [0x0020] and word("Acc", "ACC_OUT 1") == [0x002A]
    assert word("Acc", "ACC_PUSH") == [0x0030] and word("Acc", "ACC_LOAD [3]") == [0x0338]
    for tag, bad in (("W16", "SKIP 16, 0"), ("W32", "SKIP 32, 0"), ("W16", "SKIP 9, 0  1, 1"), ("Lanes", "SKIP1 8, 0"),
                     ("Lanes", "SKIP 8, 0"), ("Pin8", "SKIP_PIN 4, 0"), ("Acc", "ACC_IN 0, 1, 1"), ("Pin8", "SKIP 8, 0")):
        with pytest.raises(SyntaxError):
            word(tag, bad)


def test_each_candidate_takes_rejected_words_only(tag):
    """Every 16-bit word decoded on the ISA and on the candidate: what was an
    instruction is the same instruction, the candidate's own words were
    rejected and are counted, the rest are rejected still."""
    cls = CANDIDATES[tag]
    new = 0
    for w in range(1 << 16):
        try:
            was = decode(w, ISA)
        except ValueError:
            was = None
        try:
            now = cls.decode(w)
        except ValueError:
            now = None
        if was is not None:
            assert now == was, f"word {w:#06x} changed meaning under {tag}"
        elif now is not None:
            assert now.op not in ISA["instructions"] or now.op == "SKIP", f"word {w:#06x}: {now}"
            new += 1
    assert new == NEW_WORDS[tag]


def test_every_program_assembles_to_the_same_words(tag):
    """programs/*.asm and the CRC-4 program, word for word, on the candidate's assembler; the accumulator's came after the round."""
    cls = CANDIDATES[tag]
    for path in before_the_accumulator() + [CRC4]:
        assert assemble_candidate(path.read_text(), cls) == load_program(path, ISA), path.name


# --- the wide register -----------------------------------------------------------------------


def reference_ages(samples, n):
    """The n newest samples, newest first, the register's ages 0..n - 1; None past the history."""
    return [samples[-1 - i] if i < len(samples) else None for i in range(n)]


@pytest.mark.parametrize("tag, width", (("W16", 16), ("W32", 32), ("Pin16", 16)))
@pytest.mark.parametrize("shift_dir", (0, 1))
def test_the_wide_register_carries_the_history_on(tag, width, shift_dir):
    """After every SHIFT_IN, the register's ages: 0..7 are in_shift_reg as
    ever, bit 0 the newest MSB first and bit 7 LSB first, and 8..width - 1
    are the samples that left it, the eighth newest at 8, in either
    direction; a SKIP on any index steps over the next word exactly when
    that age holds the level, SKIP 0..7 naming the register's bit as ever,
    which is the age MSB first; PUSH hands the host in_shift_reg, the newest
    eight; the run test reads the newest n as ever. Reset is all zeros."""
    rng = random.Random(width + shift_dir)
    cls = CANDIDATES[tag]
    samples = []
    cpu = cls([0], gpio_in=0)
    cpu.shift_dir = shift_dir
    assert cpu.ages(width) == [0] * width
    for step in range(3 * width):
        bit = rng.randrange(2)
        cpu.gpio_in[0] = bit
        cpu.program = assemble_candidate("SHIFT_IN 0", cls)
        cpu.pc, cpu.halted = 0, False
        cpu.step()
        samples.append(bit)
        expect = [b if b is not None else 0 for b in reference_ages(samples, width)]
        assert cpu.ages(width) == expect, f"after sample {step}"
        for i in range(8):
            assert (cpu.in_shift_reg >> i) & 1 == expect[7 - i if shift_dir == 0 else i]
        for index in rng.sample(range(width), 6):
            level = rng.randrange(2)
            probe = cls(assemble_candidate(f"SKIP {index}, {level}\nNOP\nNOP", cls))
            probe.shift_dir, probe.in_shift_reg, probe.ext = shift_dir, cpu.in_shift_reg, cpu.ext
            probe.step()
            held = expect[index] if index >= 8 or shift_dir else expect[7 - index]  # SKIP 0..7 is a register bit, as ever
            assert probe.pc == (2 if held == level else 1), f"SKIP {index}, {level} after sample {step}"
    push = cls(assemble_candidate("PUSH", cls))
    push.shift_dir, push.in_shift_reg, push.ext = shift_dir, cpu.in_shift_reg, cpu.ext
    push.step()
    assert push.rx_fifo == [cpu.in_shift_reg]
    for n in range(1, 9):
        assert list(cpu.newest(n)) == list(reversed(reference_ages(samples, n)))


def test_a_far_skip_holds_its_delay_and_restart_clears_the_stage():
    """SKIP 12, 1 [3] decides on its last cycle from the register as it was
    when it issued, as SKIP does; a restart is the reset for the second
    stage as for the first."""
    cls = CANDIDATES["W16"]
    for taken in (True, False):
        cpu = cls(assemble_candidate("SKIP 12, 1 [3]\nNOP\nNOP\nNOP", cls))
        cpu.shift_dir, cpu.ext = 1, 0x10 if taken else 0xEF
        for _ in range(3):
            cpu.step()
            assert cpu.pc == 0
        cpu.step()
        assert cpu.pc == (2 if taken else 1)
    cpu.restart()
    assert (cpu.ext, cpu.in_shift_reg, cpu.pc) == (0, 0, 0)


# --- the pin test ----------------------------------------------------------------------------


@pytest.mark.parametrize("tag", ("Pin8", "Pin16"))
def test_the_pin_test_reads_the_pad_as_it_issues_and_moves_nothing(tag):
    """SKIP_PIN pin, level steps over the next word when gpio_in[pin] held
    `level` as the word issued, the way SHIFT_IN samples; a change during
    its delay is not seen; the register, the pins and the FIFOs are
    untouched, so the input costs no slot."""
    cls = CANDIDATES[tag]
    for pin in range(4):
        for level in (0, 1):
            for delay in (0, 2):
                cpu = cls(assemble_candidate(f"SKIP_PIN {pin}, {level} [{delay}]\nNOP\nNOP\nNOP", cls), gpio_in=1 - level)
                cpu.gpio_in[pin] = level
                cpu.in_shift_reg = 0xA5
                cpu.step()
                cpu.gpio_in[pin] = 1 - level  # too late: the word sampled as it issued
                for _ in range(delay):
                    assert cpu.pc == 0
                    cpu.step()
                assert cpu.pc == 2 and cpu.in_shift_reg == 0xA5 and cpu.rx_fifo == []
                cpu = cls(assemble_candidate(f"SKIP_PIN {pin}, {level}\nNOP\nNOP", cls), gpio_in=1 - level)
                cpu.step()
                assert cpu.pc == 1


# --- the lanes -------------------------------------------------------------------------------


@pytest.mark.parametrize("shift_dir", (0, 1))
def test_the_second_lane_is_a_register_of_its_own(shift_dir):
    """SHIFT_IN fills lane 0 as ever and leaves lane 1 alone; SHIFT_IN1
    fills lane 1 alone; SHIFT_IN01 puts the one sample into both; SKIP1
    reads lane 1's bit, SKIP lane 0's; PUSH1 hands the host lane 1 and
    keeps it; the run test reads lane 0. Both directions; reset clears both."""
    rng = random.Random(shift_dir)
    cls = CANDIDATES["Lanes"]
    lanes = ([], [])
    cpu = cls([0], gpio_in=0)
    cpu.shift_dir = shift_dir
    for step in range(40):
        bit, kind = rng.randrange(2), rng.choice(("SHIFT_IN", "SHIFT_IN1", "SHIFT_IN01"))
        cpu.gpio_in[2] = bit
        cpu.program, cpu.pc, cpu.halted = assemble_candidate(f"{kind} 2", cls), 0, False
        cpu.step()
        if kind != "SHIFT_IN1":
            lanes[0].append(bit)
        if kind != "SHIFT_IN":
            lanes[1].append(bit)
        for lane, reg in ((0, cpu.in_shift_reg), (1, cpu.lane)):
            expect = [b if b is not None else 0 for b in reference_ages(lanes[lane], 8)]
            assert [(reg >> (7 - i if shift_dir == 0 else i)) & 1 for i in range(8)] == expect, f"lane {lane} after {step}"
        index, level = rng.randrange(8), rng.randrange(2)
        for op, reg in (("SKIP", cpu.in_shift_reg), ("SKIP1", cpu.lane)):
            probe = cls(assemble_candidate(f"{op} {index}, {level}\nNOP\nNOP", cls))
            probe.shift_dir, probe.in_shift_reg, probe.lane = shift_dir, cpu.in_shift_reg, cpu.lane
            probe.step()
            assert probe.pc == (2 if (reg >> index) & 1 == level else 1), f"{op} {index}, {level}"
    for op, expect in (("PUSH", cpu.in_shift_reg), ("PUSH1", cpu.lane)):
        probe = cls(assemble_candidate(op, cls))
        probe.in_shift_reg, probe.lane = cpu.in_shift_reg, cpu.lane
        probe.step()
        assert probe.rx_fifo == [expect] and (probe.in_shift_reg, probe.lane) == (cpu.in_shift_reg, cpu.lane)
    assert list(cpu.newest(5)) == list(reversed(reference_ages(lanes[0], 5)))
    cpu.restart()
    assert (cpu.in_shift_reg, cpu.lane) == (0, 0)


def test_push1_stalls_on_a_full_fifo_with_its_side_effect():
    """PUSH1 waits while the RX FIFO is full, its side effect with it, and
    lands both when the host makes room, as PUSH does."""
    cls = CANDIDATES["Lanes"]
    cpu = cls(assemble_candidate("PUSH1 2, 0\nNOP", cls), rx_depth=4)
    cpu.rx_fifo, cpu.lane = [1, 2, 3, 4], 0x96
    for _ in range(3):
        cpu.step()
        assert cpu.stalled and cpu.pc == 0 and cpu.gpio[2] == 1
    cpu.rx_fifo.pop(0)
    cpu.step()
    assert not cpu.stalled and cpu.pc == 1 and cpu.gpio[2] == 0 and cpu.rx_fifo == [2, 3, 4, 0x96]


# --- the accumulator -------------------------------------------------------------------------


def acc_after(bits, poly, width):
    """The accumulator's value after `bits` with the polynomial left-aligned:
    the spec's register in bits 15 down to 16 - width, zeros below. The
    register runs as a 16-bit LFSR whose top bit is the CRC's top bit."""
    return crc(bits, poly, width) << (16 - width)


def load_poly(cls, poly, width):
    """A program that loads the polynomial left-aligned, low byte first, and its two host bytes."""
    aligned = (poly << (16 - width)) & 0xFFFF
    return "PULL\nACC_LOAD\nPULL\nACC_LOAD\n", [aligned & 0xFF, aligned >> 8]


@pytest.mark.parametrize("poly, width", ((POLY15, 15), (POLY8, 8), (0x3, 4), (0x1021, 16), (0x1, 1)))
def test_the_accumulator_is_the_specs_register_for_any_polynomial(poly, width):
    """ACC_IN pin: f = acc[15] ^ gpio_in[pin], acc <- (acc << 1) ^ (f ? poly
    : 0), the direct form; with the polynomial left-aligned it is the
    spec's register of any width to 16 in the top bits, CAN's CRC-15, an
    8-bit one, the 4-bit one, CRC-16-CCITT's, and x + 1, the parity bit,
    checked against the oracle on random streams of every length to 40."""
    rng = random.Random(poly)
    cls = CANDIDATES["Acc"]
    head, poly_bytes = load_poly(cls, poly, width)
    for n in range(1, 41):
        bits = [rng.randrange(2) for _ in range(n)]
        cpu = cls(assemble_candidate(head + "ACC_IN 2\n" * n, cls), tx_data=poly_bytes)
        cpu.run_cycles(4)
        assert cpu.poly == (poly << (16 - width)) & 0xFFFF
        for bit in bits:
            cpu.gpio_in[2] = bit
            cpu.step()
        assert cpu.acc == acc_after(bits, poly, width), bits
        if width == 1:
            assert cpu.acc >> 15 == sum(bits) % 2, "the parity"


def test_acc_out_emits_the_top_bit_and_acc_push_the_low_byte():
    """ACC_OUT pin: gpio[pin] <- acc[15], then acc <- acc << 1: fifteen of
    them after CAN's polynomial and a stream put the CRC on the pin MSB
    first, the order the frame sends it. ACC_PUSH: the RX FIFO takes
    acc[7:0] and acc <- acc >> 8, so two hand the host the low byte then
    the high, and after them the accumulator is clear; it stalls while the
    FIFO is full, as PUSH does. ACC_LOAD: poly <- {shift_reg, poly[15:8]}."""
    cls = CANDIDATES["Acc"]
    bits = bits_of([0x12, 0x34, 0x56])
    value = crc(bits, POLY15, 15)
    cpu = cls(assemble_candidate("ACC_OUT 0\n" * 15 + "ACC_OUT 2\n", cls))
    cpu.acc = value << 1
    seen = []
    for _ in range(15):
        cpu.step()
        seen.append(cpu.gpio[0])
    assert bits_to_int(seen) == value and cpu.acc == 0
    cpu.step()
    assert cpu.gpio[2] == 0
    cpu = cls(assemble_candidate("ACC_PUSH\nACC_PUSH\nACC_PUSH", cls), rx_depth=4)
    cpu.acc = 0x8B32
    cpu.rx_fifo = [0, 0, 0, 0]
    cpu.step()
    assert cpu.stalled and cpu.acc == 0x8B32
    cpu.rx_fifo = []
    cpu.run_cycles(3)
    assert cpu.rx_fifo == [0x32, 0x8B, 0x00] and cpu.acc == 0
    cpu = cls(assemble_candidate("PULL\nACC_LOAD\nPULL\nACC_LOAD", cls), tx_data=[0x32, 0x8B])
    cpu.run_cycles(2)
    assert cpu.poly == 0x3200
    cpu.run_cycles(2)
    assert cpu.poly == 0x8B32
    cpu.restart()
    assert (cpu.acc, cpu.poly) == (0, 0)


def test_the_accumulator_with_polynomial_1_is_a_shift_register_for_sixteen_bits():
    """With poly = 0x0001, ACC_IN shifts the sample into bit 0 and the bits
    walk up, an MSB-first stream register, until the first sample reaches
    bit 15 and feeds back: sixteen bits from clear, and ACC_PUSH clears the
    low byte's worth every eight, so a byte at a time it never fills. That
    is how the accumulator can hold RX's destuffed data."""
    rng = random.Random(1)
    cls = CANDIDATES["Acc"]
    bits = [rng.randrange(2) for _ in range(24)]
    cpu = cls(assemble_candidate("ACC_IN 0\n" * 24, cls))
    cpu.poly = 0x0001
    for k, bit in enumerate(bits):
        cpu.gpio_in[0] = bit
        cpu.step()
        if k < 16:
            assert cpu.acc == bits_to_int(bits[: k + 1]), f"bit {k}"
    assert cpu.acc != bits_to_int(bits) & 0xFFFF, "the seventeenth sample met the first, fed back"
    cpu = cls(assemble_candidate(("ACC_IN 0\n" * 8 + "ACC_PUSH\n") * 3, cls))
    cpu.poly = 0x0001
    for k, bit in enumerate(bits):
        cpu.gpio_in[0] = bit
        cpu.step()
        if k % 8 == 7:
            cpu.step()
    assert cpu.rx_fifo == [bits_to_int(bits[8 * k : 8 * k + 8]) for k in range(3)] and cpu.acc == 0


# --- the CRC programs against the oracle -----------------------------------------------------


def label_address(source, label):
    address = 0
    for line in source.splitlines():
        line = line.split("#", 1)[0].strip()
        m = LINE_RE.match(line) if line else None
        if m and m["label"] == label:
            return address
        if m and m["op"]:
            address += 1
    raise ValueError(f"no label {label}")


def run_crc(name, bytes_, poly_bytes=()):
    """The program with the host's bytes queued, the polynomial's first where
    the candidate takes one, the pads read back on every pin as the chip's
    do; the CRC's bits are pin 1's level as the REPEAT that closes the
    `crc` body issues, one per run of it. Returns the CPU, the bits, and
    the op that issued each cycle."""
    tag = PROGRAMS_CRC[name][0]
    cls = CANDIDATES[tag]
    source = (EXPERIMENTS / f"{name}.asm").read_text()
    words = assemble_candidate(source, cls)
    start = label_address(source, "crc")
    repeat = next(a for a, w in enumerate(words) if cls.decode(w).op == "REPEAT" and a - cls.decode(w).args[0] == start)
    cpu = cls(words, tx_data=list(poly_bytes) + list(bytes_))
    emitted, issues = [], []
    while not cpu.halted:
        issuing = cpu.counter == 0
        op = cls.decode(cpu.program[cpu.pc]).op if issuing else None
        if issuing and cpu.pc == repeat:
            emitted.append(cpu.gpio[CRC_PIN])
        cpu.step()
        issues.append(None if cpu.stalled else op)
        for pin in range(4):
            cpu.gpio_in[pin] = cpu.gpio[pin]
        assert cpu.cycle < 6000, "did not halt"
    return cpu, emitted, issues


def poly_bytes_of(name):
    tag, poly, width = PROGRAMS_CRC[name]
    if tag != "Acc":
        return []
    return load_poly(CANDIDATES[tag], poly, width)[1]


@pytest.fixture(params=sorted(PROGRAMS_CRC), ids=lambda n: n)
def program(request):
    return request.param


@pytest.mark.parametrize("bytes_", VECTORS, ids=lambda v: "".join(f"{b:02x}" for b in v))
def test_the_crc_of_four_host_bytes_leaves_on_the_pin(program, bytes_):
    """Four host bytes go out on pin 0 MSB first and come back through the
    pad as every CAN bit does; the CRC of the 32 bits then leaves on pin 1,
    MSB first, one bit per run of the `crc` body, as the oracle computes
    it; halted, the FIFOs empty, no stall inside."""
    tag, poly, width = PROGRAMS_CRC[program]
    cpu, emitted, issues = run_crc(program, bytes_, poly_bytes_of(program))
    assert len(emitted) == width and bits_to_int(emitted) == crc(bits_of(bytes_), poly, width)
    assert cpu.halted and cpu.tx_fifo == [] and not cpu.stalled


def test_the_crc_programs_across_random_streams(program):
    """Two hundred random four-byte streams, each with the oracle's CRC on the pin."""
    rng = random.Random(len(program))
    tag, poly, width = PROGRAMS_CRC[program]
    for _ in range(200):
        bytes_ = [rng.randrange(256) for _ in range(4)]
        _, emitted, _ = run_crc(program, bytes_, poly_bytes_of(program))
        assert bits_to_int(emitted) == crc(bits_of(bytes_), poly, width), bytes_


def test_the_accumulators_crc_reaches_the_host_as_two_bytes():
    """crc15_acc_bytes.asm: the same computation with two ACC_PUSHes in
    place of the emission: the CRC's low byte then its high, left-aligned,
    for the host. The check value of the catalogue, "123456789", 0x059E,
    is nine bytes, more than the program holds cells for: the four-byte
    form on the first four and the oracle on the nine."""
    cls = CANDIDATES["Acc"]
    source = (EXPERIMENTS / "crc15_acc_bytes.asm").read_text()
    words = assemble_candidate(source, cls)
    for bytes_ in list(VECTORS[:6]) + [(0x31, 0x32, 0x33, 0x34)]:
        cpu = cls(words, tx_data=poly_bytes_of("crc15_acc") + list(bytes_))
        while not cpu.halted:
            cpu.step()
            for pin in range(4):
                cpu.gpio_in[pin] = cpu.gpio[pin]
            assert cpu.cycle < 1000
        value = crc(bits_of(bytes_), POLY15, 15) << 1
        assert cpu.rx_fifo == [value & 0xFF, value >> 8] and cpu.acc == 0
    assert crc(bits_of(b"123456789"), POLY15, 15) == 0x059E


def test_the_widest_crc_each_shape_holds():
    """Where CRC-15 does not fit, the assembler says so on the tap that is
    out of reach: the window's fifteenth feedback bit is at age 29 in the
    interleaved form and 14 in the pin form, and a lane or a sixteen-bit
    stage stops at 15 and 7. The base ISA stops at 7, CRC-4."""
    for tag, index, op in (("W16", 29, "SKIP"), ("Lanes", 14, "SKIP1"), ("Pin8", 14, "SKIP")):
        with pytest.raises(SyntaxError):
            word(tag, f"{op} {index}, 0")
    word("W32", "SKIP 29, 0") and word("Pin16", "SKIP 14, 0") and word("Lanes", "SKIP1 7, 0") and word("W16", "SKIP 15, 0")
    with pytest.raises(SyntaxError):
        assemble_candidate("SKIP 8, 0", Variant)


# --- RX: destuffed bytes to the host --------------------------------------------------------


RX_PROGRAMS = {"can_rx_bytes_lanes": "Lanes", "can_rx_bytes_acc": "Acc"}
DATA_BITS = 42  # a DLC 1 frame's destuffed bits, the SOF to the CRC's last


def rx_bytes(name, ident, data, bit=BIT, host=None, drain=True, glitch=None):
    """The receiver on its candidate against the bench transmitter at `bit`
    clocks a bit; the accumulator's takes its polynomial from the host."""
    cls = CANDIDATES[RX_PROGRAMS[name]]
    tx = [0x01, 0x00] if RX_PROGRAMS[name] == "Acc" else []
    cpu = cls(load_candidate(name, cls), gpio_in=1, tx_data=tx)
    return run_rx(None, ident, [data], bit=bit, host=host, drain=drain, glitch=glitch, cpu=cpu)


def expected_bytes(name, ident, data):
    """The destuffed stream cut into bytes from the SOF, MSB first; the sixth
    byte holds the last two bits, and above them what the lane kept from
    the byte before, or nothing where the accumulator was cleared."""
    stream = frame_bits(ident, [data])
    out = [bits_to_int(stream[8 * k : 8 * k + 8]) for k in range(5)]
    tail = bits_to_int(stream[40:42])
    out.append(((out[4] << 2) & 0xFF) | tail if RX_PROGRAMS[name] == "Lanes" else tail)
    return out


@pytest.fixture(params=sorted(RX_PROGRAMS), ids=lambda n: n.removeprefix("can_rx_bytes_"))
def rx(request):
    return request.param


@pytest.mark.parametrize("ident, data", RX_VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_destuffed_bytes_reach_the_host_at_eight_clocks_a_bit(rx, ident, data):
    """RX6 on a candidate: the raw history in in_shift_reg for the run test,
    the data bit into the second register, a stuff bit into the first alone,
    and after every eight data bits the second register to the host: the
    frame's 42 bits as five bytes and two bits, at eight clocks a bit, the
    ACK landed, no stall, one byte in the FIFO at most with a prompt host."""
    r, tx = rx_bytes(rx, ident, data)
    assert r.received == expected_bytes(rx, ident, data)
    assert tx.acked is True and r.rx_peak == 1 and not any(r.stalls[AT + 1 :])
    assert r.cpu.halted


def test_the_receivers_sample_point_and_the_hosts_slack(rx):
    """A probe on a recessive bit at each clock: the raw sample and the data
    sample are both the sixth clock's level on the lanes, one SHIFT_IN01;
    with the accumulator the data sample is its own word, a clock after,
    so a probe on the sixth clock touches the history alone and one on the
    seventh the data alone. And the host: a byte every 64 cycles into a
    four-deep FIFO and six a frame, so the fifth is the one that can find it
    full: for this frame, two stuff bits inside, a host asleep for 33 bit
    times after the first byte is fine and one asleep for 34 stalls the
    receiver inside the frame. Eight times the FIFO receiver's slack, a
    byte where it had a bit."""
    ident, data = IDENT, 0x5A
    bits, slot = frame_on_the_bus(ident, [data])
    k = next(k for k in range(8, 30) if bits[k] == 1 and len(set(bits[k - 4 : k])) == 2 and k not in stuff_positions(ident, [data]))
    j = k - sum(1 for s in stuff_positions(ident, [data]) if s < k)
    expect = expected_bytes(rx, ident, data)
    flipped = list(expect)
    flipped[j // 8] ^= 1 << (7 - j % 8)
    for p in range(BIT):
        r, _ = rx_bytes(rx, ident, data, glitch=Glitch(AT + k * BIT + p))
        data_hit = p == RX_SAMPLE - 1 + (RX_PROGRAMS[rx] == "Acc")
        assert r.received == (flipped if data_hit else expect), f"pulse on clock {p + 1}"
    first = AT + RX_SAMPLE + 8 * BIT
    for sleep, fine in ((33, True), (34, False)):
        def host(cpu, received, sleep=sleep):
            if cpu.cycle >= first + sleep * BIT and cpu.rx_fifo:
                received.append(cpu.rx_fifo.pop(0))
        r, _ = rx_bytes(rx, ident, data, drain=False, host=host)
        assert (not any(r.stalls[AT + 1 :]) and r.received == expect) == fine, f"asleep {sleep} bit times"


# --- by the numbers --------------------------------------------------------------------------


def cells_of(issues, op="SHIFT_OUT", between="PULL"):
    """The cycles between one `op` and the next with no `between` inside."""
    outs = [i for i, o in enumerate(issues) if o == op]
    breaks = [i for i, o in enumerate(issues) if o == between]
    return {b - a for a, b in zip(outs, outs[1:]) if not any(a < p < b for p in breaks)}


# program -> (words, distinct, cycles an input bit shortest, longest, cycles a CRC bit shortest, longest)
NUMBERS = {
    "crc15_w32": (180, 90, 13, 20, 12, 17),
    "crc15_pin16": (171, 87, 12, 19, 10, 15),
    "crc15_acc": (23, 8, 3, 3, 2, 2),
    "crc8_w16": (100, 46, 9, 12, 8, 11),
    "crc8_pin8": (91, 43, 8, 11, 6, 9),
    "crc8_lanes": (100, 46, 9, 12, 8, 11),
}


def test_the_crc_programs_by_the_numbers(program):
    """The words, and the cycles an input bit and a CRC bit take by their
    paths, over the vectors and a hundred random streams. The tree forms:
    CRC-15's parity of eight terms as two paths through SKIPs, 31 words of
    a 35-word cell, 12 to 20 cycles an input bit by the crosses; CRC-8's of
    four, 8 to 12; the accumulator: two words and the REPEAT, three cycles,
    and two a CRC bit."""
    rng = random.Random(2)
    tag, poly, width = PROGRAMS_CRC[program]
    words = load_candidate(program, CANDIDATES[tag])
    assert (len(words), len(set(words))) == NUMBERS[program][:2], (len(words), len(set(words)))
    inputs, outputs = set(), set()
    for bytes_ in [(0, 0, 0, 0), (0xFF,) * 4] + [tuple(rng.randrange(256) for _ in range(4)) for _ in range(100)]:
        _, _, issues = run_crc(program, bytes_, poly_bytes_of(program))
        inputs |= cells_of(issues)
        reps = [i for i, o in enumerate(issues) if o == "REPEAT"]
        outputs |= {b - a for a, b in zip(reps[-width:], reps[-width + 1 :])}
    assert (min(inputs), max(inputs), min(outputs), max(outputs)) == NUMBERS[program][2:], (min(inputs), max(inputs), min(outputs), max(outputs))


RX_NUMBERS = {"can_rx_bytes_lanes": (82, 46), "can_rx_bytes_acc": (96, 48)}


def test_the_receivers_by_the_numbers(rx):
    """The words: an eight-cell body with the push in the eighth, run five
    times, two cells and a push for the last two bits, the ACK and the gap;
    every bus bit sampled eight clocks apart, stuff bits too; six pushes."""
    words = load_candidate(rx, CANDIDATES[RX_PROGRAMS[rx]])
    assert (len(words), len(set(words))) == RX_NUMBERS[rx], (len(words), len(set(words)))
    r, _ = rx_bytes(rx, IDENT, 0x5A)
    samples = [i for i, op in enumerate(r.issues) if op in ("SHIFT_IN", "SHIFT_IN01")]
    assert samples[1] == AT + RX_SAMPLE and [b - a for a, b in zip(samples[1:], samples[2:])] == [BIT] * (len(samples) - 2)
    pushes = [i for i, op in enumerate(r.issues) if op in ("PUSH1", "ACC_PUSH")]
    # a byte every eight data bits, 64 cycles, 72 where a stuff bit fell inside; the last two bits 16 after
    assert [b - a for a, b in zip(pushes, pushes[1:])] == [64, 72, 64, 72, 16]
