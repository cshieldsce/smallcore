"""Mini PIO-style CPU that runs 16-bit SET / SHIFT_OUT / PULL / JMP / CONFIG_SHIFT / SHIFT_IN instructions one clock
cycle at a time, driving gpio[3:0] and sampling gpio_in[3:0]: SET picks a pin, SHIFT_OUT always drives gpio[0], SHIFT_IN
samples the pin it names into the input shift register, and both can drive one more pin as a side effect. SHIFT_OUT and
SHIFT_IN are one opcode, SHIFT, told apart by an in/out bit in the operand. CONFIG_SHIFT sets shift_dir, the one bit of
persistent configuration: which end of the shift registers is the wire."""

import re
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
ISA_PATH = ROOT / "isa.yaml"

# e.g. "SET 0, 1 [7]", "SHIFT_OUT [7]", "SHIFT_OUT 1, 0 [3]", "SHIFT_IN 3, 1, 1 [3]", "set 1 0", "loop:", "JMP loop"
LINE_RE = re.compile(
    r"^(?:(?P<label>[A-Za-z_]\w*):)?\s*"
    r"(?:(?P<op>\w+)(?P<args>[^\[]*?)\s*(?:\[\s*(?P<delay>\w+)\s*\])?)?$"
)


class Instruction(NamedTuple):
    op: str
    args: tuple
    delay: int = 0
    side: tuple = None  # (pin, value) GPIO side effect, or None


def load_isa(path=ISA_PATH):
    with open(path) as f:
        isa = yaml.safe_load(f)
    fields = isa["fields"]
    if sum(f["bits"] for f in fields.values()) != isa["word_bits"]:
        raise ValueError("isa.yaml: field widths don't add up to word_bits")
    seen = {}  # (opcode, select value) -> instruction name
    for name, spec in isa["instructions"].items():
        used = 0
        side = spec.get("side_effect")
        select = spec.get("select")
        operands = spec["operands"] + ([select] if select else []) + ([side["flag"]] + side["operands"] if side else [])
        for operand in operands:
            mask = operand_mask(operand)
            if mask >> fields["operand"]["bits"] or used & mask:
                raise ValueError(f"isa.yaml: {name} {operand.get('name', 'flag')} doesn't fit the operand field")
            used |= mask
        key = (spec["opcode"], select["value"] if select else None)
        if key in seen or any(o == spec["opcode"] and (v is None) != (select is None) for o, v in seen):
            raise ValueError(f"isa.yaml: {name} and {seen.get(key)} share opcode {spec['opcode']:#b}")
        seen[key] = name
    for op, pins in ("SET", "gpio_out"), ("SHIFT_IN", "gpio_in"):
        pin = next(o for o in isa["instructions"][op]["operands"] if o["name"] == "pin")
        if 1 << pin["bits"] != isa[pins]:
            raise ValueError(f"isa.yaml: {op} pin doesn't address exactly {pins} pins")
    return isa


def operand_mask(operand):
    return ((1 << operand["bits"]) - 1) << operand["lsb"]


def delay_max(isa):
    return (1 << isa["fields"]["delay"]["bits"]) - 1


def check_operands(instr, isa):
    spec = isa["instructions"][instr.op]
    if len(instr.args) != len(spec["operands"]):
        raise ValueError(f"{instr.op} takes {len(spec['operands'])} operand(s), got {len(instr.args)}")
    checks = list(zip(instr.args, spec["operands"]))
    if instr.side is not None:
        side = spec.get("side_effect")
        if side is None:
            raise ValueError(f"{instr.op} has no GPIO side effect")
        if len(instr.side) != len(side["operands"]):
            raise ValueError(f"{instr.op} side effect takes {len(side['operands'])} operand(s), got {len(instr.side)}")
        if instr.op == "SHIFT_OUT" and instr.side[0] == 0:
            raise ValueError("SHIFT_OUT side effect pin 0 is the shift pin")
        checks += zip(instr.side, side["operands"])
    for value, operand in checks:
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
    spec = isa["instructions"][instr.op]
    operand = 0
    for value, o in zip(instr.args, spec["operands"]):
        operand |= value << o["lsb"]
    if "select" in spec:
        operand |= spec["select"]["value"] << spec["select"]["lsb"]
    if instr.side is not None:
        side = spec["side_effect"]
        operand |= 1 << side["flag"]["lsb"]
        for value, o in zip(instr.side, side["operands"]):
            operand |= value << o["lsb"]
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
    operand = field("operand")
    for op, spec in isa["instructions"].items():
        select = spec.get("select")
        if spec["opcode"] == opcode and (
            not select or (operand & operand_mask(select)) >> select["lsb"] == select["value"]
        ):

            def unpack(operands):
                return tuple((operand & operand_mask(o)) >> o["lsb"] for o in operands)

            used = operand_mask(select) if select else 0
            for o in spec["operands"]:
                used |= operand_mask(o)
            side_spec, side = spec.get("side_effect"), None
            if side_spec:
                used |= operand_mask(side_spec["flag"])
                if operand & operand_mask(side_spec["flag"]):
                    side = unpack(side_spec["operands"])
                    for o in side_spec["operands"]:
                        used |= operand_mask(o)
            if operand & ~used:
                raise ValueError(f"word {word:#06x}: operand bits {operand & ~used:#04x} not used by {op}")
            instr = Instruction(op, unpack(spec["operands"]), field("delay"), side)
            check_operands(instr, isa)
            return instr
    raise ValueError(f"word {word:#06x}: unknown opcode {opcode:#b}")


def assemble(source, isa=None):
    """Turn assembly text into a list of instruction words.

    Labels (`loop:`, alone or before an instruction) name the address of the
    next instruction and can stand in for any operand, e.g. `JMP loop`. They
    are purely an assembler feature: the words only contain addresses.

    Operands written after an instruction's own are its GPIO side effect,
    e.g. `SHIFT_OUT 1, 0 [3]` shifts and drives gpio[1] low, and
    `SHIFT_IN 3, 1, 1 [3]` samples gpio_in[3] and drives gpio[1] high.
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
            n = len(isa["instructions"][op]["operands"])
            side = args[n:] if len(args) > n and "side_effect" in isa["instructions"][op] else None
            words.append(encode(Instruction(op, args[:n] if side else args, delay, side), isa))
        except ValueError as e:
            raise SyntaxError(f"line {lineno}: {e}") from None
    return words


def load_program(path, isa=None):
    return assemble(Path(path).read_text(), isa)


def cycles(instr):
    return 1 + instr.delay


class CPU:
    def __init__(self, program, gpio=1, gpio_in=0, tx_data=(), isa=None):
        self.isa = isa or load_isa()
        self.program = list(program)  # instruction words
        self.pc = 0
        self.gpio = [gpio] * self.isa["gpio_out"]  # output pins, all reset to `gpio`
        self.gpio_in = [gpio_in] * self.isa["gpio_in"]  # input pins: the outside world sets these before each step
        self.shift_reg = 0  # 8-bit, emptied one bit at a time by SHIFT_OUT from the end shift_dir picks
        self.in_shift_reg = 0  # 8-bit, filled one bit at a time by SHIFT_IN from the end opposite shift_dir
        self.shift_dir = 0  # configuration: 0 = wire end is bit 0, registers shift right (LSB first), 1 = bit 7, left (MSB first)
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
                # end bit and the register shifts. RTL must keep this order.
                if self.shift_dir == 0:  # LSB first
                    self.gpio[0] = self.shift_reg & 1
                    self.shift_reg >>= 1
                else:  # MSB first
                    self.gpio[0] = self.shift_reg >> 7
                    self.shift_reg = (self.shift_reg << 1) & 0xFF
            elif instr.op == "SHIFT_IN":
                # Sample the pin as it stands when this cycle executes: what the
                # outside world drove before this clock edge. The side effect
                # below lands on the same edge, so it cannot reach this sample.
                bit = self.gpio_in[instr.args[0]]
                if self.shift_dir == 0:  # LSB first: the sample enters at bit 7 and walks right
                    self.in_shift_reg = (self.in_shift_reg >> 1) | (bit << 7)
                else:  # MSB first: the sample enters at bit 0 and walks left
                    self.in_shift_reg = ((self.in_shift_reg << 1) & 0xFF) | bit
            elif instr.op == "PULL":
                self.shift_reg = self.tx_fifo.pop(0)
            elif instr.op == "CONFIG_SHIFT":
                self.shift_dir = instr.args[0]
            if instr.side is not None:
                # GPIO side effect: one more pin, same edge as the primary operation.
                pin, value = instr.side
                self.gpio[pin] = value
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
        args = ", ".join(str(a) for a in instr.args + (instr.side or ()))
        print(f"{addr:3}  {word:04x}  {instr.op} {args} [{instr.delay}]")
    cpu = CPU(program, tx_data=tx_data, isa=isa)
    while not cpu.halted and not cpu.stalled and cpu.cycle < 100_000:
        cpu.step()
    print(f"{cpu.cycle} cycles, {'stalled on PULL' if cpu.stalled else 'halted' if cpu.halted else 'still running'}, "
          f"shift_dir {cpu.shift_dir} ({'MSB' if cpu.shift_dir else 'LSB'} first), "
          f"in_shift_reg {cpu.in_shift_reg:#04x} (gpio_in held at {cpu.gpio_in[0]})")
    for pin in range(len(cpu.gpio)):
        print(f"gpio{pin} " + "".join(str(level) for level in cpu.pin_trace(pin)))
