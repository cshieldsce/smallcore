"""The accumulator, adopted 2026-09-28 (docs/crc-candidates.md, "Decided"):
a second stream register, sixteen bits, with optional LFSR feedback, and
its sixteen-bit polynomial. The corners pinned on the model, the way
REPEAT's and the run test's were.

The words: opcode 000, NOP's hole, bits 7:5 = 001, bits 4:2 the kind, bits
1:0 the pin where there is one, a delay in 12:8 as any word, no side effect.

  ACC_IN pin    acc <- (acc << 1) | gpio_in[pin]: a plain shift, the
                oldest bit falling off bit 15
  ACC_CRC pin   f = acc[15] ^ gpio_in[pin]; acc <- (acc << 1) ^ (f ? poly :
                0): the spec's register in the direct form, any width to 16
                with the polynomial left-aligned
  ACC_OUT pin   gpio[pin] <- acc[15]; acc <- acc << 1: the CRC out MSB first
  ACC_PUSH      RX FIFO <- acc[7:0]; acc <- acc >> 8; stalls while the FIFO
                is full, the delay waiting with it
  ACC_LOAD      poly <- {shift_reg, poly[15:8]}: a polynomial byte, low first

The candidate round's accumulator had one input word, ACC_IN with the
feedback, and a plain register only with poly = 1 and a push every eight
bits, before anything reached bit 15; the adopted one says which it is in
the word. The pad is sampled as SHIFT_IN samples it, as the word issues.
acc shifts towards bit 15 whatever shift_dir says: a CRC is defined MSB
first. Reset and restart clear acc and poly. 448 words that were rejected
are instructions, no other word changed meaning, every program assembles
to the words it did.

Then the candidate programs on the ISA as it is: CRC-15 against the oracle
and the destuffing receiver handing the host bytes."""

import copy
import random
from pathlib import Path

import pytest

from cpu import CPU, assemble, decode, load_isa, load_program
from test_can import BIT, IDENT, PROGRAMS, bits_to_int, frame_bits  # noqa: E402
from test_can_rx import AT, frame_on_the_bus, run_rx  # noqa: E402
from test_crc import CRC4, VECTORS, bits_of, crc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
EXPERIMENTS = ROOT / "experiments"
ISA = load_isa()
ACC_OPS = ("ACC_IN", "ACC_CRC", "ACC_OUT", "ACC_PUSH", "ACC_LOAD")
POLY15 = 0x4599


def old_isa():
    """isa.yaml as it was before the accumulator."""
    isa = copy.deepcopy(ISA)
    for op in ACC_OPS:
        del isa["instructions"][op]
    return isa


def cpu_of(source, **kw):
    return CPU(assemble(source, ISA), isa=ISA, **kw)


# --- the words -------------------------------------------------------------------------------


def test_the_words_sit_in_nops_hole():
    """ACC_IN 0 is 0x0020: opcode 000, bits 7:5 = 001, kind 000 in 4:2, the
    pin in 1:0; ACC_CRC is kind 001, ACC_OUT 010, ACC_PUSH 011 and
    ACC_LOAD 100 with bits 1:0 clear. A delay goes in 12:8 as for any word.
    No side effect: the assembler refuses one."""
    assert assemble("ACC_IN 0") == [0x0020] and assemble("ACC_IN 3") == [0x0023]
    assert assemble("ACC_CRC 0") == [0x0024] and assemble("ACC_OUT 1") == [0x0029]
    assert assemble("ACC_PUSH") == [0x002C] and assemble("ACC_LOAD [3]") == [0x0330]
    assert assemble("NOP") == [0x0000] and assemble("SKIP_RUN 5, 1") == [0x0049]
    for bad in ("ACC_IN", "ACC_IN 4", "ACC_IN 0, 1, 1", "ACC_PUSH 1", "ACC_OUT 0, 2, 0", "ACC_LOAD 0"):
        with pytest.raises(SyntaxError):
            assemble(bad)


def test_the_accumulator_takes_448_rejected_words_and_changes_no_other():
    """Every 16-bit word on the ISA as it was and as it is: what was an
    instruction is the same instruction; 448 rejected words are the
    accumulator's, three kinds with a pin and two without, times 32 delays;
    kinds 101 to 111 and a pin on ACC_PUSH or ACC_LOAD stay rejected."""
    before, new = old_isa(), {}
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
        elif now is not None:
            assert now.op in ACC_OPS and now.side is None, f"word {w:#06x}"
            new[now.op] = new.get(now.op, 0) + 1
    assert new == {"ACC_IN": 128, "ACC_CRC": 128, "ACC_OUT": 128, "ACC_PUSH": 32, "ACC_LOAD": 32}


def test_every_program_assembles_to_the_same_words():
    old = old_isa()
    for path in sorted(PROGRAMS.rglob("*.asm")) + [CRC4]:
        assert load_program(path, ISA) == load_program(path, old), path.name


# --- what each does ---------------------------------------------------------------------------


@pytest.mark.parametrize("shift_dir", (0, 1))
def test_acc_in_is_a_plain_sixteen_bit_shift_register(shift_dir):
    """Forty samples from four pins: after each, acc is the last sixteen,
    the newest at bit 0, whatever the polynomial holds and whatever
    shift_dir says; the oldest falls off bit 15 and feeds nothing back.
    in_shift_reg is not touched."""
    rng = random.Random(shift_dir)
    cpu = CPU([0], isa=ISA)
    cpu.shift_dir, cpu.poly, cpu.in_shift_reg = shift_dir, 0x4599 << 1, 0xA5
    samples = []
    for step in range(40):
        pin, bit = rng.randrange(4), rng.randrange(2)
        cpu.gpio_in[pin] = bit
        cpu.program, cpu.pc, cpu.halted = assemble(f"ACC_IN {pin}", ISA), 0, False
        cpu.step()
        samples.append(bit)
        assert cpu.acc == bits_to_int(samples[-16:]), f"after sample {step}"
    assert cpu.in_shift_reg == 0xA5 and cpu.poly == 0x4599 << 1


@pytest.mark.parametrize("poly, width", ((POLY15, 15), (0x07, 8), (0x3, 4), (0x1021, 16), (0x1, 1)))
def test_acc_crc_is_the_specs_register_for_any_polynomial(poly, width):
    """ACC_CRC with the polynomial left-aligned is the spec's register in the
    top bits, zeros below: CAN's CRC-15, an 8-bit, the 4-bit, CRC-16-CCITT's,
    and x + 1, the parity, in acc[15]. Random streams of every length to 40
    against the oracle."""
    rng = random.Random(poly)
    for n in range(1, 41):
        bits = [rng.randrange(2) for _ in range(n)]
        cpu = CPU(assemble("ACC_CRC 2\n" * n, ISA), isa=ISA)
        cpu.poly = (poly << (16 - width)) & 0xFFFF
        for bit in bits:
            cpu.gpio_in[2] = bit
            cpu.step()
        assert cpu.acc == crc(bits, poly, width) << (16 - width), bits
    assert crc(bits_of(b"123456789"), POLY15, 15) == 0x059E


def test_acc_out_emits_the_top_bit_msb_first():
    """ACC_OUT pin: the pin takes acc[15], then acc shifts left, zero in:
    fifteen after a CRC-15 put the CRC on the pin MSB first, the order CAN
    sends it, and leave acc clear; any pin."""
    value = crc(bits_of([0x12, 0x34, 0x56]), POLY15, 15)
    cpu = cpu_of("ACC_OUT 3\n" * 15)
    cpu.acc = value << 1
    seen = []
    for _ in range(15):
        cpu.step()
        seen.append(cpu.gpio[3])
    assert bits_to_int(seen) == value and cpu.acc == 0 and cpu.gpio[:3] == [1, 1, 1]


def test_acc_push_hands_the_low_byte_and_stalls_on_a_full_fifo():
    """ACC_PUSH: the RX FIFO takes acc[7:0], acc shifts right by eight, so
    two hand the host a sixteen-bit value low byte first and leave acc
    clear. A full FIFO stalls it with acc untouched, and the delay waits
    with it, as PUSH's does."""
    cpu = cpu_of("ACC_PUSH [2]\nACC_PUSH\nACC_PUSH\nNOP", rx_depth=4)
    cpu.acc, cpu.rx_fifo = 0x8B32, [0, 0, 0, 0]
    for _ in range(3):
        cpu.step()
        assert cpu.stalled and cpu.pc == 0 and cpu.acc == 0x8B32
    cpu.rx_fifo = []
    cpu.step()
    assert not cpu.stalled and cpu.rx_fifo == [0x32] and cpu.acc == 0x008B and cpu.pc == 0
    cpu.run_cycles(4)
    assert cpu.rx_fifo == [0x32, 0x8B, 0x00] and cpu.acc == 0 and cpu.pc == 3


def test_acc_load_takes_the_polynomial_a_byte_at_a_time():
    """ACC_LOAD: poly <- {shift_reg, poly[15:8]}: two loads after two PULLs
    set poly from the host's bytes, low first; acc is not touched."""
    cpu = cpu_of("PULL\nACC_LOAD\nPULL\nACC_LOAD", tx_data=[0x32, 0x8B])
    cpu.acc = 0x1234
    cpu.run_cycles(2)
    assert cpu.poly == 0x3200
    cpu.run_cycles(2)
    assert cpu.poly == 0x8B32 and cpu.acc == 0x1234


def test_the_pad_is_sampled_as_the_word_issues_and_the_delay_holds_the_state():
    """ACC_IN and ACC_CRC sample the pad on the word's first cycle, the way
    SHIFT_IN does: a change during the delay is not seen and nothing moves
    again. ACC_OUT's pin lands on the first cycle."""
    for op in ("ACC_IN", "ACC_CRC"):
        cpu = cpu_of(f"{op} 1 [3]\nNOP")
        cpu.poly, cpu.gpio_in[1] = 0x8000, 1
        cpu.step()
        after = cpu.acc
        cpu.gpio_in[1] = 0
        for _ in range(3):
            assert cpu.pc == 0
            cpu.step()
            assert cpu.acc == after
        assert cpu.pc == 1 and after in (1, 0x8000)
    cpu = cpu_of("ACC_OUT 2 [2]\nNOP")
    cpu.acc = 0x8000
    cpu.step()
    assert cpu.gpio[2] == 1 and cpu.acc == 0 and cpu.pc == 0


def test_reset_and_restart_clear_the_accumulator_and_its_polynomial():
    cpu = cpu_of("PULL\nACC_LOAD\nACC_IN 0\nACC_IN 0", tx_data=[0xFF], gpio_in=1)
    assert (cpu.acc, cpu.poly) == (0, 0)
    cpu.run()
    assert (cpu.acc, cpu.poly) == (3, 0xFF00)
    cpu.restart()
    assert (cpu.acc, cpu.poly) == (0, 0)


def test_the_accumulator_leaves_everything_else_alone():
    """No accumulator word moves in_shift_reg, shift_reg, the configuration,
    rc, or the pc beyond the next word; only ACC_OUT writes a pin, only
    ACC_PUSH the RX FIFO."""
    rng = random.Random(7)
    for source in ("ACC_IN 2", "ACC_CRC 1", "ACC_OUT 3", "ACC_PUSH", "ACC_LOAD"):
        for _ in range(20):
            cpu = cpu_of(source + "\nNOP")
            cpu.in_shift_reg, cpu.shift_reg, cpu.acc, cpu.poly = (rng.randrange(1 << k) for k in (8, 8, 16, 16))
            cpu.gpio_in = [rng.randrange(2) for _ in range(4)]
            before = (cpu.in_shift_reg, cpu.shift_reg, cpu.shift_dir, list(cpu.open_drain), cpu.rc)
            gpio = list(cpu.gpio)
            cpu.step()
            assert (cpu.in_shift_reg, cpu.shift_reg, cpu.shift_dir, list(cpu.open_drain), cpu.rc) == before and cpu.pc == 1
            assert cpu.gpio[:3] == gpio[:3] and (cpu.gpio[3] == gpio[3] or source == "ACC_OUT 3")
            assert cpu.rx_fifo == [] or source == "ACC_PUSH"


# --- the programs, on the ISA as it is ---------------------------------------------------------


def run_crc15(bytes_):
    """experiments/acc/crc15.asm with the polynomial and `bytes_` queued, the
    pads read back: the CRC's bits are pin 1 as the emission's REPEAT issues."""
    words = load_program(EXPERIMENTS / "acc" / "crc15.asm", ISA)
    cpu = CPU(words, isa=ISA, tx_data=[(POLY15 << 1) & 0xFF, POLY15 >> 7] + list(bytes_))
    last = max(a for a, w in enumerate(words) if decode(w, ISA).op == "REPEAT")
    emitted = []
    while not cpu.halted:
        if cpu.counter == 0 and cpu.pc == last:
            emitted.append(cpu.gpio[1])
        cpu.step()
        cpu.gpio_in = list(cpu.gpio)
        assert cpu.cycle < 1000
    return cpu, emitted


@pytest.mark.parametrize("bytes_", VECTORS, ids=lambda v: "".join(f"{b:02x}" for b in v))
def test_crc15_of_four_host_bytes_leaves_on_the_pin(bytes_):
    """The candidate round's crc15_acc.asm with ACC_CRC for its input word:
    23 words, the CRC-15 of the 32 bits out on pin 1 MSB first."""
    cpu, emitted = run_crc15(bytes_)
    assert bits_to_int(emitted) == crc(bits_of(bytes_), POLY15, 15) and len(emitted) == 15
    assert cpu.tx_fifo == [] and len(cpu.program) == 23


RX_VECTORS = ((0x5A3, 0x5A), (0x7FF, 0xFF), (0x000, 0x00), (0x07C, 0x00), (0x555, 0xAA), (0x123, 0x01))


@pytest.mark.parametrize("ident, data", RX_VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_the_destuffing_receiver_hands_the_host_bytes(ident, data):
    """The candidate round's can_rx_bytes_acc.asm with ACC_IN, the plain
    shift, and no polynomial to load: the destuffed stream as five bytes
    and the last two bits, at eight clocks a bit, the ACK landed, no stall."""
    cpu = CPU(load_program(EXPERIMENTS / "acc" / "can_rx_bytes.asm", ISA), gpio_in=1, isa=ISA)
    r, tx = run_rx(None, ident, [data], cpu=cpu)
    stream = frame_bits(ident, [data])
    assert r.received == [bits_to_int(stream[8 * k : 8 * k + 8]) for k in range(5)] + [bits_to_int(stream[40:42])]
    assert tx.acked is True and r.rx_peak == 1 and not any(r.stalls[AT + 1 :]) and r.cpu.halted
