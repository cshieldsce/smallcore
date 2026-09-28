"""Model-only ISA variants for the CAN comparison (docs/can-candidates.md).

CAN left two complaints on the post-REPEAT ISA (README, "CAN by the
numbers"): arbitration, where the core cannot branch on the bit it sent once
SHIFT_OUT has put it on the pin, and bit stuffing, where the last five
samples are in in_shift_reg but asking "all one level?" is a tree of SKIPs
seven cycles deep. Shared: after a sample, a decision that must land on the
next bit edge, and SKIP + JMP is a cycle longer on the taken side. Each
candidate here is isa.yaml plus its word or two and a CPU that runs them,
spliced into can_tx_arb.asm (95 words) and can_tx_stuff.asm (224 words) and
measured against them. Nothing here touches sim/cpu.py, isa.yaml or the RTL:
the four CAN programs stay as the baselines.

  A   BRANCH bit, level, label     one word, one cycle, taken or not: pc <-
                                   pc + ahead if in_shift_reg[bit] == level
  B   SHIFT_SENT pin               the bit the core holds on gpio[pin], the
                                   register behind the pad, sampled into
                                   in_shift_reg as SHIFT_IN samples the pad
  Bc  SKIP_SENT pin, level         the same register as a condition, no sample
  C   SKIP_RUN n, level            the newest n samples all `level`: a run
      SKIP_NORUN n, level          test on the register, no new state, in
                                   both senses
  D   SKIP_SAME n                  a 3-bit counter of consecutive equal
                                   samples, kept by SHIFT_IN; the test is
                                   count >= n
  AB, ABc, AC, AD                  A with each: BRANCH_SENT, BRANCH_RUN,
                                   BRANCH_SAME are the same tests as branches

Encoding, the cost the reviewer asked to count. Opcode space is full, so
every word here takes words the ISA rejects today and changes the meaning of
none it accepts. The branch family is opcode 110 (SKIP's) with bits 7:6 =
01, which SKIP leaves rejected (bit 6 must be 0 without a side effect, and
bits 7:6 = 01 is no side effect with a pin bit set):

  15 14 13 | 12   | 11 10 9         | 8     | 7 6 | 5 4 3 2 1 0
   1  1  0 | kind | bit / n-1 / pin | level | 0 1 | ahead 1..63

one cycle, no delay (bits 12:8 are the condition, as they are a count in
REPEAT), no side effect, and a reach of 63 words ahead only, the mirror of
REPEAT's 255 back. kind 0 is BRANCH; kind 1 is the candidate's other test.
The SKIP-shaped tests live in the NOP's hole, opcode 000 with bit 7 clear
and bits 6:0 not all 0, which is 4064 rejected words: bits 7:5 = 001
SKIP_SENT, 010 SKIP_RUN with bit 4 its sense, 011 SKIP_SAME, own operands in
bits 3:0 as SKIP's, a delay as any word, no side effect (SET owns the flag
bit). SHIFT_SENT is
bit 0 of the SHIFT word, spare until now: bits 1:0 = 11.

`Candidate` is cpu.CPU's step word for word, REPEAT included, with hooks for
the new words, so the existing suite run against it (`suite.py`) checks the
copy before the extensions.
"""

import copy
from pathlib import Path

from cpu import CPU, Instruction, LINE_RE, PC_BITS, cycles, decode, load_isa
from cpu import assemble as base_assemble

HERE = Path(__file__).resolve().parent
AHEAD_BITS = 6
KIND_LSB = 4  # in the delay field: kind at bit 4, bit / n-1 / pin at 3:1, level at 0


class Candidate(CPU):
    """cpu.CPU with the step written out and hooks: `execute` for a new
    word's first cycle, `cycles_of` for how long it holds, `advance` for
    where pc goes on its last cycle, `sample` for what a sample does."""

    NEW = {}  # instruction name -> spec, added to isa.yaml's; merged down the class tree
    SELECTS = {}  # instruction name -> select spec, replacing isa.yaml's
    BRANCHES = {}  # mnemonic -> (kind, operand names) for the branch family
    KINDS = {}  # kind -> the mnemonic, for listings and the check
    SKIPS = ()  # the SKIP-shaped words of this candidate, besides SKIP
    RUNS = ()  # mnemonics whose first operand is written as n, 1..8, and held as n - 1
    _isa = None

    @classmethod
    def isa(cls):
        if cls.__dict__.get("_isa") is None:  # one cache per class, not the parent's
            isa = copy.deepcopy(load_isa())
            for klass in reversed(cls.__mro__):
                for name, select in klass.__dict__.get("SELECTS", {}).items():
                    isa["instructions"][name]["select"] = copy.deepcopy(select)
                isa["instructions"].update(copy.deepcopy(klass.__dict__.get("NEW", {})))
            if "BRANCH" in isa["instructions"]:
                # decode() takes the first instruction whose opcode and select match, and SKIP has no
                # select: the branch family, bits 7:6 = 01 where SKIP's shape rejects, goes before it
                branch = isa["instructions"].pop("BRANCH")
                isa["instructions"] = {**{k: v for k, v in isa["instructions"].items() if k < "SKIP" or k in ("SKIP_RUN", "SKIP_SAME", "SKIP_SENT")},
                                       "BRANCH": branch, **{k: v for k, v in isa["instructions"].items() if not (k < "SKIP" or k in ("SKIP_RUN", "SKIP_SAME", "SKIP_SENT"))}}
            cls._isa = isa
        return cls._isa

    @classmethod
    def merged(cls, attr):
        out = {}
        for klass in reversed(cls.__mro__):
            value = klass.__dict__.get(attr, {})
            out.update(value) if isinstance(value, dict) else out.update({v: v for v in value})
        return out

    @classmethod
    def decode(cls, word):
        """decode() on the candidate's ISA, then the checks the fields cannot
        say: a branch kind the candidate lacks, a pin above 3."""
        instr = decode(word, cls.isa())
        if instr.op == "BRANCH":
            kinds = cls.merged("KINDS")
            kind, a = instr.delay >> KIND_LSB, (instr.delay >> 1) & 7
            if kind not in kinds:
                raise ValueError(f"word {word:#06x}: branch kind {kind} is not one of this candidate's")
            if kinds[kind] == "BRANCH_SENT" and a > 3:
                raise ValueError(f"word {word:#06x}: BRANCH_SENT pin {a} is not a pin")
        return instr

    def __init__(self, program, gpio=1, gpio_in=0, tx_data=(), rx_depth=4, isa=None):
        super().__init__(program, gpio, gpio_in, tx_data, rx_depth, isa or self.isa())
        self.reset_state()

    def reset_state(self):
        """The candidate's own registers, at reset (and restart: CPU.restart runs __init__)."""

    def state(self):
        """The candidate's own registers, for a test to watch."""
        return ()

    # -- the step, as cpu.CPU.step, with the hooks ------------------------------------

    def stalls(self, instr):
        return ((instr.op == "PULL" and not self.tx_fifo) or (instr.op == "PUSH" and len(self.rx_fifo) >= self.rx_depth)
                or (instr.op == "WAIT" and self.gpio_in[instr.args[0]] != instr.args[1]))

    def shift_out(self):
        if self.shift_dir == 0:
            self.gpio[0] = self.shift_reg & 1
            self.shift_reg >>= 1
        else:
            self.gpio[0] = self.shift_reg >> 7
            self.shift_reg = (self.shift_reg << 1) & 0xFF

    def sample(self, bit):
        """A level into in_shift_reg, as SHIFT_IN does it."""
        if self.shift_dir == 0:
            self.in_shift_reg = (self.in_shift_reg >> 1) | (bit << 7)
        else:
            self.in_shift_reg = ((self.in_shift_reg << 1) & 0xFF) | bit

    def newest(self, n):
        """The newest n samples, as a tuple oldest first."""
        if self.shift_dir == 0:
            return tuple((self.in_shift_reg >> (8 - n + i)) & 1 for i in range(n))
        return tuple((self.in_shift_reg >> (n - 1 - i)) & 1 for i in range(n))

    def config(self, field, value):
        config = self.isa["config"]
        if field == config["shift_dir"]["field"]:
            self.shift_dir = value
        elif field == config["open_drain01"]["field"]:
            self.open_drain[0:2] = [value & 1, value >> 1]
        elif field == config["open_drain23"]["field"]:
            self.open_drain[2:4] = [value & 1, value >> 1]

    def execute(self, instr):
        """A candidate's own word, on its first cycle."""
        if instr.op not in ("BRANCH",) + tuple(self.merged("SKIPS")):
            raise ValueError(f"{instr.op}: not an instruction of this candidate")

    def cycles_of(self, instr):
        return 1 if instr.op == "BRANCH" else cycles(instr)

    def condition(self, instr):
        """A BRANCH or SKIP-shaped word's condition, as it stands on the word's last cycle."""
        if instr.op == "SKIP":
            return (self.in_shift_reg >> instr.args[0]) & 1 == instr.args[1]
        if instr.op == "BRANCH":
            kind, a, level = instr.delay >> KIND_LSB, (instr.delay >> 1) & 7, instr.delay & 1
            op = self.merged("KINDS")[kind]
        else:
            op, a, level = instr.op, instr.args[0], instr.args[1] if len(instr.args) > 1 else 0
        if op == "BRANCH":
            return (self.in_shift_reg >> a) & 1 == level
        return self.test(op, a, level)

    def test(self, op, a, level):
        raise ValueError(f"{op}: not a test of this candidate")

    def advance(self, instr):
        """pc on the instruction's last cycle: JMP, SKIP, REPEAT, a branch, or the next word."""
        if instr.op == "JMP":
            self.pc = instr.args[0]
        elif instr.op == "SKIP" or instr.op in self.merged("SKIPS"):
            self.pc += 2 if self.condition(instr) else 1
        elif instr.op == "BRANCH":
            self.pc += instr.args[0] if self.condition(instr) else 1
        elif instr.op == "REPEAT":
            self.rc = instr.delay if self.rc == 0 else self.rc - 1
            self.pc = (self.pc - instr.args[0]) % (1 << PC_BITS) if self.rc else self.pc + 1
        else:
            self.pc += 1

    def finish(self):
        self.halted = self.pc >= len(self.program)
        self.trace.append(tuple(self.gpio))
        self.cycle += 1

    def step(self):
        if self.halted:
            raise RuntimeError("CPU is halted")
        instr = self.decode(self.program[self.pc])
        if self.counter == 0:
            if self.stalls(instr):
                self.stalled = True
                self.trace.append(tuple(self.gpio))
                self.cycle += 1
                return
            self.stalled = False
            if instr.op == "SHIFT_OUT":
                self.shift_out()
            elif instr.op == "SHIFT_IN":
                self.sample(self.gpio_in[instr.args[0]])
            elif instr.op == "PULL":
                self.shift_reg = self.tx_fifo.pop(0)
            elif instr.op == "PUSH":
                self.rx_fifo.append(self.in_shift_reg)
            elif instr.op == "CONFIG":
                self.config(*instr.args)
            elif instr.op not in ("NOP", "SET", "WAIT", "SKIP", "JMP", "REPEAT"):
                self.execute(instr)
            pin_write = instr.args if instr.op == "SET" else instr.side
            if pin_write is not None:
                pin, value = pin_write
                self.gpio[pin] = value
            self.counter = self.cycles_of(instr)
        self.counter -= 1
        if self.counter == 0:
            self.advance(instr)
        self.finish()


# -- the pieces ------------------------------------------------------------------------

BRANCH_WORD = {
    "opcode": 0b110,
    "select": {"name": "branch", "lsb": 6, "bits": 2, "value": 0b01},
    "description": "pc <- pc + ahead if the condition in bits 12:8 holds, else pc + 1; one cycle either way.",
    "operands": [{"name": "ahead", "lsb": 0, "bits": AHEAD_BITS, "min": 1}],
}
NOP_HOLE = {"name": "kind", "lsb": 5, "bits": 3, "value": 0}  # NOP: bits 7:5 = 000, the rest 0 as ever


class Branch(Candidate):
    """A: `BRANCH bit, level, label`. Rules the assembler keeps, as for a JMP
    (`check_bodies`): a BRANCH in a REPEAT body lands in it, from the label
    to the REPEAT, and nothing outside lands inside a body past its label."""

    NEW = {"BRANCH": BRANCH_WORD}
    BRANCHES = {"BRANCH": (0, ("bit", "level"))}
    KINDS = {0: "BRANCH"}


class Sent(Candidate):
    """B: `SHIFT_SENT pin`, the register behind the pad into in_shift_reg."""

    SELECTS = {
        "SHIFT_OUT": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b00},
        "SHIFT_IN": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b10},
    }
    NEW = {
        "SHIFT_SENT": {
            "opcode": 0b001,
            "select": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b11},
            "description": "Sample gpio[pin], the level the core holds on the pin, into in_shift_reg as SHIFT_IN samples gpio_in[pin].",
            "operands": [{"name": "pin", "lsb": 2, "bits": 2}],
            "side_effect": True,
        }
    }

    def execute(self, instr):
        if instr.op == "SHIFT_SENT":
            self.sample(self.gpio[instr.args[0]])
        else:
            super().execute(instr)


class SentCondition(Candidate):
    """Bc: `SKIP_SENT pin, level`, the register behind the pad as a condition;
    with A, `BRANCH_SENT pin, level, label`."""

    SELECTS = {"NOP": NOP_HOLE}
    NEW = {
        "SKIP_SENT": {
            "opcode": 0b000,
            "select": {"name": "kind", "lsb": 5, "bits": 3, "value": 0b001},
            "description": "Step over the next word if gpio[pin] == level.",
            "operands": [{"name": "pin", "lsb": 1, "bits": 2}, {"name": "level", "lsb": 0, "bits": 1}],
        }
    }
    BRANCHES = {"BRANCH_SENT": (1, ("pin", "level"))}
    KINDS = {1: "BRANCH_SENT"}
    SKIPS = ("SKIP_SENT",)

    def test(self, op, a, level):
        if op in ("SKIP_SENT", "BRANCH_SENT"):
            return self.gpio[a] == level
        return super().test(op, a, level)


class Run(Candidate):
    """C: `SKIP_RUN n, level`, step over the next word if the newest n
    samples are all `level`, and `SKIP_NORUN n, level`, step over it unless
    they are; with A, `BRANCH_RUN n, level, label`. n is 1..8, held as
    n - 1; n = 1 is SKIP on the newest bit. Two senses because a run test,
    unlike a bit test, is not negated by flipping its level, and the word
    after a SKIP is the case the SKIP does not cover: `SKIP 0, 1` then `JMP
    dominant` is the baseline's shape, `SKIP_NORUN 5, 1` then `JMP stuff`
    is this one's. A BRANCH takes the run's side itself."""

    # Adopted 2026-09-28: SKIP_RUN and SKIP_NORUN are isa.yaml's, with NOP's hole select, and the
    # assembler writes their n - 1; the candidate adds nothing to the word space now and keeps
    # its own test for the comparison and BRANCH_RUN for AC.
    SELECTS = {}
    NEW = {}
    BRANCHES = {"BRANCH_RUN": (1, ("n", "level"))}
    KINDS = {1: "BRANCH_RUN"}
    SKIPS = ("SKIP_RUN", "SKIP_NORUN")
    RUNS = ("SKIP_RUN", "SKIP_NORUN", "BRANCH_RUN")

    def test(self, op, a, level):
        if op in ("SKIP_RUN", "BRANCH_RUN"):
            return all(bit == level for bit in self.newest(a + 1))
        if op == "SKIP_NORUN":
            return not all(bit == level for bit in self.newest(a + 1))
        return super().test(op, a, level)


class Same(Candidate):
    """D: a counter `same`, 3 bits, of consecutive equal samples: a sample
    equal to the one before makes it one more, to 7 at most, any other
    sample makes it 1; reset and restart make it 0. `SKIP_SAME n` steps over
    the next word if same >= n; with A, `BRANCH_SAME n, label`. The level of
    the run is the newest bit, SKIP 0 / BRANCH 0's business."""

    SELECTS = {"NOP": NOP_HOLE}
    NEW = {
        "SKIP_SAME": {
            "opcode": 0b000,
            "select": {"name": "kind", "lsb": 5, "bits": 3, "value": 0b011},
            "description": "Step over the next word if the last n samples were the same level; n - 1 in the word.",
            "operands": [{"name": "n1", "lsb": 1, "bits": 3}],
        }
    }
    BRANCHES = {"BRANCH_SAME": (1, ("n",))}
    KINDS = {1: "BRANCH_SAME"}
    SKIPS = ("SKIP_SAME",)
    RUNS = ("SKIP_SAME", "BRANCH_SAME")

    def reset_state(self):
        self.same, self.last = 0, None

    def state(self):
        return (self.same, self.last)

    def sample(self, bit):
        super().sample(bit)
        self.same = min(self.same + 1, 7) if bit == self.last else 1
        self.last = bit

    def test(self, op, a, level):
        if op in ("SKIP_SAME", "BRANCH_SAME"):
            return self.same >= a + 1
        return super().test(op, a, level)


class A(Branch):
    pass


class B(Sent):
    pass


class Bc(SentCondition):
    pass


class C(Run):
    pass


class D(Same):
    pass


class AB(Branch, Sent):
    pass


class ABc(Branch, SentCondition):
    pass


class AC(Branch, Run):
    pass


class AD(Branch, Same):
    pass


CANDIDATES = {"A": A, "B": B, "Bc": Bc, "C": C, "D": D, "AB": AB, "ABc": ABc, "AC": AC, "AD": AD}
ARBITRATION = ("A", "B", "Bc", "AB", "ABc")  # the candidates spliced into can_tx_arb.asm
STUFFING = ("A", "C", "D", "AC", "AD")  # the candidates spliced into can_tx_stuff.asm


# -- the assembler -----------------------------------------------------------------------


def assemble(source, cls):
    """cpu.assemble on the candidate's ISA, after rewriting the candidate's
    own syntax into the word's fields: `BRANCH bit, level, label` and its
    kin become `BRANCH ahead [condition]`, the condition in the delay bits;
    a run test's n becomes n - 1. Labels are the assembler's, resolved here
    first for the distance ahead. Then the REPEAT rules, a BRANCH held to a
    JMP's."""
    branches, runs = cls.merged("BRANCHES"), cls.merged("RUNS")
    labels, address, parsed = {}, 0, []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        m = LINE_RE.match(line) if line else None
        if line and not m:
            raise SyntaxError(f"line {lineno}: can't parse {line!r}")
        if m and m["label"]:
            labels[m["label"]] = address
        parsed.append((raw, m, address))
        if m and m["op"]:
            address += 1

    def value(lineno, text):
        if text in labels:
            return labels[text]
        try:
            return int(text, 0)
        except ValueError:
            raise SyntaxError(f"line {lineno}: unknown label {text!r}") from None

    out = []
    for lineno, (raw, m, address) in enumerate(parsed, start=1):
        if not (m and m["op"]):
            out.append(raw)
            continue
        op = m["op"].upper()
        args = m["args"].replace(",", " ").split()
        label = f"{m['label']}:" if m["label"] else ""
        if op in branches:
            kind, names = branches[op]
            if m["delay"] is not None:
                raise SyntaxError(f"line {lineno}: {op} takes no delay: bits 12:8 hold the condition")
            if len(args) != len(names) + 1:
                raise SyntaxError(f"line {lineno}: {op} takes {', '.join(names)} and a label, got {len(args)} operand(s)")
            values = [value(lineno, a) for a in args]
            if names[0] == "n" and not 1 <= values[0] <= 8:
                raise SyntaxError(f"line {lineno}: {op} n {values[0]} outside 1..8")
            a = values[0] - 1 if names[0] == "n" else values[0]
            level = values[1] if "level" in names else 0
            if not 0 <= a <= 7 or (names[0] == "pin" and a > 3) or level not in (0, 1):
                raise SyntaxError(f"line {lineno}: {op} {names[0]} {values[0]}, level {level}: out of range")
            ahead = values[-1] - address
            if not 1 <= ahead < 1 << AHEAD_BITS:
                raise SyntaxError(f"line {lineno}: {op} reaches {ahead} words ahead, not 1..{(1 << AHEAD_BITS) - 1}")
            out.append(f"{label:8}BRANCH {ahead} [{kind << KIND_LSB | a << 1 | level}]")
        elif op in runs and op not in ("SKIP_RUN", "SKIP_NORUN"):  # the base assembler writes those two's n - 1 since 2026-09-28
            n = value(lineno, args[0]) if args else 0
            if not 1 <= n <= 8:
                raise SyntaxError(f"line {lineno}: {op} n {n} outside 1..8")
            rest = ", ".join(args[1:])
            delay = f" [{m['delay']}]" if m["delay"] else ""
            out.append(f"{label:8}{op} {n - 1}{', ' + rest if rest else ''}{delay}")
        else:
            out.append(raw)
    words = base_assemble("\n".join(out), cls.isa())
    try:
        check_bodies(words, cls)
    except ValueError as e:
        raise SyntaxError(str(e)) from None
    return words


def check_bodies(words, cls):
    """cpu.check_bodies knows JMP and SKIP; the same rules for a BRANCH, which
    goes ahead, and for the SKIP-shaped words, which step over."""
    ops = [cls.decode(w) for w in words]
    skips = ("SKIP",) + tuple(cls.merged("SKIPS"))
    bodies = [(end - instr.args[0], end) for end, instr in enumerate(ops) if instr.op == "REPEAT"]
    for start, end in bodies:
        if ops[end - 1].op in skips:
            raise ValueError(f"REPEAT at {end}: the body's last word is a {ops[end - 1].op}, which would step over the REPEAT")
        for address, instr in enumerate(ops):
            inside = start <= address < end
            if instr.op == "BRANCH":
                target = address + instr.args[0]
                if inside and not start <= target <= end:
                    raise ValueError(f"REPEAT at {end}: the BRANCH at {address} leaves the body")
                if not inside and start < target <= end:
                    raise ValueError(f"REPEAT at {end}: the BRANCH at {address} lands inside the body past its label")
            if instr.op in skips and not inside and start < address + 2 <= end:
                raise ValueError(f"REPEAT at {end}: the {instr.op} at {address} steps into the body past its label")


def load_program(name, cls):
    """experiments/can/<name>.asm assembled for the candidate."""
    return assemble((HERE / f"{name}.asm").read_text(), cls)


def listing(words, cls):
    """One line per word, the candidate's own words by their mnemonic."""
    kinds, out = cls.merged("KINDS"), []
    for address, word in enumerate(words):
        instr = cls.decode(word)
        if instr.op == "BRANCH":
            kind, a, level = instr.delay >> KIND_LSB, (instr.delay >> 1) & 7, instr.delay & 1
            op = kinds[kind]
            first = a + 1 if op in cls.merged("RUNS") else a
            args = [first] + ([level] if op != "BRANCH_SAME" else []) + [address + instr.args[0]]
            out.append(f"{address:3}  {word:04x}  {op} {', '.join(map(str, args))}")
        elif instr.op == "REPEAT":
            out.append(f"{address:3}  {word:04x}  REPEAT {instr.delay + 1}, {address - instr.args[0]}")
        else:
            args = list(instr.args)
            if instr.op in cls.merged("RUNS"):
                args[0] += 1
            args = ", ".join(str(a) for a in args + list(instr.side or ()))
            out.append(f"{address:3}  {word:04x}  {instr.op} {args} [{instr.delay}]")
    return out
