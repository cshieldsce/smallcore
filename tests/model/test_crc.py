"""CRC-15 on the current ISA, the three baselines: docs/crc-baselines.md.

The question, kept apart from the frame: given a known bit stream, the
SOF, the identifier, the control field, the DLC and the data, can the core
as it is produce CAN's CRC-15 over it? Python is the oracle. Before any
candidate, what exactly fails is classified: the width of the state, the
XOR, getting the sent bit into the computation, or writing the state back.

The state a program can hold is pinned first, by running every word of the
ISA from random state and recording what it changed and what it read
(`test_what_each_instruction_writes`, `test_what_each_instruction_reads`):
in_shift_reg is the only state a program both writes and reads, eight bits,
written one at a time at one end by SHIFT_IN and read into the pc by SKIP,
one bit, and since 2026-09-28 by the run tests, the newest n; the pins are
written by SET and read by nothing but a SHIFT_IN from the pad. So a bit moves from the register to a pin only
through the pc, and every XOR is control flow. That was the ISA the
baselines ran on; since 2026-09-28 the accumulator, acc and its polynomial,
is the second state a program writes and reads, and the census counts it.

Then the three baselines. One, the host's CRC (stage 5A as it stands): the
computation is separable from the wire. Two, the widest CRC the current ISA
can compute, `experiments/crc/crc4_lfsr.asm`: the spec's register, shift
then XOR the polynomial in at the taps, cannot be kept in in_shift_reg,
because a bit in the middle of it cannot be written and rebuilding the
register through a pin needs the old copy to survive while the new one
shifts in, twice the width; but the same register seen from its input end
is a Fibonacci LFSR, f_t = in_t ^ XOR over the taps of the last w feedback
bits, and the shift is then the only write. Every input bit takes a slot of
the register beside its feedback bit, so eight bits of register hold four
of history: CRC-4 is the widest, and CRC-15 wants 30. Three, the CRC as
data: stage 5A's frame sends whatever CRC the host wrote, right or wrong,
with no word of its own for it."""

import random
from pathlib import Path

import pytest

from cpu import CPU, Instruction, cycles, decode, encode, load_isa, load_program
from test_can import (  # noqa: E402
    CRC_BITS, CRC_POLY, FRAME_BIT, GAP, IDENT, cells, crc15, frame_bits, frame_bytes, frame_host, run_frame, stuffed,
)

ROOT = Path(__file__).resolve().parent.parent.parent
CRC4 = ROOT / "experiments" / "crc" / "crc4_lfsr.asm"
CRC4_POLY = 0x3  # x^4 + x + 1, the ITU's; the word here is the low four bits, the x^4 implied as CAN's x^15 is
CRC4_WIDTH = 4
ISA = load_isa()
FEEDBACK_PIN = 1  # the pin crc4_lfsr.asm puts each feedback bit on, and samples back
DATA_PIN = 0  # the pin the data bit goes out on, and is sampled back from


def crc(bits, poly=CRC_POLY, width=CRC_BITS):
    """The spec's register over `bits`: shift, and XOR the polynomial in when
    the bit in and the bit out differ. CAN's with the defaults."""
    top, mask = 1 << (width - 1), (1 << width) - 1
    c = 0
    for bit in bits:
        c = ((c << 1) & mask) ^ (poly if bit != (c & top) >> (width - 1) else 0)
    return c


def feedback(bits, poly=CRC_POLY, width=CRC_BITS):
    """The same register seen from its input end: the bit fed back at each
    step, in ^ crc[width - 1], which depends on the last `width` feedback
    bits alone, f_t = in_t ^ XOR over i of poly[width - 1 - i] f_{t - 1 - i}:
    a Fibonacci LFSR, no state but the bits it shifted in."""
    f = []
    for bit in bits:
        top = 0
        for i in range(min(width, len(f))):
            if (poly >> (width - 1 - i)) & 1:
                top ^= f[-1 - i]
        f.append(bit ^ top)
    return f


def from_window(f, poly=CRC_POLY, width=CRC_BITS):
    """The register from the last `width` feedback bits: bit k is
    XOR over i <= k of poly[k - i] f_{t - 1 - i}."""
    c = 0
    for k in range(width):
        bit = 0
        for i in range(min(k + 1, len(f))):
            if (poly >> (k - i)) & 1:
                bit ^= f[-1 - i]
        c |= bit << k
    return c


def random_bits(rng, n):
    return [rng.randrange(2) for _ in range(n)]


@pytest.mark.parametrize("poly, width", ((CRC_POLY, CRC_BITS), (CRC4_POLY, CRC4_WIDTH), (0x07, 8)))
def test_the_register_is_a_function_of_its_last_feedback_bits(poly, width):
    """The spec's register and the Fibonacci form agree on every stream: the
    register after any bits is from_window of the feedback bits, so a
    program that keeps the last `width` feedback bits keeps the CRC. CAN's
    polynomial, the 4-bit one the program uses, and an 8-bit one."""
    rng = random.Random(width)
    assert crc([], poly, width) == 0 == from_window([], poly, width)
    for n in list(range(1, 2 * width + 2)) + [27, 42, 98]:
        for _ in range(40):
            bits = random_bits(rng, n)
            assert from_window(feedback(bits, poly, width), poly, width) == crc(bits, poly, width), bits
    assert crc([1] * width, poly, width) == from_window(feedback([1] * width, poly, width), poly, width)


def test_the_oracle_is_the_benchs_crc():
    """crc() with the defaults is test_can.py's crc15, on the frames' streams and the catalogue's check value."""
    for ident, data in ((0x5A3, [0x5A]), (0x7FF, [0xFF]), (0x000, [0x00])):
        bits = frame_bits(ident, data)[:-CRC_BITS]
        assert crc(bits) == crc15(bits)
    assert crc([b for byte in b"123456789" for b in ((byte >> i) & 1 for i in range(7, -1, -1))]) == 0x059E


# --- the state a program can hold ---------------------------------------------------------


FIELDS = ("pc", "shift_reg", "in_shift_reg", "gpio", "open_drain", "shift_dir", "rc", "tx_fifo", "rx_fifo", "stalled", "acc", "poly")


def state(cpu):
    return {
        "pc": cpu.pc, "shift_reg": cpu.shift_reg, "in_shift_reg": cpu.in_shift_reg, "gpio": tuple(cpu.gpio),
        "open_drain": tuple(cpu.open_drain), "shift_dir": cpu.shift_dir, "rc": cpu.rc, "tx_fifo": tuple(cpu.tx_fifo),
        "rx_fifo": tuple(cpu.rx_fifo), "stalled": cpu.stalled, "acc": cpu.acc, "poly": cpu.poly,
    }


def machine(word, rng, tx=1, rx=1):
    """One word as the program, from random state: the registers and pins
    random, `tx` bytes in the TX FIFO, `rx` in the RX FIFO, the word at pc 0
    with room after it for a SKIP to land."""
    cpu = CPU([word, 0, 0], gpio_in=0, tx_data=[rng.randrange(256) for _ in range(tx)], isa=ISA)
    cpu.shift_reg, cpu.in_shift_reg = rng.randrange(256), rng.randrange(256)
    cpu.gpio, cpu.open_drain = [rng.randrange(2) for _ in range(4)], [rng.randrange(2) for _ in range(4)]
    cpu.gpio_in, cpu.shift_dir = [rng.randrange(2) for _ in range(4)], rng.randrange(2)
    cpu.rc = rng.randrange(1, 32)
    cpu.acc, cpu.poly = rng.randrange(1 << 16), rng.randrange(1 << 16)
    cpu.rx_fifo = [rng.randrange(256) for _ in range(rx)]
    return cpu


def run_word(cpu):
    """The word to its end, or three cycles of it stalled."""
    instr = decode(cpu.program[0], ISA)
    for _ in range(cycles(instr) + 2):
        if cpu.halted:
            break
        cpu.step()
        if cpu.counter == 0 and not cpu.stalled:
            break
    return state(cpu)


_VALID = {}


def valid_words(delay=0):
    """Every word the ISA accepts with the given delay field, REPEAT with any count; decoded once."""
    if delay not in _VALID:
        found = []
        for word in range(1 << 16):
            if (word >> 8) & 0x1F != delay and word >> 13 != ISA["instructions"]["REPEAT"]["opcode"]:
                continue
            try:
                found.append((word, decode(word, ISA)))
            except ValueError:
                continue
        _VALID[delay] = found
    return _VALID[delay]


def test_what_each_instruction_writes():
    """Every valid word with no delay, run once from random state, twice:
    what it changed. in_shift_reg is written by SHIFT_IN alone; shift_reg by
    SHIFT_OUT, a shift, and PULL, a load; the pins by SET, by SHIFT_OUT, its
    own bit on pin 0, and by the side effect of any word that carries one,
    and by nothing else; the configuration by CONFIG; rc by REPEAT; the TX
    FIFO by PULL, the RX FIFO
    by PUSH; the pc goes somewhere other than the next word only for JMP,
    SKIP, the run tests and REPEAT, and only a WAIT stalls with a byte in
    each FIFO. So the
    state a program can write is in_shift_reg, one bit at one end, the four
    pins, and the configuration."""
    rng = random.Random(15)
    writers = {field: set() for field in FIELDS}
    side_effects = set()
    for word, instr in valid_words():
        for _ in range(2):
            cpu = machine(word, rng)
            before = state(cpu)
            after = run_word(cpu)
            for field in FIELDS:
                if field == "pc":
                    if after["pc"] != 1 and not after["stalled"]:
                        writers["pc"].add(instr.op)
                elif field == "stalled":
                    if after["stalled"]:
                        writers["stalled"].add(instr.op)
                elif after[field] != before[field]:
                    writers[field].add(instr.op)
                    if field == "gpio":
                        side_effects.add((instr.op, instr.side is not None or instr.op in ("SET", "SHIFT_OUT")))
    assert writers["in_shift_reg"] == {"SHIFT_IN"}
    assert writers["shift_reg"] == {"SHIFT_OUT", "PULL"}
    assert writers["gpio"] == {"SET", "SHIFT_OUT", "SHIFT_IN", "PULL", "PUSH", "WAIT", "SKIP", "CONFIG", "ACC_OUT"}
    assert all(carried or op == "ACC_OUT" for op, carried in side_effects), "a pin changes only under SET, SHIFT_OUT, ACC_OUT or a side effect"
    assert writers["acc"] == {"ACC_IN", "ACC_CRC", "ACC_OUT", "ACC_PUSH"} and writers["poly"] == {"ACC_LOAD"}
    assert writers["open_drain"] == {"CONFIG"} and writers["shift_dir"] == {"CONFIG"}
    assert writers["rc"] == {"REPEAT"}
    assert writers["tx_fifo"] == {"PULL"} and writers["rx_fifo"] == {"PUSH", "ACC_PUSH"}
    assert writers["pc"] == {"JMP", "SKIP", "SKIP_RUN", "SKIP_NORUN", "REPEAT"}
    assert writers["stalled"] == {"WAIT"}, "a byte in each FIFO: only a WAIT on the wrong level stalls"


def perturbed(cpu, field, rng):
    """The same machine with one field of its state different."""
    other = CPU(list(cpu.program), gpio_in=0, tx_data=list(cpu.tx_fifo), isa=ISA)
    other.shift_reg, other.in_shift_reg, other.gpio, other.open_drain = cpu.shift_reg, cpu.in_shift_reg, list(cpu.gpio), list(cpu.open_drain)
    other.gpio_in, other.shift_dir, other.rc, other.rx_fifo = list(cpu.gpio_in), cpu.shift_dir, cpu.rc, list(cpu.rx_fifo)
    other.acc, other.poly = cpu.acc, cpu.poly
    if field == "shift_reg":
        other.shift_reg ^= rng.randrange(1, 256)
    elif field == "in_shift_reg":
        other.in_shift_reg ^= rng.randrange(1, 256)
    elif field == "gpio":
        other.gpio[rng.randrange(4)] ^= 1
    elif field == "gpio_in":
        other.gpio_in[rng.randrange(4)] ^= 1
    elif field == "open_drain":
        other.open_drain[rng.randrange(4)] ^= 1
    elif field == "shift_dir":
        other.shift_dir ^= 1
    elif field == "rc":
        other.rc = (other.rc + rng.randrange(1, 32)) % 32 or 1
    elif field == "tx_fifo":
        other.tx_fifo[0] ^= rng.randrange(1, 256)
    elif field == "tx_empty":
        other.tx_fifo = []
    elif field == "rx_full":
        other.rx_fifo = [0] * other.rx_depth
    elif field == "acc":
        other.acc ^= rng.randrange(1, 1 << 16)
    elif field == "poly":
        other.poly ^= rng.randrange(1, 1 << 16)
    return other


READS = {
    ("in_shift_reg", "pc"): {"SKIP", "SKIP_RUN", "SKIP_NORUN"},
    ("shift_dir", "pc"): {"SKIP_RUN", "SKIP_NORUN"},  # the direction says which end of the register is the newest
    ("in_shift_reg", "rx_fifo"): {"PUSH"},
    ("shift_reg", "gpio"): {"SHIFT_OUT"},
    ("gpio_in", "in_shift_reg"): {"SHIFT_IN"},
    ("gpio_in", "stalled"): {"WAIT"},
    ("gpio_in", "pc"): {"WAIT"},
    ("gpio_in", "gpio"): {"WAIT"},  # a stalled word's side effect waits with it
    ("tx_fifo", "shift_reg"): {"PULL"},
    ("tx_empty", "stalled"): {"PULL"},
    ("tx_empty", "pc"): {"PULL"},
    ("tx_empty", "gpio"): {"PULL"},
    ("tx_empty", "shift_reg"): {"PULL"},  # and its load
    ("rx_full", "stalled"): {"PUSH", "ACC_PUSH"},
    ("rx_full", "pc"): {"PUSH", "ACC_PUSH"},
    ("rx_full", "gpio"): {"PUSH"},
    ("rx_full", "acc"): {"ACC_PUSH"},  # and its shift
    ("acc", "rx_fifo"): {"ACC_PUSH"},  # the accumulator, since 2026-09-28: the second register a program writes and reads
    ("acc", "gpio"): {"ACC_OUT"},
    ("gpio_in", "acc"): {"ACC_IN", "ACC_CRC"},
    ("poly", "acc"): {"ACC_CRC"},
    ("shift_reg", "poly"): {"ACC_LOAD"},
    ("rc", "pc"): {"REPEAT"},
    ("shift_dir", "gpio"): {"SHIFT_OUT"},
    ("shift_dir", "shift_reg"): {"SHIFT_OUT"},
    ("shift_dir", "in_shift_reg"): {"SHIFT_IN"},
}


def test_what_each_instruction_reads():
    """Every kind of word, 64 of each, run from four states and from the same
    state with one field changed: where the change shows up is what the
    word read. The whole table: SKIP and the run tests read in_shift_reg
    into the pc, the run tests under shift_dir, and PUSH reads it into the
    RX FIFO; SHIFT_OUT reads shift_reg onto a pin;
    SHIFT_IN reads a pin into in_shift_reg and WAIT reads one into a stall;
    PULL reads the TX FIFO; REPEAT reads rc; shift_dir steers the shifts;
    and what stalls a word, a pin's level or a FIFO's fullness, holds its
    side effect and its load with it. Nothing reads a pin register, and
    nothing reads in_shift_reg onto a pin: a register bit reaches a pin
    only through the pc, SKIP then SET."""
    rng = random.Random(4599)
    by_op = {}
    for word, instr in valid_words():
        by_op.setdefault(instr.op, []).append(word)
    reads = {}
    fields = ("shift_reg", "in_shift_reg", "gpio", "gpio_in", "open_drain", "shift_dir", "rc", "tx_fifo", "tx_empty", "rx_full", "acc", "poly")
    for op, words in by_op.items():
        for word in rng.sample(words, min(64, len(words))):
            for field in [f for f in fields for _ in range(4)]:  # four states each: a read that shows only sometimes still shows
                base = machine(word, rng, tx=2, rx=1)
                other = perturbed(base, field, rng)
                a, b = run_word(base), run_word(other)
                for dest in FIELDS:
                    if dest == field or (dest in ("tx_fifo", "rx_fifo") and field in ("tx_fifo", "tx_empty", "rx_full")):
                        continue
                    if a[dest] != b[dest]:
                        reads.setdefault((field, dest), set()).add(op)
    assert reads == READS


# --- baseline two: the widest CRC the current ISA computes ---------------------------------


def crc4_byte(bits):
    """What crc4_lfsr.asm hands the host after `bits`: the CRC-4 in the low
    nibble, converted from the feedback window, and above it what the
    window's conversion left in the register: the last feedback bit, the
    last input bit, the feedback bit before, the input bit before."""
    f = feedback(bits, CRC4_POLY, CRC4_WIDTH)
    assert from_window(f, CRC4_POLY, CRC4_WIDTH) == crc(bits, CRC4_POLY, CRC4_WIDTH)
    return crc(bits, CRC4_POLY, CRC4_WIDTH) | f[-1] << 4 | bits[-1] << 5 | f[-2] << 6 | bits[-2] << 7


def run_crc4(bytes_, program=None):
    """crc4_lfsr.asm with `bytes_` queued, the pads read back: gpio_in[0] and
    [1] follow gpio[0] and [1] every cycle, as the chip's pins do."""
    cpu = CPU(program or load_program(CRC4, ISA), tx_data=list(bytes_), isa=ISA)
    cpu.issues = []  # the op that issued each cycle, or None
    while not cpu.halted:
        op = decode(cpu.program[cpu.pc], ISA).op if cpu.counter == 0 else None
        cpu.step()
        cpu.issues.append(None if cpu.stalled else op)
        cpu.gpio_in[DATA_PIN], cpu.gpio_in[FEEDBACK_PIN] = cpu.gpio[DATA_PIN], cpu.gpio[FEEDBACK_PIN]
        assert cpu.cycle < 2000, "did not halt"
    return cpu


def bits_of(bytes_):
    return [(byte >> i) & 1 for byte in bytes_ for i in range(7, -1, -1)]


VECTORS = [(0, 0, 0, 0), (0xFF, 0xFF, 0xFF, 0xFF), (0x5A, 0x3A, 0x00, 0x5A), (0x12, 0x34, 0x56, 0x78)]
VECTORS += [tuple((1 << i) >> (8 * k) & 0xFF for k in range(3, -1, -1)) for i in range(32)]


@pytest.mark.parametrize("bytes_", VECTORS, ids=lambda v: "".join(f"{b:02x}" for b in v))
def test_crc4_of_four_host_bytes_reaches_the_host(bytes_):
    """The program shifts the four bytes out on pin 0, samples each bit back,
    feeds the register back on pin 1 and hands the host one byte: the CRC-4
    of the 32 bits in its low nibble, as the oracle computes it, the
    window's leftovers above; halted with the FIFOs empty and no stall."""
    cpu = run_crc4(bytes_)
    assert cpu.rx_fifo == [crc4_byte(bits_of(bytes_))]
    assert cpu.rx_fifo[0] & 0xF == crc(bits_of(bytes_), CRC4_POLY, CRC4_WIDTH)
    assert cpu.tx_fifo == [] and cpu.halted and cpu.stalled is False


def test_crc4_across_random_streams():
    """Two hundred random four-byte streams, each with the oracle's CRC-4 in the byte's low nibble."""
    rng = random.Random(3)
    for _ in range(200):
        bytes_ = [rng.randrange(256) for _ in range(4)]
        assert run_crc4(bytes_).rx_fifo == [crc4_byte(bits_of(bytes_))], bytes_


def test_crc4_is_the_feedback_window_in_the_register():
    """Inside a byte, after each input bit, in_shift_reg holds the input bits
    and the feedback bits interleaved, the newest feedback bit at 0, its
    input at 1, and so on up: four of each. The cell's parity reads bits 0,
    5 and 7, the input and the third and fourth feedback bits back, the
    polynomial's taps."""
    bytes_ = [0x5A, 0x3A, 0x00, 0x5A]
    bits = bits_of(bytes_)
    f = feedback(bits, CRC4_POLY, CRC4_WIDTH)
    cpu = CPU(load_program(CRC4, ISA), tx_data=list(bytes_), isa=ISA)
    seen = []
    while not cpu.halted and len(seen) < 32:
        pc = cpu.pc
        cpu.step()
        cpu.gpio_in[DATA_PIN], cpu.gpio_in[FEEDBACK_PIN] = cpu.gpio[DATA_PIN], cpu.gpio[FEEDBACK_PIN]
        instr = decode(cpu.program[pc], ISA)
        if instr.op == "SHIFT_IN" and instr.args[0] == FEEDBACK_PIN and cpu.counter == 0:
            seen.append(cpu.in_shift_reg)
    for t, reg in enumerate(seen):
        window = 0
        for i in range(4):
            if t - i >= 0:
                window |= f[t - i] << (2 * i) | bits[t - i] << (2 * i + 1)
        assert reg == window, f"after input bit {t}"


def test_crc4_by_the_numbers():
    """The cost of a 4-bit CRC on the current ISA: the words, the cycles an
    input bit takes, the register's use. A byte's cell is 17 words, the
    parity of three register bits as two paths through SKIPs with the
    result on a pin by a side effect, and the four bytes are written out,
    since the PULL between them breaks a body; the conversion of the window
    to the register's four bits is 27 words more. An input bit takes 8 to
    11 cycles by its path, 9 when everything is 0. Eight bits of register
    hold four of history: the widest CRC there is room for, and CRC-15
    wants 30."""
    words = load_program(CRC4)
    assert len(words) == 101
    assert len(set(words)) == 43
    assert [run_crc4(bytes_).cycle for bytes_ in ((0, 0, 0, 0), (0xFF,) * 4, (0x5A, 0x3A, 0x00, 0x5A))] == [308, 302, 323]
    rng = random.Random(1)
    cells = set()
    for bytes_ in [(0, 0, 0, 0)] + [tuple(rng.randrange(256) for _ in range(4)) for _ in range(100)]:
        cpu = run_crc4(bytes_)
        outs = [i for i, op in enumerate(cpu.issues) if op == "SHIFT_OUT"]
        pulls = [i for i, op in enumerate(cpu.issues) if op == "PULL"]
        cells |= {b - a for a, b in zip(outs, outs[1:]) if not any(a < p < b for p in pulls)}
    assert (min(cells), max(cells)) == (8, 11), "an input bit's cell, by its path"
    assert run_crc4((0, 0, 0, 0)).issues.count("SHIFT_OUT") == 32 and run_crc4((0, 0, 0, 0)).issues.count("PULL") == 4


# --- baseline three: the CRC as data ---------------------------------------------------------


def test_the_crc_is_data_to_the_frame_transmitter():
    """can_tx_frame.asm sends whatever CRC the host wrote: with the CRC bytes
    carrying a wrong CRC the stuffed stream on the bus is the wrong stream,
    bit for bit, the receiver reads a CRC that does not match and does not
    ack, and the host reads the ACK as 1. No word of the program is the
    CRC's: it is fifteen of the 42 stream bits, two of the six bytes, and
    the one pad bit in the last byte."""
    ident, data = IDENT, [0x5A]
    right = crc15(frame_bits(ident, data)[:-CRC_BITS])
    wrong = right ^ 0x2A5
    r = run_frame(ident, data, host=frame_host(frame_bytes(ident, data, crc=wrong)), cycles=3000)
    sof = r.line.index(0)
    bits = stuffed(frame_bits(ident, data, crc=wrong)) + [1, 1, 1] + [1] * GAP
    assert cells(r.line, sof, len(bits), FRAME_BIT) == bits
    rx = r.nodes[0].received[0]
    assert rx.ident == ident and rx.data == (0x5A,) and rx.crc == wrong and not rx.crc_ok and not rx.acked
    assert r.received[0] & 1 == 1
    assert len(frame_bits(ident, data)) == 42 and len(frame_bytes(ident, data)) == 6
    assert frame_bytes(ident, data)[4:] == [right >> 7, (right & 0x7F) << 1]
