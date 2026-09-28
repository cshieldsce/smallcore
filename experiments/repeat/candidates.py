"""Model-only ISA variants for the repeat comparison (docs/repeat-candidates.md).

SWD left one architectural complaint: the same two-word bit cell 32 times, 64 of
each program's words (README, "SWD by the numbers"). Each candidate here is
isa.yaml plus its own words and a CPU that runs them, spliced into the exact
swd_read.asm and swd_write.asm and measured against them. Nothing here touches
sim/cpu.py, isa.yaml or the RTL: the 103- and 106-word programs stay as the
baseline.

  A  REPEAT count, label   a counted backward branch at the end of the body,
                           count - 1 in the word's delay bits, the distance
                           back in its operand byte, one counter
  B  REPEAT_NEXT count     the next word again, count times: one-word bodies only
  C  LOAD count / DJNZ label
                           the conventional shape: a counter loaded by one word,
                           decremented and tested by another
  D  BURST_OUT / BURST_IN  eight shift cells in one word: the shift with its side
                           effect, then the side pin returned, eight times, the
                           last return left to the next word; bit 0 of the SHIFT
                           word, which is spare; no new opcode, no count

`Candidate` is cpu.CPU's step word for word with hooks for the new words, so
the existing suite run against it (`suite.py`) checks the copy before the
extensions. The chip's restart, every register back to reset with the FIFOs
kept, is cpu.CPU.restart(); a candidate's own state goes with the rest.

A was adopted on 2026-09-27: REPEAT is isa.yaml's opcode 111, the counter
cpu.py's `rc`, the rules the assembler's. The candidates here start from the
ISA as it stood for the comparison, opcode 111 free, so the comparison runs as
it ran; A's word is the adopted one, spec for spec, and its assembler is the
assembler.
"""

import copy
from pathlib import Path

from cpu import CPU, Instruction, cycles, decode, load_isa

HERE = Path(__file__).resolve().parent
FREE = 0b111  # the opcode isa.yaml left free until REPEAT took it


class Candidate(CPU):
    """cpu.CPU with the step written out and three hooks: `execute` for a new
    word's first cycle, `cycles_of` for how long it holds, `advance` for where
    pc goes on its last cycle. Bursts (D) override step itself."""

    NEW = {}  # instruction name -> spec, added to isa.yaml's
    SELECTS = {}  # instruction name -> select spec, replacing isa.yaml's
    _isa = None

    @classmethod
    def isa(cls):
        if cls.__dict__.get("_isa") is None:  # one cache per class, not the parent's
            isa = copy.deepcopy(load_isa())
            for name in [n for n, spec in isa["instructions"].items() if spec["opcode"] == FREE]:
                del isa["instructions"][name]  # the ISA as it stood for the comparison: 111 free
            for name, select in cls.SELECTS.items():
                isa["instructions"][name]["select"] = select
            isa["instructions"].update(copy.deepcopy(cls.NEW))
            cls._isa = isa
        return cls._isa

    def __init__(self, program, gpio=1, gpio_in=0, tx_data=(), rx_depth=4, isa=None):
        super().__init__(program, gpio, gpio_in, tx_data, rx_depth, isa or self.isa())
        self.reset_state()

    def reset_state(self):
        """The candidate's own registers, at reset."""

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

    def shift_in(self, pin):
        bit = self.gpio_in[pin]
        if self.shift_dir == 0:
            self.in_shift_reg = (self.in_shift_reg >> 1) | (bit << 7)
        else:
            self.in_shift_reg = ((self.in_shift_reg << 1) & 0xFF) | bit

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
        raise ValueError(f"{instr.op}: not an instruction of this candidate")

    def cycles_of(self, instr):
        return cycles(instr)

    def advance(self, instr):
        """pc on the instruction's last cycle: JMP, SKIP, or the next word."""
        if instr.op == "JMP":
            self.pc = instr.args[0]
        elif instr.op == "SKIP" and (self.in_shift_reg >> instr.args[0]) & 1 == instr.args[1]:
            self.pc += 2
        else:
            self.pc += 1

    def finish(self):
        self.halted = self.pc >= len(self.program)
        self.trace.append(tuple(self.gpio))
        self.cycle += 1

    def step(self):
        if self.halted:
            raise RuntimeError("CPU is halted")
        instr = decode(self.program[self.pc], self.isa)
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
                self.shift_in(instr.args[0])
            elif instr.op == "PULL":
                self.shift_reg = self.tx_fifo.pop(0)
            elif instr.op == "PUSH":
                self.rx_fifo.append(self.in_shift_reg)
            elif instr.op == "CONFIG":
                self.config(*instr.args)
            elif instr.op not in ("NOP", "SET", "WAIT", "SKIP", "JMP"):
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


class A(Candidate):
    """REPEAT count, label: at the end of a body, back to `label` until the
    body has run `count` times, 1..32, `count - 1` in bits 12:8 (the delay
    bits of every other word: REPEAT holds one cycle and has no delay). Bits
    7:0 are `back`, the body's length in words, 1..255: pc <- pc - back, so
    the reach is bounded and the program is not. No side effect: no bits are
    left for one. The counter `rc`, six bits, is 0 while no loop is under
    way. The REPEAT's one cycle is when it changes, and the only time: on
    arrival with rc == 0 it loads `count`; every arrival then takes one off
    and jumps back while the result is not 0. A body word stalling, or
    holding its delay, does nothing to rc. Reset and restart clear it.

    Programs that keep the rules the assembler checks (`assemble`): a body
    holds no REPEAT (no nesting, no overlap); a JMP in a body lands in it,
    from the label to the REPEAT; the body's last word is not a SKIP (it
    would step over the REPEAT); nothing outside jumps or skips into a body
    past its label. Outside the rules the hardware still does the one thing
    above with whatever rc holds.

    Adopted: this is isa.yaml's REPEAT, taken from there spec for spec; the
    rules moved into cpu.check_bodies()."""

    NEW = {"REPEAT": copy.deepcopy(load_isa()["instructions"]["REPEAT"])}

    def reset_state(self):
        self.rc = 0

    def state(self):
        return (self.rc,)

    def execute(self, instr):
        if instr.op != "REPEAT":
            super().execute(instr)

    def cycles_of(self, instr):
        return 1 if instr.op == "REPEAT" else cycles(instr)

    def advance(self, instr):
        if instr.op == "REPEAT":
            if self.rc == 0:
                self.rc = instr.delay + 1  # the count
            self.rc -= 1
            self.pc = self.pc - instr.args[0] if self.rc > 0 else self.pc + 1
        else:
            super().advance(instr)


    @staticmethod
    def unroll(words):
        """What a REPEAT program means, as a program for the ISA as it is: each
        body `count` times over, a NOP after each for the REPEAT's cycle. The
        oracle the corner tests hold A to. Bodies must not hold a JMP: the
        addresses move."""
        isa = A.isa()
        nop = 0
        out = []
        for word in words:
            instr = decode(word, isa)
            if instr.op == "REPEAT":
                back, count = instr.args[0], instr.delay + 1
                body = out[-back:]
                out.append(nop)
                for _ in range(count - 1):
                    out.extend(body + [nop])
            else:
                out.append(word)
        return out


class B(Candidate):
    """REPEAT_NEXT count: the next word runs `count` times before pc moves
    on. One 5-bit counter `rn`, loaded by REPEAT_NEXT, counted down as the
    word after it completes; the word's stalls and delay play out every
    time. One cycle for the REPEAT_NEXT itself. The repeated word must not be
    a JMP, SKIP or REPEAT_NEXT."""

    NEW = {
        "REPEAT_NEXT": {
            "opcode": FREE,
            "description": "the next word runs `count` times; operand bits 4:0, one cycle.",
            "operands": [{"name": "count", "lsb": 0, "bits": 5}],
        }
    }

    def reset_state(self):
        self.rn = 0

    def state(self):
        return (self.rn,)

    def execute(self, instr):
        if instr.op != "REPEAT_NEXT":
            super().execute(instr)
        self.rn = instr.args[0]

    def advance(self, instr):
        if instr.op != "REPEAT_NEXT" and self.rn > 1:
            self.rn -= 1  # the same word again
        else:
            if instr.op != "REPEAT_NEXT":
                self.rn = 0
            super().advance(instr)


class C(Candidate):
    """LOAD count / DJNZ label: a 5-bit counter `rc` a word of its own loads,
    and a word that decrements it and jumps while it is not 0. Two words per
    loop; the LOAD may sit anywhere before the loop, on any path. Both share
    the free opcode on operand bit 7, so DJNZ's target is 7 bits: programs
    of at most 128 words, unless the count moves into the delay bits as in
    A. Both hold 1 + delay cycles like any word."""

    NEW = {
        "LOAD": {
            "opcode": FREE,
            "select": {"name": "djnz", "lsb": 7, "bits": 1, "value": 0},
            "description": "rc <- count, operand bits 4:0.",
            "operands": [{"name": "count", "lsb": 0, "bits": 5}],
        },
        "DJNZ": {
            "opcode": FREE,
            "select": {"name": "djnz", "lsb": 7, "bits": 1, "value": 1},
            "description": "rc <- rc - 1; pc <- target while rc != 0. A 7-bit target.",
            "operands": [{"name": "target", "lsb": 0, "bits": 7}],
        },
    }

    def reset_state(self):
        self.rc = 0

    def state(self):
        return (self.rc,)

    def execute(self, instr):
        if instr.op == "LOAD":
            self.rc = instr.args[0]
        elif instr.op != "DJNZ":
            super().execute(instr)

    def advance(self, instr):
        if instr.op == "DJNZ":
            self.rc = max(self.rc - 1, 0)
            self.pc = instr.args[0] if self.rc > 0 else self.pc + 1
        else:
            super().advance(instr)


class D(Candidate):
    """BURST_OUT / BURST_IN: SHIFT_OUT / SHIFT_IN eight times from one word.
    Each cell is the shift with the side effect on its edge, held 1 + delay
    cycles, then the side pin returned to the other level for 1 + delay
    cycles: `BURST_IN 0, 1, 1 [3]` is `SHIFT_IN 0, 1, 1 [3]` and `SET 1, 0
    [3]` eight times over. The eighth cell has no return: the next word does
    that, a PUSH, a PULL's clock, whatever the protocol puts there, so a
    burst is the unrolled cells less their last clock word, cycle for cycle.
    Without a side effect the return half still holds its cycles. Encoded in
    bit 0 of the SHIFT word, spare until now: bits 1:0 select SHIFT_OUT 00,
    BURST_OUT 01, SHIFT_IN 10, BURST_IN 11. State: which cell (3 bits) and
    which half (1 bit). Eight because the registers are eight wide: a burst
    is a byte. A burst never stalls and nothing can happen inside one."""

    SELECTS = {
        "SHIFT_OUT": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b00},
        "SHIFT_IN": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b10},
    }
    NEW = {
        "BURST_OUT": {
            "opcode": 0b001,
            "select": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b01},
            "description": "SHIFT_OUT with its side effect, then the side pin returned, eight times, less the last return.",
            "operands": [],
            "side_effect": True,
        },
        "BURST_IN": {
            "opcode": 0b001,
            "select": {"name": "kind", "lsb": 0, "bits": 2, "value": 0b11},
            "description": "SHIFT_IN pin with its side effect, then the side pin returned, eight times, less the last return.",
            "operands": [{"name": "pin", "lsb": 2, "bits": 2}],
            "side_effect": True,
        },
    }
    CELLS = 8

    def reset_state(self):
        self.cell = 0  # cells done in the burst under way
        self.returning = False  # in a cell's return half

    def state(self):
        return (self.cell, self.returning)

    def step(self):
        if self.halted:
            raise RuntimeError("CPU is halted")
        instr = decode(self.program[self.pc], self.isa)
        if instr.op not in ("BURST_OUT", "BURST_IN"):
            return super().step()
        if self.counter == 0:
            self.stalled = False
            if not self.returning:
                if instr.op == "BURST_OUT":
                    self.shift_out()
                else:
                    self.shift_in(instr.args[0])
                if instr.side is not None:
                    pin, value = instr.side
                    self.gpio[pin] = value
            elif instr.side is not None:
                pin, value = instr.side
                self.gpio[pin] = 1 - value
            self.counter = cycles(instr)
        self.counter -= 1
        if self.counter == 0:
            if self.returning:
                self.returning = False
            else:
                self.cell += 1
                if self.cell == self.CELLS:
                    self.cell = 0
                    self.pc += 1
                else:
                    self.returning = True
        self.finish()


CANDIDATES = {"A": A, "B": B, "C": C, "D": D}


def assemble(source, candidate):
    """cpu.assemble with the candidate's ISA. `REPEAT count, label` is the
    assembler's own syntax since A was adopted, its rules included."""
    from cpu import assemble as base

    return base(source, candidate.isa())


def load_program(name, candidate):
    """experiments/repeat/<name>.asm assembled for `candidate`."""
    return assemble((HERE / f"{name}.asm").read_text(), candidate)


def listing(words, candidate):
    return [decode(w, candidate.isa()) for w in words]
