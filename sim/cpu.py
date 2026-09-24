"""Mini PIO-style CPU that runs 16-bit SET / SHIFT_OUT / PULL / JMP instructions one clock cycle at a time,
driving gpio[3:0]: SET picks a pin, SHIFT_OUT always drives gpio[0]."""

import re
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
ISA_PATH = ROOT / "isa.yaml"

# e.g. "SET 0, 1 [7]", "SHIFT_OUT [7]", "set 1 0", "loop:", "loop: PULL", "JMP loop"
LINE_RE = re.compile(
    r"^(?:(?P<label>[A-Za-z_]\w*):)?\s*"
    r"(?:(?P<op>\w+)(?P<args>[^\[]*?)\s*(?:\[\s*(?P<delay>\w+)\s*\])?)?$"
)


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
    for name, spec in isa["instructions"].items():
        used = 0
        for operand in spec["operands"]:
            mask = operand_mask(operand)
            if mask >> fields["operand"]["bits"] or used & mask:
                raise ValueError(f"isa.yaml: {name} {operand['name']} doesn't fit the operand field")
            used |= mask
    pin = next(o for o in isa["instructions"]["SET"]["operands"] if o["name"] == "pin")
    if 1 << pin["bits"] != isa["gpio_out"]:
        raise ValueError("isa.yaml: SET pin doesn't address exactly gpio_out pins")
    return isa


def operand_mask(operand):
    return ((1 << operand["bits"]) - 1) << operand["lsb"]


def delay_max(isa):
    return (1 << isa["fields"]["delay"]["bits"]) - 1


def check_operands(instr, isa):
    spec = isa["instructions"][instr.op]["operands"]
    if len(instr.args) != len(spec):
        raise ValueError(f"{instr.op} takes {len(spec)} operand(s), got {len(instr.args)}")
    for value, operand in zip(instr.args, spec):
        if not 0 <= value < 1 << operand["bits"]:
            raise ValueError(
                f"{instr.op} {operand['name']}={value} outside 0..{(1 << operand['bits']) - 1}"
            )
    if not 0 <= instr.delay <= delay_max(isa):
        raise ValueError(f"delay {instr.delay} outside 0..{delay_max(isa)}")


def encode(instr, isa):
    """Pack an Instruction into its instruction word."""
    check_operands(instr, isa)
    fields = isa["fields"]
    operand = 0
    for value, spec in zip(instr.args, isa["instructions"][instr.op]["operands"]):
        operand |= value << spec["lsb"]
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
            operand = field("operand")
            used = 0
            for o in spec["operands"]:
                used |= operand_mask(o)
            if operand & ~used:
                raise ValueError(f"word {word:#06x}: operand bits {operand & ~used:#04x} not used by {op}")
            args = tuple((operand & operand_mask(o)) >> o["lsb"] for o in spec["operands"])
            instr = Instruction(op, args, field("delay"))
            check_operands(instr, isa)
            return instr
    raise ValueError(f"word {word:#06x}: unknown opcode {opcode:#b}")


def assemble(source, isa=None):
    """Turn assembly text into a list of instruction words.

    Labels (`loop:`, alone or before an instruction) name the address of the
    next instruction and can stand in for any operand, e.g. `JMP loop`. They
    are purely an assembler feature: the words only contain addresses.
    """
    isa = isa or load_isa()
    labels = {}
    lines = []  # (lineno, op, args as written, delay) in address order
    for lineno, line in enumerate(source.splitlines(), start=1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = LINE_RE.match(line)
        if not m:
            raise SyntaxError(f"line {lineno}: can't parse {line!r}")
        if m["label"]:
            if m["label"] in labels:
                raise SyntaxError(f"line {lineno}: label {m['label']!r} defined twice")
            labels[m["label"]] = len(lines)
        if m["op"]:
            op = m["op"].upper()
            if op not in isa["instructions"]:
                raise SyntaxError(f"line {lineno}: unknown instruction {op!r}")
            lines.append((lineno, op, m["args"].replace(",", " ").split(), m["delay"]))

    def operand(lineno, text):
        if text in labels:
            return labels[text]
        try:
            return int(text, 0)
        except ValueError:
            raise SyntaxError(f"line {lineno}: unknown label {text!r}") from None

    words = []
    for lineno, op, args, delay in lines:
        try:
            args = tuple(operand(lineno, a) for a in args)
            delay = int(delay, 0) if delay else 0
            words.append(encode(Instruction(op, args, delay), isa))
        except ValueError as e:
            raise SyntaxError(f"line {lineno}: {e}") from None
    return words


def load_program(path, isa=None):
    return assemble(Path(path).read_text(), isa)


def cycles(instr):
    return 1 + instr.delay


class CPU:
    def __init__(self, program, gpio=1, tx_data=(), isa=None):
        self.isa = isa or load_isa()
        self.program = list(program)  # instruction words
        self.pc = 0
        self.gpio = [gpio] * self.isa["gpio_out"]  # output pins, all reset to `gpio`
        self.shift_reg = 0  # 8-bit, shifted out LSB first
        self.tx_fifo = list(tx_data)  # bytes waiting for PULL, oldest first
        self.stalled = False  # True while a PULL is waiting on an empty FIFO
        self.cycle = 0
        self.counter = 0  # cycles left in the current instruction
        self.halted = not self.program
        self.trace = []  # gpio levels (gpio[0], gpio[1], ...) at the end of each cycle

    def pin_trace(self, pin):
        """One pin's level at the end of each cycle."""
        return [levels[pin] for levels in self.trace]

    def step(self):
        """Advance exactly one clock cycle."""
        if self.halted:
            raise RuntimeError("CPU is halted")

        instr = decode(self.program[self.pc], self.isa)  # imem[pc], visible every cycle
        if self.counter == 0:
            if instr.op == "PULL" and not self.tx_fifo:
                # Block: stay on this PULL, pins unchanged, until a byte arrives.
                self.stalled = True
                self.trace.append(tuple(self.gpio))
                self.cycle += 1
                return
            self.stalled = False
            if instr.op == "SET":
                pin, value = instr.args
                self.gpio[pin] = value
            elif instr.op == "SHIFT_OUT":
                # Both happen on this one clock edge: gpio[0] takes the old
                # bit 0 and the register shifts. RTL must keep this order.
                self.gpio[0] = self.shift_reg & 1
                self.shift_reg >>= 1
            elif instr.op == "PULL":
                self.shift_reg = self.tx_fifo.pop(0)
            self.counter = cycles(instr)

        self.counter -= 1
        if self.counter == 0:
            # Last cycle of the instruction: JMP loads its target, everything else PC + 1.
            self.pc = instr.args[0] if instr.op == "JMP" else self.pc + 1
            self.halted = self.pc >= len(self.program)

        self.trace.append(tuple(self.gpio))
        self.cycle += 1

    def run_cycles(self, n):
        """Step n cycles (fewer if the CPU halts first). Returns the trace so far."""
        for _ in range(n):
            if self.halted:
                break
            self.step()
        return self.trace

    def run(self, max_cycles=100_000):
        while not self.halted:
            if self.cycle >= max_cycles:
                why = "stalled on PULL with an empty TX FIFO" if self.stalled else "did not halt"
                raise RuntimeError(f"{why} within {max_cycles} cycles")
            self.step()
        return self.trace


if __name__ == "__main__":
    # usage: cpu.py [program.asm [tx byte ...]]   e.g. cpu.py programs/uart_tx_loop.asm 0x55 0xA3
    path = sys.argv[1] if len(sys.argv) > 1 else ROOT / "programs" / "uart_tx_0x55.asm"
    tx_data = [int(b, 0) for b in sys.argv[2:]]
    isa = load_isa()
    program = load_program(path, isa)
    for addr, word in enumerate(program):
        instr = decode(word, isa)
        args = " ".join(str(a) for a in instr.args)
        print(f"{addr:3}  {word:04x}  {instr.op} {args} [{instr.delay}]")
    cpu = CPU(program, tx_data=tx_data, isa=isa)
    while not cpu.halted and not cpu.stalled and cpu.cycle < 100_000:
        cpu.step()
    print(f"{cpu.cycle} cycles, {'stalled on PULL' if cpu.stalled else 'halted' if cpu.halted else 'still running'}")
    for pin in range(len(cpu.gpio)):
        print(f"gpio{pin} " + "".join(str(level) for level in cpu.pin_trace(pin)))
