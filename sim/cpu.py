"""Mini PIO-style CPU that runs 16-bit SET / WAIT instructions one clock cycle at a time."""

import re
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
ISA_PATH = ROOT / "isa.yaml"

# e.g. "SET 1 [7]", "WAIT 100", "set 0"
LINE_RE = re.compile(r"^(?P<op>\w+)(?P<args>[^\[]*?)\s*(?:\[\s*(?P<delay>\w+)\s*\])?$")


class Instruction(NamedTuple):
    op: str
    args: tuple
    delay: int = 0


def load_isa(path=ISA_PATH):
    with open(path) as f:
        isa = yaml.safe_load(f)
    fields = isa["fields"]
    if sum(f["bits"] for f in fields.values()) != isa["word_bits"]:
        raise ValueError("isa.yaml: field widths don't add up to word_bits")
    operand_max = (1 << fields["operand"]["bits"]) - 1
    for name, spec in isa["instructions"].items():
        for operand in spec["operands"]:
            if operand["max"] > operand_max:
                raise ValueError(f"isa.yaml: {name} {operand['name']} doesn't fit the operand field")
    return isa


def delay_max(isa):
    return (1 << isa["fields"]["delay"]["bits"]) - 1


def check_operands(instr, isa):
    spec = isa["instructions"][instr.op]["operands"]
    if len(instr.args) != len(spec):
        raise ValueError(f"{instr.op} takes {len(spec)} operand(s), got {len(instr.args)}")
    for value, operand in zip(instr.args, spec):
        if not operand["min"] <= value <= operand["max"]:
            raise ValueError(
                f"{instr.op} {operand['name']}={value} outside {operand['min']}..{operand['max']}"
            )
    if not 0 <= instr.delay <= delay_max(isa):
        raise ValueError(f"delay {instr.delay} outside 0..{delay_max(isa)}")


def encode(instr, isa):
    """Pack an Instruction into its instruction word."""
    check_operands(instr, isa)
    fields = isa["fields"]
    operand = instr.args[0] if instr.args else 0
    return (
        (isa["instructions"][instr.op]["opcode"] << fields["opcode"]["lsb"])
        | (instr.delay << fields["delay"]["lsb"])
        | (operand << fields["operand"]["lsb"])
    )


def decode(word, isa):
    """Unpack an instruction word into an Instruction."""
    fields = isa["fields"]

    def field(name):
        return (word >> fields[name]["lsb"]) & ((1 << fields[name]["bits"]) - 1)

    if not 0 <= word < (1 << isa["word_bits"]):
        raise ValueError(f"word {word:#x} wider than {isa['word_bits']} bits")
    opcode = field("opcode")
    for op, spec in isa["instructions"].items():
        if spec["opcode"] == opcode:
            args = (field("operand"),) if spec["operands"] else ()
            instr = Instruction(op, args, field("delay"))
            check_operands(instr, isa)
            return instr
    raise ValueError(f"word {word:#06x}: unknown opcode {opcode:#b}")


def assemble(source, isa=None):
    """Turn assembly text into a list of instruction words."""
    isa = isa or load_isa()
    words = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = LINE_RE.match(line)
        if not m:
            raise SyntaxError(f"line {lineno}: can't parse {line!r}")
        op = m["op"].upper()
        if op not in isa["instructions"]:
            raise SyntaxError(f"line {lineno}: unknown instruction {op!r}")
        try:
            args = tuple(int(a, 0) for a in m["args"].replace(",", " ").split())
            delay = int(m["delay"], 0) if m["delay"] else 0
            words.append(encode(Instruction(op, args, delay), isa))
        except ValueError as e:
            raise SyntaxError(f"line {lineno}: {e}") from None
    return words


def load_program(path, isa=None):
    return assemble(Path(path).read_text(), isa)


def cycles(instr):
    base = 1 if instr.op == "SET" else instr.args[0]
    return base + instr.delay


class CPU:
    def __init__(self, program, pin=1, isa=None):
        self.isa = isa or load_isa()
        self.program = list(program)  # instruction words
        self.pc = 0
        self.pin = pin
        self.cycle = 0
        self.counter = 0  # cycles left in the current instruction
        self.halted = not self.program
        self.trace = []  # pin level at the end of each cycle

    def step(self):
        """Advance exactly one clock cycle."""
        if self.halted:
            raise RuntimeError("CPU is halted")

        if self.counter == 0:
            instr = decode(self.program[self.pc], self.isa)
            if instr.op == "SET":
                self.pin = instr.args[0]
            self.counter = cycles(instr)

        self.counter -= 1
        if self.counter == 0:
            self.pc += 1
            self.halted = self.pc >= len(self.program)

        self.trace.append(self.pin)
        self.cycle += 1

    def run(self, max_cycles=100_000):
        while not self.halted:
            if self.cycle >= max_cycles:
                raise RuntimeError(f"did not halt within {max_cycles} cycles")
            self.step()
        return self.trace


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else ROOT / "programs" / "uart_tx_0x55.asm"
    isa = load_isa()
    program = load_program(path, isa)
    for addr, word in enumerate(program):
        instr = decode(word, isa)
        args = " ".join(str(a) for a in instr.args)
        print(f"{addr:3}  {word:04x}  {instr.op} {args} [{instr.delay}]")
    trace = CPU(program, isa=isa).run()
    print(f"{len(trace)} cycles")
    print("".join(str(level) for level in trace))
