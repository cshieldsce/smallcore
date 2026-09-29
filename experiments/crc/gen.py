"""Write the CRC state candidates' programs into experiments/crc/.

    python experiments/crc/gen.py

Every CRC program here does what crc4_lfsr.asm does, at the width its
candidate holds: four host bytes out on pin 0 MSB first and back through the
pad, the register kept from its input end, the Fibonacci form, f_t = in_t ^
XOR over the taps of the feedback bits before it; the parity as two paths
through SKIPs that meet on pin 1, cleared by the cell's first word and set
on the odd paths, then sampled back in. Then the CRC out on pin 1 MSB first,
one bit per run of the `crc` body: the register's top bit is the feedback
with a 0 in, the same tree, and feeding a 0 back in its place shifts the
register without feedback, so the emission cell is the data cell with a 0
for the input and a 0 for the feedback, both from pin 3, held at 0.

  crc15_w32, crc8_w16      the input in the register: f_{t-1-i} at age 2i + 1
  crc15_pin16, crc8_pin8   the input as SKIP_PIN's condition: f_{t-1-i} at age i
  crc8_lanes               the input in lane 0, the window in lane 1
  crc15_acc, _bytes        the accumulator, two words a bit

And the receivers, can_rx_bits_C.asm's cell with the data bit gathered in a
second register and pushed a byte at a time: can_rx_bytes_lanes,
can_rx_bytes_acc.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent / "model")]

from candidates import CANDIDATES, assemble  # noqa: E402

POLY15, POLY8 = 0x4599, 0x07


def taps(poly, width):
    """i such that f_{t-1-i} is a term of the feedback."""
    return [i for i in range(width) if (poly >> (width - 1 - i)) & 1]


def tidy(line):
    if "#" not in line or line.lstrip().startswith("#"):
        return line.rstrip()
    code, comment = line.split("#", 1)
    return f"{code.rstrip():32}# {comment.strip()}"


def out(name, header, lines, tag):
    lines = [tidy(line) for line in lines]
    words = assemble("\n".join(lines) + "\n", CANDIDATES[tag])
    text = header.rstrip("\n").replace("{words}", str(len(words))).replace("{distinct}", str(len(set(words))))
    (HERE / f"{name}.asm").write_text(text + "\n\n" + "\n".join(lines) + "\n")
    print(f"{name}: {len(words)} words, {len(set(words))} distinct")


def parity(terms, p, done):
    """Pin 1 <- the parity of `terms`, each a function level -> the word that
    steps over the next when the term holds that level; pin 1 is 0 on entry.
    The even chain inline, a JMP across at every 1, the odd chain after it;
    the two meet at `done`."""
    n = len(terms)
    even, odd = [], []
    for j, term in enumerate(terms):
        last = j == n - 1
        if last:
            even += [f"{p}e{j}: {term(0)}  # even so far: 0? step over: even", "SET 1, 1  # odd", f"JMP {done}"]
            odd += [f"{p}o{j}: {term(1)}  # odd so far: 1? step over: even", "SET 1, 1  # odd"]
        else:
            even += [f"{p}e{j}: {term(0)}  # even so far: 0? step over: even still", f"JMP {p}o{j + 1}  # 1: odd"]
            if j > 0:  # the odd chain starts at o1: o0 is never entered
                odd += [f"{p}o{j}: {term(0)}  # odd so far: 0? step over: odd still", f"JMP {p}e{j + 1}  # 1: even"]
    return even + odd


def skip(index, side=""):
    return lambda level: f"SKIP {index}, {level}{side}"


def skip_pin(pin):
    return lambda level: f"SKIP_PIN {pin}, {level}"


def skip1(bit):
    return lambda level: f"SKIP1 {bit}, {level}"


# --- the tree forms ------------------------------------------------------------------------------


TREE_HEADER = """# CRC-{width} on candidate {tag}, {what}: four host bytes out on pin 0 MSB
# first and back through the pad; the register kept from its input end, the
# Fibonacci form (docs/crc-baselines.md), f = in ^ the feedback bits at the
# taps, {where}; the parity as two paths through SKIPs meeting on pin 1,
# cleared by the cell's first word, sampled back in as the new feedback bit.
# Then the CRC out on pin 1 MSB first, one bit per run of the `crc` body: the
# register's top bit is the feedback with a 0 in, the same tree, and a 0 fed
# back in its place shifts the register on without feedback; pin 3, held at
# 0, is both. The PULL between bytes breaks a body, so the four are written
# out. {{words}} words, {{distinct}} distinct. Written by gen.py.
"""


def tree_program(name, tag, poly, width, form):
    """form: "wide" (the input in the register at age 0, f_{t-1-i} at 2i + 1),
    "pin" (the input as SKIP_PIN 0, f_{t-1-i} at age i), "lanes" (the input
    in lane 0 at age 0, f_{t-1-i} at lane 1's bit i)."""
    ts = taps(poly, width)
    if form == "wide":
        window = [skip(2 * i + 1) for i in ts]
        data_in, zero_in = [skip(0)], [skip(0)]
        what, where = "the register carried on", f"f(t-1-i) at age 2i + 1, the input at age 0: {2 * width} bits of register"
    elif form == "pin":
        window = [skip(i) for i in ts]
        data_in, zero_in = [skip_pin(0)], []
        what, where = "the pad as a condition", f"f(t-1-i) at age i, the input read from the pad by SKIP_PIN, no slot: {width} bits of register"
    else:
        window = [skip1(i) for i in ts]
        data_in, zero_in = [skip(0)], [skip(0)]
        what, where = "two lanes", "the input into lane 0 at age 0, f(t-1-i) at lane 1's bit i: eight bits of each"
    lines = ["CONFIG shift_dir, 1  # MSB first: a sample enters at bit 0 and ages upward", "SET 3, 0  # pin 3: the 0 the emission feeds in"]
    for b in range(4):
        p = f"b{b}"
        lines += [f"PULL  # byte {b}"]
        if form == "pin":
            lines += [f"{p}: SHIFT_OUT 1, 0  # the data bit onto pin 0; pin 1 <- 0"]
        else:
            lines += [f"{p}: SHIFT_OUT 1, 0  # the data bit onto pin 0; pin 1 <- 0", "SHIFT_IN 0  # and back: the input, age 0"]
        lines += parity(data_in + window, p, f"{p}_f")
        feedback = "SHIFT_IN1 1" if form == "lanes" else "SHIFT_IN 1"
        lines += [f"{p}_f: {feedback}  # f into the window", f"REPEAT 8, {p}  # the byte's eight bits"]
    # the emission: a 0 in, the tree, the top bit on pin 1, a 0 back
    if form == "pin":
        # no input to shift: the tree's first word is the entry, and clears pin 1 if it can carry a side effect
        body = parity(window, "c", "c_f")
        index = ts[0]
        if index < 8:
            label, rest = body[0].split(": ", 1)
            word, comment = rest.split("#", 1)
            body[0] = f"crc: {word.rstrip()}, 1, 0  # pin 1 <- 0; {comment.strip()}"
        else:
            body = ["crc: SET 1, 0  # pin 1 <- 0"] + body
        lines += body
    else:
        lines += ["crc: SHIFT_IN 3, 1, 0  # a 0 in, age 0; pin 1 <- 0"] + parity(zero_in + window, "c", "c_f")
    lines += ["c_f: " + ("SHIFT_IN1 3" if form == "lanes" else "SHIFT_IN 3") + "  # a 0 back for the feedback: the register shifts on",
              f"REPEAT {width}, crc  # pin 1 holds the CRC's bit as the REPEAT issues; halted after the last"]
    out(name, TREE_HEADER.format(width=width, tag=tag, what=what, where=where), lines, tag)


# --- the accumulator -------------------------------------------------------------------------------


ACC_HEADER = """# CRC-15 on candidate Acc, the accumulator: the polynomial from the host,
# left-aligned, low byte first; four host bytes out on pin 0 MSB first and
# back through the pad into ACC_IN, the spec's register in the direct form;
# {tail} {{words}} words, {{distinct}} distinct. Written by gen.py.
"""


def acc_program(name, emit):
    lines = ["CONFIG shift_dir, 1  # MSB first", "PULL  # the polynomial's low byte", "ACC_LOAD",
             "PULL  # its high byte", "ACC_LOAD  # poly = 0x4599 << 1"]
    for b in range(4):
        lines += [f"PULL  # byte {b}", f"b{b}: SHIFT_OUT  # the data bit onto pin 0",
                  "ACC_IN 0  # and back into the accumulator: f = acc[15] ^ in", f"REPEAT 8, b{b}"]
    if emit:
        lines += ["crc: ACC_OUT 1  # the CRC's top bit onto pin 1, the accumulator shifted", "REPEAT 15, crc  # halted"]
        tail = "then the CRC out on pin 1 MSB first, ACC_OUT, one bit per run of the `crc` body."
    else:
        lines += ["ACC_PUSH  # {CRC[6:0], 0} to the host", "ACC_PUSH  # CRC[14:7]; halted"]
        tail = "then the CRC to the host in two bytes, low first, left-aligned."
    out(name, ACC_HEADER.format(tail=tail), lines, "Acc")


# --- the receivers -----------------------------------------------------------------------------------


RX_HEADER = """# The destuffing receiver with {what}: can_rx_bits_C.asm's cell, the raw
# history in in_shift_reg for the run test, {data}, a stuff bit into the raw
# history alone, and after every eight data bits {push} to the host: destuffed
# bytes at 8 clocks a bit. A body of eight cells with the push in the
# eighth, run five times, the SOF to bit 39; bits 40 and 41, the CRC's last
# two, written out with a push after; then the CRC delimiter, the ACK slot,
# the gap. For DLC 1, as the other receivers. {{words}} words, {{distinct}} distinct.
# Written by gen.py.
"""


def rx_cell(p, sample, gather, push, last_word, cycles_to_next):
    """One data bit: the sample (and the gather), the push if any, the run
    test both ways, the stuff bit on its seventh clock. The no-stuff path
    reaches `last_word`'s address on b(9 - cycles_to_next) so that the next
    cell's sample is at b9."""
    lines = [f"{p}: {sample}  # b1: the seventh clock, the level through the sixth"]
    used = 1
    for word in gather + push:
        used += 1
        lines += [f"{word}  # b{used}"]
    # after `used` cycles: SKIP_NORUN at b(used+1)
    a = used + 1
    to_stuff1 = 9 - (a + 1)  # the JMP after the first test issues at b(a+1) and the stuff sample is at b9
    to_stuff2 = 9 - (a + 2)
    to_next = 9 - (a + 2) - cycles_to_next
    lines += [f"SKIP_NORUN 5, 1  # b{a}: not five recessive? step over", f"JMP {p}s [{to_stuff1 - 1}]  # five recessive: the stuff bit at b9",
              f"SKIP_NORUN 5, 0  # b{a + 1}: not five dominant? step over", f"JMP {p}s [{to_stuff2 - 1}]  # five dominant",
              f"JMP {last_word} [{to_next - 1}]  # no run"]
    return lines, a


def rx_program(name, tag):
    if tag == "Lanes":
        sample, gather, push = "SHIFT_IN01 0", [], ["PUSH1"]
        what, data, pushw = "a second lane", "the data bit into both lanes by one sample, SHIFT_IN01", "lane 1"
        pre = []
    else:
        sample, gather, push = "SHIFT_IN 0", ["ACC_IN 0"], ["ACC_PUSH"]
        what, data, pushw = "the accumulator as a shift register", "the data bit into the accumulator a clock later, ACC_IN with the polynomial 1", "its low byte"
        pre = ["PULL  # the polynomial 0x0001, low byte first: the accumulator a plain shift register", "ACC_LOAD", "PULL", "ACC_LOAD"]
    lines = pre + ["CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening",
                   "CONFIG shift_dir, 1  # MSB first: a sample enters at bit 0",
                   "SHIFT_IN 0  # the idle bus, recessive: the register below the SOF holds a 1",
                   "WAIT 0, 0 [4]  # the SOF's edge, held through its fifth clock"]

    def cell(p, with_push, end):
        """A cell whose no-stuff path lands on `end`, `end` being the next
        cell's sample (8 cycles) or a word that takes one more cycle first."""
        c, a = rx_cell(p, sample, gather, push if with_push else [], end, 0 if end.startswith("c") else 1)
        return c + [f"{p}s: SHIFT_IN 0 [{7 if end.startswith('c') else 6}]  # the stuff bit into the raw history alone"]

    for k in range(8):
        last = k == 7
        nxt = "e" if last else f"c{k + 1}"
        lines += cell(f"c{k}", last, nxt)
    lines += ["e: REPEAT 5, c0  # b8, or b16 after a stuff bit: five bytes, the SOF to bit 39"]
    lines += cell("c40", False, "c41")
    c41, a = rx_cell("c41", sample, gather, push, "d", 0)
    lines += c41 + ["c41s: SHIFT_IN 0 [7]  # the stuff bit after the CRC's last, if any",
                    "d: SHIFT_IN 0 [1]  # the CRC delimiter, sampled; the slot's edge two clocks on",
                    "SET 0, 0 [7]  # the ACK slot: pulled dominant for the bit",
                    "SET 0, 1 [7]  # the ACK delimiter: let go",
                    "gap: NOP [6]  # EOF and the intermission", "REPEAT 10, gap  # halted"]
    out(name, RX_HEADER.format(what=what, data=data, push=pushw), lines, tag)


if __name__ == "__main__":
    tree_program("crc15_w32", "W32", POLY15, 15, "wide")
    tree_program("crc8_w16", "W16", POLY8, 8, "wide")
    tree_program("crc15_pin16", "Pin16", POLY15, 15, "pin")
    tree_program("crc8_pin8", "Pin8", POLY8, 8, "pin")
    tree_program("crc8_lanes", "Lanes", POLY8, 8, "lanes")
    acc_program("crc15_acc", True)
    acc_program("crc15_acc_bytes", False)
    rx_program("can_rx_bytes_lanes", "Lanes")
    rx_program("can_rx_bytes_acc", "Acc")
