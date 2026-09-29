"""Simulator and assembler for the ISA in isa.yaml: a PIO-style CPU stepped one clock cycle at a time, driving
gpio[3:0], push-pull or open-drain per pin, and sampling or waiting on gpio_in[3:0]. isa.yaml is the reference
for what each instruction does."""

import re
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
ISA_PATH = ROOT / "isa" / "isa.yaml"

# e.g. "SET 0, 1 [7]", "SHIFT_OUT [7]", "SHIFT_OUT 1, 0 [3]", "SHIFT_IN 3, 1, 1 [3]", "CONFIG shift_dir, 1", "loop:", "JMP loop",
# "REPEAT 8, bit"
LINE_RE = re.compile(
    r"^(?:(?P<label>[A-Za-z_]\w*):)?\s*"
    r"(?:(?P<op>\w+)(?P<args>[^\[]*?)\s*(?:\[\s*(?P<delay>\w+)\s*\])?)?$"
)


PC_BITS = 9  # the pc: room for the halt address 256 and a SKIP's pc + 2 past it, as in core.v
RUN_TESTS = ("SKIP_RUN", "SKIP_NORUN")  # the run tests, SKIP-shaped: they step over the next word
SKIPS = ("SKIP",) + RUN_TESTS  # every word that steps over the next one
ACC_BITS = 16  # the accumulator and its polynomial


class Instruction(NamedTuple):
    op: str
    args: tuple
    delay: int = 0  # bits 12:8; for REPEAT the count - 1, and the word holds one cycle
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
        side = side_effect(isa, name)
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
    for op, pins in ("SET", "gpio_out"), ("SHIFT_IN", "gpio_in"), ("WAIT", "gpio_in"):
        pin = next(o for o in isa["instructions"][op]["operands"] if o["name"] == "pin")
        if 1 << pin["bits"] != isa[pins]:
            raise ValueError(f"isa.yaml: {op} pin doesn't address exactly {pins} pins")
    if isa["instructions"]["SET"]["operands"] != isa["side_effect"]["operands"]:
        raise ValueError("isa.yaml: SET's operands must be the side effect's bits: there is one pin-write port")
    field, value = (next(o for o in isa["instructions"]["CONFIG"]["operands"] if o["name"] == n) for n in ("field", "value"))
    for name, cfg in isa["config"].items():
        if cfg["field"] >> field["bits"] or cfg["bits"] > value["bits"]:
            raise ValueError(f"isa.yaml: config {name} doesn't fit CONFIG's operands")
    if len({cfg["field"] for cfg in isa["config"].values()}) != len(isa["config"]):
        raise ValueError("isa.yaml: two config registers share a field number")
    return isa


def config_field(isa, field):
    """The config register spec for CONFIG's field number, or None if unassigned."""
    return next((cfg for cfg in isa["config"].values() if cfg["field"] == field), None)


def operand_mask(operand):
    return ((1 << operand["bits"]) - 1) << operand["lsb"]


def side_effect(isa, op):
    """The GPIO side effect spec (one shape for all instructions) if `op` allows one, else None."""
    return isa["side_effect"] if isa["instructions"][op].get("side_effect") else None


def delay_max(isa):
    return (1 << isa["fields"]["delay"]["bits"]) - 1


def check_operands(instr, isa):
    spec = isa["instructions"][instr.op]
    if len(instr.args) != len(spec["operands"]):
        raise ValueError(f"{instr.op} takes {len(spec['operands'])} operand(s), got {len(instr.args)}")
    checks = list(zip(instr.args, spec["operands"]))
    if instr.side is not None:
        side = side_effect(isa, instr.op)
        if side is None:
            raise ValueError(f"{instr.op} has no GPIO side effect")
        if len(instr.side) != len(side["operands"]):
            raise ValueError(f"{instr.op} side effect takes {len(side['operands'])} operand(s), got {len(instr.side)}")
        if instr.op == "SHIFT_OUT" and instr.side[0] == 0:
            raise ValueError("SHIFT_OUT side effect pin 0 is the shift pin")
        checks += zip(instr.side, side["operands"])
    for value, operand in checks:
        if not operand.get("min", 0) <= value < 1 << operand["bits"]:
            raise ValueError(
                f"{instr.op} {operand['name']}={value} outside {operand.get('min', 0)}..{(1 << operand['bits']) - 1}"
            )
    if instr.op == "CONFIG":
        field, value = instr.args
        cfg = config_field(isa, field)
        if cfg is None:
            raise ValueError(f"CONFIG field {field} is unassigned")
        if value >> cfg["bits"]:
            raise ValueError(f"CONFIG field {field} value={value} outside 0..{(1 << cfg['bits']) - 1}")
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
        side = side_effect(isa, instr.op)
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
            side_spec, side = side_effect(isa, op), None
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

    `label:` names the address of the next instruction, for `JMP label` and
    `REPEAT count, label`. Operands after an instruction's own are its GPIO
    side effect: `SHIFT_OUT 1, 0 [3]`. CONFIG takes its field by name:
    `CONFIG shift_dir, 1`. REPEAT is written the natural way round, the count
    then the label, and goes into the word as count - 1 in bits 12:8 and the
    distance back in the operand byte; it takes no `[n]`. A run test is
    written `SKIP_RUN n, level`, n 1..8, and holds n - 1. Labels and names
    never reach the words. A program whose REPEAT bodies break the rules in
    check_bodies() is refused.
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

    def operand(lineno, text, op=None):
        if text in labels:
            return labels[text]
        if op == "CONFIG" and text in isa["config"]:
            return isa["config"][text]["field"]
        try:
            return int(text, 0)
        except ValueError:
            raise SyntaxError(f"line {lineno}: unknown label {text!r}") from None

    words = []
    for address, (lineno, op, args, delay) in enumerate(lines):
        try:
            if op == "REPEAT":
                words.append(encode(repeat(address, args, delay, labels, isa), isa))
                continue
            args = tuple(operand(lineno, a, op if i == 0 else None) for i, a in enumerate(args))
            delay = int(delay, 0) if delay else 0
            if op in RUN_TESTS:  # `SKIP_RUN n, level`, n written 1..8 and held as n - 1
                if not args or not 1 <= args[0] <= 8:
                    raise ValueError(f"{op} n {args[0] if args else '?'} outside 1..8")
                args = (args[0] - 1,) + args[1:]
            n = len(isa["instructions"][op]["operands"])
            side = args[n:] if len(args) > n and side_effect(isa, op) else None
            words.append(encode(Instruction(op, args[:n] if side else args, delay, side), isa))
        except ValueError as e:
            raise SyntaxError(f"line {lineno}: {e}") from None
    try:
        check_bodies(words, isa)
    except ValueError as e:
        raise SyntaxError(str(e)) from None
    return words


def repeat(address, args, delay, labels, isa):
    """`REPEAT count, label` at `address` as an Instruction: count - 1 in the
    delay bits, the label's distance back as the operand. The label may be an
    address, as JMP's target may. No `[n]`: bits 12:8 are the count."""
    if delay is not None:
        raise ValueError("REPEAT takes no delay: bits 12:8 hold the count")
    if len(args) != 2:
        raise ValueError(f"REPEAT takes a count and a label, got {len(args)} operand(s)")
    count_max = 1 << isa["fields"]["delay"]["bits"]
    back = next(o for o in isa["instructions"]["REPEAT"]["operands"] if o["name"] == "back")
    try:
        count = int(args[0], 0)
    except ValueError:
        raise ValueError(f"REPEAT count {args[0]!r} is not a number") from None
    if not 1 <= count <= count_max:
        raise ValueError(f"REPEAT count {count} outside 1..{count_max}")
    if args[1] in labels:
        target = labels[args[1]]
    else:
        try:
            target = int(args[1], 0)
        except ValueError:
            raise ValueError(f"unknown label {args[1]!r}") from None
    distance = address - target
    if not back["min"] <= distance < 1 << back["bits"]:
        raise ValueError(f"REPEAT reaches {distance} words back, not {back['min']}..{(1 << back['bits']) - 1}")
    return Instruction("REPEAT", (distance,), count - 1)


def check_bodies(words, isa):
    """The rules that keep a REPEAT body plain, so the hardware needs no
    machinery for odd control flow: a body (the words from the label to the
    REPEAT) holds no REPEAT, so no nesting and no overlap; a JMP in a body
    lands in it, from the label to the REPEAT; the body's last word is not a
    SKIP or a run test, which would step over the REPEAT; nothing outside
    jumps or skips into a body past its label. Raises ValueError. Outside these rules the
    hardware still does the one thing REPEAT does with whatever rc holds."""
    ops = [decode(w, isa) for w in words]
    bodies = [(end - instr.args[0], end) for end, instr in enumerate(ops) if instr.op == "REPEAT"]
    for start, end in bodies:
        for other_start, other_end in bodies:
            if start <= other_end < end:
                raise ValueError(f"REPEAT at {end}: a REPEAT at {other_end} inside its body, or bodies overlapping")
        if start < 0:
            raise ValueError(f"REPEAT at {end}: reaches {end - start} words back, before the program")
        if ops[end - 1].op in SKIPS:
            raise ValueError(f"REPEAT at {end}: the body's last word is a {ops[end - 1].op}, which would step over the REPEAT")
        for address, instr in enumerate(ops):
            inside = start <= address < end
            if instr.op == "JMP":
                target = instr.args[0]
                if inside and not start <= target <= end:
                    raise ValueError(f"REPEAT at {end}: the JMP at {address} leaves the body")
                if not inside and start < target <= end:
                    raise ValueError(f"REPEAT at {end}: the JMP at {address} lands inside the body past its label")
            if instr.op in SKIPS and not inside and start < address + 2 <= end:
                raise ValueError(f"REPEAT at {end}: the {instr.op} at {address} steps into the body past its label")


def load_program(path, isa=None):
    return assemble(Path(path).read_text(), isa)


def cycles(instr):
    return 1 if instr.op == "REPEAT" else 1 + instr.delay  # REPEAT's bits 12:8 are its count, not a delay


class CPU:
    def __init__(self, program, gpio=1, gpio_in=0, tx_data=(), rx_depth=4, isa=None):
        self.isa = isa or load_isa()
        self.program = list(program)  # instruction words
        self.pc = 0
        self.gpio = [gpio] * self.isa["gpio_out"]  # output pins, all reset to `gpio`
        # Configuration, one bit per pin: 0 = push-pull (reset), gpio[pin] is driven; 1 = open-drain, a 0 is
        # driven and a 1 lets go of the line (see gpio_oe). CONFIG open_drain01 writes [1:0], open_drain23 [3:2].
        self.open_drain = [0] * self.isa["gpio_out"]
        self.gpio_in = [gpio_in] * self.isa["gpio_in"]  # input pins: the outside world sets these before each step
        self.shift_reg = 0  # 8-bit, emptied one bit at a time by SHIFT_OUT from the end shift_dir picks
        self.in_shift_reg = 0  # 8-bit, filled one bit at a time by SHIFT_IN from the end opposite shift_dir
        self.shift_dir = 0  # configuration: 0 = wire end is bit 0, registers shift right (LSB first), 1 = bit 7, left (MSB first)
        self.tx_fifo = list(tx_data)  # bytes waiting for PULL, oldest first (the outside world appends)
        self.rx_fifo = []  # bytes PUSHed, oldest first (the outside world pops from the front)
        self.rx_depth = rx_depth  # RX FIFO capacity: PUSH stalls while len(rx_fifo) == rx_depth
        self.stalled = False  # True while a PULL waits on an empty TX FIFO, a PUSH on a full RX FIFO or a WAIT on a pin level
        self.cycle = 0
        self.counter = 0  # cycles left in the current instruction
        self.rc = 0  # REPEAT's counter, 5 bits: runs of the body still to go, 0 between loops; moves on a REPEAT's cycle only
        self.acc = 0  # the accumulator, 16 bits: the second stream register, shifted towards bit 15 by ACC_IN and ACC_CRC
        self.poly = 0  # its polynomial, 16 bits, left-aligned: ACC_CRC's feedback, loaded a byte at a time by ACC_LOAD
        self.halted = not self.program
        self.trace = []  # gpio levels (gpio[0], gpio[1], ...) at the end of each cycle

    def restart(self, program=None):
        """The chip's restart (top.v's `restart`, a CONTROL write): the core
        back to reset, the FIFOs, the input pins, the cycle count and the
        trace kept. With `program`, a slot change: the same, under it."""
        keep = self.tx_fifo, self.rx_fifo, self.gpio_in, self.cycle, self.trace
        self.__init__(self.program if program is None else program, rx_depth=self.rx_depth, isa=self.isa)
        self.tx_fifo, self.rx_fifo, self.gpio_in, self.cycle, self.trace = keep

    @property
    def gpio_oe(self):
        """Output enable per pin, combinational: gpio_oe[k] = !(open_drain[k] & gpio[k]). The pad drives
        gpio[k] while it is 1 and lets go while it is 0, so an open-drain pin drives its 0s and releases on
        a 1; a push-pull pin is always driven. The outside world resolves a released line."""
        return [0 if od and level else 1 for od, level in zip(self.open_drain, self.gpio)]

    def pin_trace(self, pin):
        """One pin's level at the end of each cycle."""
        return [levels[pin] for levels in self.trace]

    def newest(self, n):
        """The newest n samples in in_shift_reg, oldest first: the n bits at
        the end SHIFT_IN fills, bit 0 MSB first, bit 7 LSB first."""
        if self.shift_dir == 0:
            return [(self.in_shift_reg >> (8 - n + i)) & 1 for i in range(n)]
        return [(self.in_shift_reg >> (n - 1 - i)) & 1 for i in range(n)]

    def run_test(self, instr):
        """SKIP_RUN: the newest n samples all `level`; SKIP_NORUN: not so."""
        n, level = instr.args[0] + 1, instr.args[1]
        run = all(bit == level for bit in self.newest(n))
        return run if instr.op == "SKIP_RUN" else not run

    def step(self):
        """Advance exactly one clock cycle."""
        if self.halted:
            raise RuntimeError("CPU is halted")

        instr = decode(self.program[self.pc], self.isa)  # imem[pc], visible every cycle
        if self.counter == 0:
            if ((instr.op == "PULL" and not self.tx_fifo) or (instr.op in ("PUSH", "ACC_PUSH") and len(self.rx_fifo) >= self.rx_depth)
                    or (instr.op == "WAIT" and self.gpio_in[instr.args[0]] != instr.args[1])):
                # Block: stay on this PULL / PUSH / WAIT, pins unchanged, until there is a
                # byte / room / the level. The pin is read as SHIFT_IN samples it: what the
                # outside world drove before this edge. One stall port, three conditions.
                self.stalled = True
                self.trace.append(tuple(self.gpio))
                self.cycle += 1
                return
            self.stalled = False
            if instr.op == "SHIFT_OUT":
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
            elif instr.op == "PUSH":
                self.rx_fifo.append(self.in_shift_reg)  # the register keeps its value
            elif instr.op in ("ACC_IN", "ACC_CRC"):
                # The pad sampled as SHIFT_IN samples it; ACC_CRC feeds the bit that leaves back in.
                bit = self.gpio_in[instr.args[0]]
                top = self.acc >> (ACC_BITS - 1)
                self.acc = ((self.acc << 1) & 0xFFFF) | (bit if instr.op == "ACC_IN" else 0)
                if instr.op == "ACC_CRC" and top ^ bit:
                    self.acc ^= self.poly
            elif instr.op == "ACC_OUT":
                self.gpio[instr.args[0]] = self.acc >> (ACC_BITS - 1)  # the pin-write port, as SET's
                self.acc = (self.acc << 1) & 0xFFFF
            elif instr.op == "ACC_PUSH":
                self.rx_fifo.append(self.acc & 0xFF)
                self.acc >>= 8
            elif instr.op == "ACC_LOAD":
                self.poly = (self.shift_reg << 8) | (self.poly >> 8)
            elif instr.op == "CONFIG":
                # One write port into the configuration registers, field-decoded.
                field, value = instr.args
                config = self.isa["config"]
                if field == config["shift_dir"]["field"]:
                    self.shift_dir = value
                elif field == config["open_drain01"]["field"]:
                    self.open_drain[0:2] = [value & 1, value >> 1]
                elif field == config["open_drain23"]["field"]:
                    self.open_drain[2:4] = [value & 1, value >> 1]
            # The one pin-write port: SET's operands and every other instruction's
            # GPIO side effect land here, on the same edge as the primary operation.
            pin_write = instr.args if instr.op == "SET" else instr.side
            if pin_write is not None:
                pin, value = pin_write
                self.gpio[pin] = value
            self.counter = cycles(instr)

        self.counter -= 1
        if self.counter == 0:
            # Last cycle of the instruction: JMP loads its target, SKIP steps over the next word
            # (pc + 2) when the bit of in_shift_reg it names holds the level, a run test when the
            # newest n samples are all the level (SKIP_RUN) or not (SKIP_NORUN), REPEAT goes back
            # while runs of the body are left, everything else pc + 1.
            if instr.op == "JMP":
                self.pc = instr.args[0]
            elif instr.op == "SKIP" and (self.in_shift_reg >> instr.args[0]) & 1 == instr.args[1]:
                self.pc += 2
            elif instr.op in RUN_TESTS and self.run_test(instr):
                self.pc += 2
            elif instr.op == "REPEAT":
                # The one cycle rc changes: 0 loads count - 1, the runs still to go; any other
                # rc loses one. Back to the label while any are left; a back past word 0 wraps
                # the nine-bit pc past the end, as core.v's subtract does, and halts.
                self.rc = instr.delay if self.rc == 0 else self.rc - 1
                self.pc = (self.pc - instr.args[0]) % (1 << PC_BITS) if self.rc else self.pc + 1
            else:
                self.pc += 1
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
                why = f"stalled on {decode(self.program[self.pc], self.isa).op}" if self.stalled else "did not halt"
                raise RuntimeError(f"{why} within {max_cycles} cycles")
            self.step()
        return self.trace


if __name__ == "__main__":
    # usage: cpu.py [program.asm [tx byte ...]]   e.g. cpu.py programs/uart/uart_tx_loop.asm 0x55 0xA3
    path = sys.argv[1] if len(sys.argv) > 1 else ROOT / "programs" / "uart" / "uart_tx_0x55.asm"
    tx_data = [int(b, 0) for b in sys.argv[2:]]
    isa = load_isa()
    program = load_program(path, isa)
    for addr, word in enumerate(program):
        instr = decode(word, isa)
        args = ", ".join(str(a) for a in instr.args + (instr.side or ()))
        if instr.op == "REPEAT":  # as written: the count, then the label's address
            args = f"{instr.delay + 1}, {addr - instr.args[0]}"
        elif instr.op in RUN_TESTS:  # as written: n, not n - 1
            args = f"{instr.args[0] + 1}, {instr.args[1]}"
        print(f"{addr:3}  {word:04x}  {instr.op} {args} [{instr.delay}]")
    cpu = CPU(program, tx_data=tx_data, isa=isa)
    while not cpu.halted and not cpu.stalled and cpu.cycle < 100_000:
        cpu.step()
    state = f"stalled on {decode(program[cpu.pc], isa).op}" if cpu.stalled else "halted" if cpu.halted else "still running"
    print(f"{cpu.cycle} cycles, {state}, shift_dir {cpu.shift_dir} ({'MSB' if cpu.shift_dir else 'LSB'} first), "
          f"in_shift_reg {cpu.in_shift_reg:#04x} (gpio_in held at {cpu.gpio_in[0]}), "
          f"rx_fifo [{', '.join(f'{b:#04x}' for b in cpu.rx_fifo)}]")
    for pin in range(len(cpu.gpio)):
        print(f"gpio{pin} " + "".join(str(level) for level in cpu.pin_trace(pin)))
