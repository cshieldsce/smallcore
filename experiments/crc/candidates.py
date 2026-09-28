"""Model-only ISA variants for the CRC state comparison (docs/crc-candidates.md).

The CRC baselines left one wall: in_shift_reg is the eight bits a program
both writes and reads, and CRC-15 wants fifteen, thirty in the form the core
can execute, since every input bit takes a slot beside its feedback bit.
RX found the same wall from the other side: the raw history the run test
reads and the destuffed data the host wants cannot share the one register.
So the candidates here are state architectures, not CRC opcodes, each
isa.yaml plus its words and a CPU that runs them, measured on CRC-15 against
the oracle and on the destuffing receiver. Nothing here touches sim/cpu.py,
isa.yaml or the RTL.

  W16, W32  the register carried on: the bit that leaves in_shift_reg's wire
            end goes into a second stage, 8 or 24 bits more of history, in
            the same direction; `SKIP index, level` reaches it with the
            index's high part in bits 6:4 of the word, which SKIP's shape
            rejects (no side effect and a pin bit set). in_shift_reg, PUSH
            and the run test are as they were: ages 0..7 are the register,
            8..width - 1 the stage, the eighth newest sample at 8
  Pin8      SKIP_PIN pin, level: step over the next word if gpio_in[pin]
            held `level` as the word issued, the way SHIFT_IN samples. The
            input as a condition without a shift: it costs no slot
  Pin16     W16 with SKIP_PIN: a window the input does not enter, sixteen
            bits, the fifteen CRC-15 wants
  Lanes     a second in_shift_reg, `lane`: SHIFT_IN1 pin fills it alone,
            SHIFT_IN01 pin puts one sample into both, SKIP1 bit, level reads
            it, PUSH1 hands it to the host; the run test reads lane 0
  Acc       a 16-bit accumulator `acc` and a 16-bit polynomial `poly`:
            ACC_IN pin, f = acc[15] ^ gpio_in[pin], acc <- (acc << 1) ^ (f ?
            poly : 0), the spec's register in the direct form, any width to
            16 with the polynomial left-aligned; ACC_OUT pin, gpio[pin] <-
            acc[15] then acc <- acc << 1, the CRC out MSB first; ACC_PUSH,
            the RX FIFO takes acc[7:0] and acc <- acc >> 8, stalling while
            the FIFO is full; ACC_LOAD, poly <- {shift_reg, poly[15:8]}, a
            polynomial byte from the host, low byte first

Encoding, every word one the ISA rejects today, no valid word changed:

  far SKIP    opcode 110, bit 7 clear, bits 6:4 = the index's bits 5:3 (not
              000), bits 3:1 its bits 2:0, bit 0 the level, a delay as any
              word, no side effect: SKIP8, SKIP16, SKIP24 by the high part
  SKIP1       opcode 110, bit 7 clear, bits 6:4 = 001, bits 3:1 the bit, 0
              the level: lane 1's SKIP, no side effect
  SHIFT_IN1   opcode 001 with bits 1:0 = 11; SHIFT_IN01, bits 1:0 = 01; the
              shift word's spare bit 0, the pin in bits 3:2 and the side
              effect as SHIFT_IN's
  PUSH1       opcode 010 with bits 1:0 = 11, the pull/push word's spare bit
              1, the side effect as PUSH's
  SKIP_PIN    NOP's hole, bits 7:3 = 01100, the pin in bits 2:1, the level
              in bit 0
  ACC_IN      NOP's hole, bits 7:3 = 00100, the pin in bits 2:1; ACC_OUT
              00101 and the pin; ACC_PUSH bits 7:0 = 00110000; ACC_LOAD
              00111000

`Variant` is experiments/can/candidates.py's `Candidate`, cpu.CPU's step
with hooks, so the run test and REPEAT are the model's; the wide register's
stage, the lane and the accumulator are the hooks' business.
"""

import copy
import importlib.util
import sys
from pathlib import Path

from cpu import LINE_RE

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("can_candidates", HERE.parent / "can" / "candidates.py")
can = sys.modules.get("can_candidates") or importlib.util.module_from_spec(_spec)
if "can_candidates" not in sys.modules:
    sys.modules["can_candidates"] = can
    _spec.loader.exec_module(can)
Candidate = can.Candidate


class Variant(Candidate):
    """Candidate with the words that must decode before SKIP put first: SKIP
    has no select, so a far SKIP or SKIP1, opcode 110 with bits 6:4 set,
    would be SKIP's rejected word unless its own entry comes first."""

    FIRST = ()  # instruction names to decode before SKIP
    WIDTH = 8  # the sample history a SKIP can reach, ages 0..WIDTH - 1
    # The run tests are the ISA's since 2026-09-28; the CAN round's base Candidate predates that and runs them
    # only in its C class, so every variant here runs them as the model does.
    SKIPS = ("SKIP_RUN", "SKIP_NORUN")

    @classmethod
    def isa(cls):
        if cls.__dict__.get("_isa") is None:
            isa = can.round_isa()  # the ISA the round ran on, before the accumulator was adopted
            for klass in reversed(cls.__mro__):
                for name, select in klass.__dict__.get("SELECTS", {}).items():
                    isa["instructions"][name]["select"] = copy.deepcopy(select)
                isa["instructions"].update(copy.deepcopy(klass.__dict__.get("NEW", {})))
            first = cls.merged("FIRST")
            isa["instructions"] = {**{k: v for k, v in isa["instructions"].items() if k in first},
                                   **{k: v for k, v in isa["instructions"].items() if k not in first}}
            cls._isa = isa
        return cls._isa

    def ages(self, n):
        """The newest n samples a SKIP can reach, newest first: ages 0..n - 1."""
        return [self.age(i) for i in range(n)]

    def age(self, i):
        """The i-th newest sample, 0 the newest: in_shift_reg for 0..7, bit 0 MSB first and bit 7 LSB first."""
        if i < 8:
            return (self.in_shift_reg >> (i if self.shift_dir else 7 - i)) & 1
        raise ValueError(f"age {i}: the register holds eight")

    def execute(self, instr):
        if instr.op in self.merged("SKIPS"):
            return
        super().execute(instr)

    def test(self, op, a, level):
        if op in ("SKIP_RUN", "SKIP_NORUN"):
            run = all(bit == level for bit in self.newest(a + 1))
            return run if op == "SKIP_RUN" else not run
        return super().test(op, a, level)


# --- the wide register -----------------------------------------------------------------------


def far_skip(high):
    return {
        "opcode": 0b110,
        "select": {"name": "far", "lsb": 4, "bits": 4, "value": high},
        "description": f"SKIP on the register's age {8 * high} + bit, the second stage; no side effect.",
        "operands": [{"name": "bit", "lsb": 1, "bits": 3}, {"name": "level", "lsb": 0, "bits": 1}],
    }


class Wide(Variant):
    """W16, W32: the sample that leaves in_shift_reg's wire end enters `ext`,
    the second stage, which shifts the same way: ages 8..WIDTH - 1."""

    WIDTH = 16
    NEW = {"SKIP8": far_skip(1)}
    FIRST = ("SKIP8",)
    SKIPS = ("SKIP8",)

    def reset_state(self):
        self.ext = 0

    def state(self):
        return (self.ext,)

    @property
    def ext_bits(self):
        return self.WIDTH - 8

    def sample(self, bit):
        top = self.ext_bits - 1
        if self.shift_dir == 0:  # LSB first: the register walks right, bit 0 leaves into the stage's top, which walks right
            leaving = self.in_shift_reg & 1
            self.ext = (self.ext >> 1) | (leaving << top)
        else:  # MSB first: bit 7 leaves into the stage's bit 0, which walks left
            leaving = self.in_shift_reg >> 7
            self.ext = ((self.ext << 1) & ((1 << self.ext_bits) - 1)) | leaving
        super().sample(bit)

    def age(self, i):
        if i < 8:
            return super().age(i)
        j = i - 8
        if j >= self.ext_bits:
            raise ValueError(f"age {i}: the register holds {self.WIDTH}")
        return (self.ext >> (j if self.shift_dir else self.ext_bits - 1 - j)) & 1

    def test(self, op, a, level):
        if op in ("SKIP8", "SKIP16", "SKIP24"):
            return self.age(int(op[4:]) + a) == level
        return super().test(op, a, level)


class W16(Wide):
    pass


class W32(Wide):
    WIDTH = 32
    NEW = {"SKIP16": far_skip(2), "SKIP24": far_skip(3)}
    FIRST = ("SKIP16", "SKIP24")
    SKIPS = ("SKIP16", "SKIP24")


# --- the pin test ----------------------------------------------------------------------------


class Pin(Variant):
    """`SKIP_PIN pin, level`: the pad as a condition, sampled as the word issues, decided on its last cycle."""

    NEW = {
        "SKIP_PIN": {
            "opcode": 0b000,
            "select": {"name": "kind", "lsb": 3, "bits": 5, "value": 0b01100},
            "description": "Step over the next word if gpio_in[pin] held `level` as the word issued. No side effect.",
            "operands": [{"name": "pin", "lsb": 1, "bits": 2}, {"name": "level", "lsb": 0, "bits": 1}],
        }
    }
    SKIPS = ("SKIP_PIN",)

    def reset_state(self):
        super().reset_state()
        self.pin_seen = 0

    def execute(self, instr):
        if instr.op == "SKIP_PIN":
            self.pin_seen = self.gpio_in[instr.args[0]]
            return
        super().execute(instr)

    def test(self, op, a, level):
        if op == "SKIP_PIN":
            return self.pin_seen == level
        return super().test(op, a, level)


class Pin8(Pin):
    pass


class Pin16(Pin, W16):
    pass


# --- the lanes -------------------------------------------------------------------------------


def shift_word(value, description):
    return {
        "opcode": 0b001,
        "select": {"name": "kind", "lsb": 0, "bits": 2, "value": value},
        "description": description,
        "operands": [{"name": "pin", "lsb": 2, "bits": 2}],
        "side_effect": True,
    }


class Lanes(Variant):
    """A second in_shift_reg, `lane`, with its own shift, skip and push."""

    SELECTS = {
        "SHIFT_OUT": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b00},
        "SHIFT_IN": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b10},
        "PULL": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b00},
        "PUSH": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b01},
    }
    NEW = {
        "SHIFT_IN1": shift_word(0b11, "Sample gpio_in[pin] into lane 1, as SHIFT_IN into lane 0."),
        "SHIFT_IN01": shift_word(0b01, "Sample gpio_in[pin] into both lanes: one sample, two registers."),
        "PUSH1": {
            "opcode": 0b010,
            "select": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b11},
            "description": "Append lane 1 to the RX FIFO; the lane keeps its value. Stalls while the FIFO is full.",
            "operands": [],
            "side_effect": True,
        },
        "SKIP1": {
            "opcode": 0b110,
            "select": {"name": "lane", "lsb": 4, "bits": 4, "value": 0b0001},
            "description": "Step over the next word if lane 1's bit holds `level`. No side effect.",
            "operands": [{"name": "bit", "lsb": 1, "bits": 3}, {"name": "level", "lsb": 0, "bits": 1}],
        },
    }
    FIRST = ("SKIP1",)
    SKIPS = ("SKIP1",)

    def reset_state(self):
        self.lane = 0

    def state(self):
        return (self.lane,)

    def sample_lane(self, bit):
        if self.shift_dir == 0:
            self.lane = (self.lane >> 1) | (bit << 7)
        else:
            self.lane = ((self.lane << 1) & 0xFF) | bit

    def stalls(self, instr):
        return super().stalls(instr) or (instr.op == "PUSH1" and len(self.rx_fifo) >= self.rx_depth)

    def execute(self, instr):
        if instr.op == "SHIFT_IN1":
            self.sample_lane(self.gpio_in[instr.args[0]])
        elif instr.op == "SHIFT_IN01":
            bit = self.gpio_in[instr.args[0]]
            self.sample(bit)
            self.sample_lane(bit)
        elif instr.op == "PUSH1":
            self.rx_fifo.append(self.lane)
        else:
            super().execute(instr)

    def test(self, op, a, level):
        if op == "SKIP1":
            return (self.lane >> a) & 1 == level
        return super().test(op, a, level)


# --- the accumulator -------------------------------------------------------------------------


def hole_word(value, bits, operands, description):
    return {
        "opcode": 0b000,
        "select": {"name": "kind", "lsb": 8 - bits, "bits": bits, "value": value},
        "description": description,
        "operands": operands,
    }


PIN = [{"name": "pin", "lsb": 1, "bits": 2}]


class Acc(Variant):
    """A 16-bit LFSR accumulator with a loadable polynomial, the direct form."""

    NEW = {
        "ACC_IN": hole_word(0b00100, 5, PIN, "f = acc[15] ^ gpio_in[pin]; acc <- (acc << 1) ^ (f ? poly : 0)."),
        "ACC_OUT": hole_word(0b00101, 5, PIN, "gpio[pin] <- acc[15]; acc <- acc << 1."),
        "ACC_PUSH": hole_word(0b00110000, 8, [], "RX FIFO <- acc[7:0]; acc <- acc >> 8. Stalls while the FIFO is full."),
        "ACC_LOAD": hole_word(0b00111000, 8, [], "poly <- {shift_reg, poly[15:8]}: a polynomial byte from the host, low first."),
    }

    def reset_state(self):
        self.acc, self.poly = 0, 0

    def state(self):
        return (self.acc, self.poly)

    def stalls(self, instr):
        return super().stalls(instr) or (instr.op == "ACC_PUSH" and len(self.rx_fifo) >= self.rx_depth)

    def execute(self, instr):
        if instr.op == "ACC_IN":
            f = (self.acc >> 15) ^ self.gpio_in[instr.args[0]]
            self.acc = ((self.acc << 1) & 0xFFFF) ^ (self.poly if f else 0)
        elif instr.op == "ACC_OUT":
            self.gpio[instr.args[0]] = self.acc >> 15
            self.acc = (self.acc << 1) & 0xFFFF
        elif instr.op == "ACC_PUSH":
            self.rx_fifo.append(self.acc & 0xFF)
            self.acc >>= 8
        elif instr.op == "ACC_LOAD":
            self.poly = (self.shift_reg << 8) | (self.poly >> 8)
        else:
            super().execute(instr)


CANDIDATES = {"W16": W16, "W32": W32, "Pin8": Pin8, "Pin16": Pin16, "Lanes": Lanes, "Acc": Acc}


# --- the assembler -----------------------------------------------------------------------------


def assemble(source, cls):
    """experiments/can/candidates.py's assembler on the candidate's ISA,
    after `SKIP index, level` with an index of 8 or more is written as the
    far word its high part names, SKIP8, SKIP16 or SKIP24; a far SKIP takes
    no side effect. The rest is the model's assembler and REPEAT's rules."""
    out = []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        m = LINE_RE.match(line) if line else None
        if m and m["op"] and m["op"].upper() == "SKIP":
            args = m["args"].replace(",", " ").split()
            try:
                index = int(args[0], 0) if args else 0
            except ValueError:
                index = 0
            if index >= 8:
                if index >= cls.WIDTH:
                    raise SyntaxError(f"line {lineno}: SKIP {index}: the register holds {cls.WIDTH}")
                if len(args) != 2:
                    raise SyntaxError(f"line {lineno}: a far SKIP takes a bit and a level and no side effect")
                label = f"{m['label']}:" if m["label"] else ""
                delay = f" [{m['delay']}]" if m["delay"] else ""
                out.append(f"{label:8}SKIP{8 * (index >> 3)} {index & 7}, {args[1]}{delay}")
                continue
        out.append(raw)
    return can.assemble("\n".join(out), cls)


def load_program(name, cls):
    """experiments/crc/<name>.asm assembled for the candidate."""
    return assemble((HERE / f"{name}.asm").read_text(), cls)


def listing(words, cls):
    """One line per word, a far SKIP by its index."""
    out = []
    for line, word in zip(can.listing(words, cls), words):
        instr = cls.decode(word)
        if instr.op in ("SKIP8", "SKIP16", "SKIP24"):
            address = line.split()[0]
            line = f"{address:>3}  {word:04x}  SKIP {int(instr.op[4:]) + instr.args[0]}, {instr.args[1]} [{instr.delay}]"
        out.append(line)
    return out
