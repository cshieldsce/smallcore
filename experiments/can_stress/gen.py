"""CAN stress programs: Protocol Engine v2 pushed wider, programs only.

    python experiments/can_stress/gen.py      # writes the .asm files below

Nothing in the ISA, the model or the RTL changes. Every program here is
generated from parameters, because the question is how far *programs* go:

  tx(dlc, n, loop)     stage 6A (experiments/combined/can_tx_combined.asm)
                       for any DLC and any bit time of n >= 8 clocks; with
                       `loop` it goes round after every frame, acked or not,
                       for back-to-back frames. n = 8, dlc = 1 is 6A word for
                       word.
  rx(bits, n, loop, idle, check)
                       stage 6C (can_rx_crc.asm) for a fixed stuffed-region
                       length and any bit time; with `loop` it goes round,
                       with `idle` it first waits for eleven recessive bits
                       (bus integration), with `check` it checks the CRC
                       delimiter and the stuff bits and answers with an
                       error flag.
  rx_dlc()             a receiver that follows the DLC it samples: a tree of
                       cells on the DLC bits into a chain of loops.
  arb_retry(ident)     stage 6B with a retry in the program after a loss.

Delays wider than a word holds (32 clocks) become NOPs; a SKIP-guarded JMP
whose hold is too long pads at its target instead, since the SKIP steps over
exactly one word.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT / "model")]

from cpu import assemble, decode, encode, load_isa, Instruction  # noqa: E402

MAXHOLD = 32  # the most clocks one word takes: 1 + a 5-bit delay


def hold(word, clocks, label=None):
    """`word` taking exactly `clocks` clocks: its own delay, then NOPs."""
    assert clocks >= 1, (word, clocks)
    first = min(clocks, MAXHOLD)
    lines = [f"{label + ': ' if label else ''}{word}" + (f" [{first - 1}]" if first > 1 else "")]
    clocks -= first
    while clocks:
        take = min(clocks, MAXHOLD)
        lines.append("NOP" + (f" [{take - 1}]" if take > 1 else ""))
        clocks -= take
    return lines


def pad(clocks, label=None):
    """NOPs taking `clocks` clocks, 0 allowed (then only a label, which needs a word: not allowed)."""
    if clocks == 0:
        assert label is None
        return []
    return hold("NOP", clocks, label)


def jump(target, clocks, label=None):
    """A JMP to `target` that arrives `clocks` clocks after it issues: NOPs first, the JMP last."""
    assert clocks >= 1
    lines = []
    while clocks > MAXHOLD:
        take = min(clocks - 1, MAXHOLD)
        lines.append("NOP" + (f" [{take - 1}]" if take > 1 else ""))
        clocks -= take
    lines.append(f"JMP {target}" + (f" [{clocks - 1}]" if clocks > 1 else ""))
    if label:
        lines[0] = f"{label}: {lines[0]}"
    return lines


def guarded(target, clocks):
    """A JMP right after a SKIP: one word. What it cannot hold, (word, extra), the target pads."""
    take = min(clocks, MAXHOLD)
    return f"JMP {target}" + (f" [{take - 1}]" if take > 1 else ""), clocks - take


def tx_sample(n):
    """The clock of a TX bit whose SHIFT_IN samples the bus: the 4th at n = 8 (6A's), else about 75%,
    leaving the four clocks the decision needs."""
    return 4 if n == 8 else min(max(4, round(0.75 * n)), n - 4)


def rx_sample(n):
    """The clock a receiver's SHIFT_IN issues on, counted from the SOF's first clock: 6C's is the 7th at n = 8."""
    return 7 if n == 8 else min(max(5, round(0.75 * n) + 1), n - 1)


# --- the transmitter ------------------------------------------------------------------------

DATA = ["SHIFT_OUT [1]", "ACC_CRC 0"]  # b1..b3: the bit onto the pad, the pad into the CRC on b3
PULLED = ["SHIFT_OUT", "PULL", "ACC_CRC 0"]  # the same with the next byte's PULL on b2
CRC = ["ACC_OUT 0 [2]"]  # a CRC bit from acc[15]


def tx_cell(p, before, nxt, last, n):
    """6A's checked bit at n clocks: `before` on b1..b3, the sample on clock s, the run test,
    the stuff bit on b(n + 1). The next cell follows the stuff code; `last` means the next word is a REPEAT."""
    s = tx_sample(n)
    a = s - 4  # clocks padded before the sample
    lines = [f"{p}: {before[0]}"] + before[1:] + pad(a)
    jd, xd = guarded(f"{p}d", n - 5 - a)  # issues on b(s + 2), arrives on b(n + 1)
    jr, xr = guarded(f"{p}r", n - 6 - a)  # issues on b(s + 3)
    lines += ["SHIFT_IN 0", "SKIP_NORUN 5, 1", jd, "SKIP_NORUN 5, 0", jr]
    lines += jump(nxt, n - 6 - a - (1 if last else 0))  # no run: the next cell on b(n + 1), or the REPEAT on b(n)
    # the stuff bits: pads the guarded JMPs could not hold, then the bit, sampled on its sth clock
    lines += (pad(xd, f"{p}d") + hold("SET 0, 0", 3 + a)) if xd else hold("SET 0, 0", 3 + a, f"{p}d")
    lines += hold("SHIFT_IN 0", n - 4 - a - (1 if last else 0)) + [f"JMP {nxt}"]
    lines += (pad(xr, f"{p}r") + hold("SET 0, 1", 3 + a)) if xr else hold("SET 0, 1", 3 + a, f"{p}r")
    lines += hold("SHIFT_IN 0", n - 3 - a - (1 if last else 0))  # falls into the next cell, or the REPEAT
    return lines


def tx(dlc=1, n=8, loop=False, ackflag=False):
    """6A for `dlc` data bytes at n clocks a bit. The host writes 0x32, 0x8B once, then 3 + dlc bytes a
    frame (test_can_combined.unopposed_bytes). Acked, it halts; with `loop` it always goes round. With
    `ackflag` (n = 8), a missing ACK is answered as CAN asks: an error flag, six dominant bits from the ACK
    delimiter, then eleven recessive bits waited out, 0xFF to the host (bit 0: not acked) and the frame
    again from the host's next bytes."""
    s = tx_sample(n)
    lines = ["CONFIG open_drain01, 1", "CONFIG shift_dir, 1", "PULL", "ACC_LOAD", "PULL", "ACC_LOAD",
             "frame: SHIFT_IN 0", "PULL",
             "lead: SHIFT_OUT [1]", "ACC_CRC 0"] + hold("SHIFT_IN 0", n - 4) + ["REPEAT 2, lead"]
    for k in range(8):
        lines += tx_cell(f"b{k}", PULLED if k == 0 else DATA, "end" if k == 7 else f"b{k + 1}", k == 7, n)
    lines += [f"end: REPEAT {2 + dlc}, b0"]
    lines += tx_cell("tail", DATA, "crc", False, n)
    lines += tx_cell("crc", CRC, "crc_end", True, n)
    lines += ["crc_end: REPEAT 15, crc"]
    lines += hold("SET 0, 1", n)  # the CRC delimiter
    if ackflag:
        assert n == 8
        lines += ["NOP [2]", "SHIFT_IN 0", "SKIP 0, 0 [3]", "JMP aerr"]  # the slot on clock 4; acked: the PUSH on clock 9
    else:
        lines += hold("NOP", s - 1) + hold("SHIFT_IN 0", n - s + 1)  # the ACK slot, sampled on clock s
    lines += hold("PUSH", n)  # the ACK delimiter: {the last seven samples, ACK} to the host
    lines += hold("NOP", n - 1, "gap") + ["REPEAT 10, gap"]  # EOF and the intermission
    if loop:
        lines += ["JMP frame"]
    else:
        lines += ["SKIP 0, 0", "JMP frame"]
    if ackflag:
        lines += hold("SET 0, 0", 6 * n, "aerr")  # the error flag, from the ACK delimiter's second clock
        lines += ["SET 0, 1"] + idle_wait("aidle") + ["PUSH", "JMP frame"]  # 0xFF: not acked
    return "\n".join(lines) + "\n"


# --- the receiver ---------------------------------------------------------------------------


def rx_cell(p, count, n, check=False):
    """6C's cell as a body run `count` times at n clocks a bit: the sample on b1, the CRC on b2, the PUSH on b3,
    the stuff bit sampled n clocks after, on b(n + 1). With `check`, a stuff bit equal to the run before it
    jumps to `err`, out of the body: the one JMP the assembler refuses, patched in afterwards (patched())."""
    long = n - 4 > MAXHOLD  # the guarded JMPs cannot hold: they land on pads before the stuff sample
    lines = [f"{p}: SHIFT_IN 0", "ACC_CRC 0", "PUSH", "SKIP_NORUN 5, 1", guarded(f"{p}s", n - 4)[0],
             "SKIP_NORUN 5, 0", guarded(f"{p}t" if long else f"{p}s", n - 5)[0]]
    lines += jump(f"{p}e", n - 6)  # no run: the REPEAT on b(n)
    stuff = []
    if long:
        extra = n - 5 - MAXHOLD  # what the second JMP could not hold; the first one more
        stuff += [f"{p}s: NOP"] + (pad(extra, f"{p}t") if extra else [])
    if check:
        stuff += ["SHIFT_IN 0", "SKIP_NORUN 2, 0", f"JMP {p}e  # PATCH err", "SKIP_NORUN 2, 1", f"JMP {p}e  # PATCH err"]
        stuff += pad(n - 4)
    else:
        stuff += hold("SHIFT_IN 0", n - 1)
    if not long:
        stuff[0] = f"{p}s: {stuff[0]}"
    elif not (n - 5 - MAXHOLD):
        stuff[1] = f"{p}t: {stuff[1]}"
    return lines + stuff + [f"{p}e: REPEAT {count}, {p}"]


def rx_cells(p, total, n, check=False):
    """`total` checked bits as bodies of at most 32 runs."""
    lines, k = [], 0
    while total:
        runs = min(total, 32)
        lines += rx_cell(f"{p}{k}", runs, n, check)
        total -= runs
        k += 1
    return lines


def idle_wait(label):
    """Wait for the bus to be idle: eleven recessive samples in a row, one every 8 clocks, so no dominant bit
    of eight clocks slips between two. The run test takes eight at once; three more one at a time. 12 words."""
    return [f"{label}: SHIFT_IN 0 [5]", "SKIP_RUN 8, 1", f"JMP {label}",  # the newest eight recessive
            "SHIFT_IN 0 [6]", "SKIP 0, 1", f"JMP {label}",  # a ninth
            "SHIFT_IN 0 [6]", "SKIP 0, 1", f"JMP {label}",  # a tenth
            "SHIFT_IN 0 [6]", "SKIP 0, 1", f"JMP {label}"]  # an eleventh: the bus is idle


def rx(bits=42, n=8, loop=False, idle=False, check=False, drain=True):
    """6C for a stuffed region of `bits` data bits (34 + 8 DLC), n clocks a bit. The host writes 0x32, 0x8B
    and pops `bits` + 2 bytes a frame. With `loop`, it goes round for the next frame; with `idle`, it first
    waits for the bus to be idle, eleven recessive samples a bit apart; with `check`, a stuff error or a
    dominant CRC delimiter sends an error flag, six dominant bits, hands the host 0x00 (eight dominant raw
    samples, which no frame's PUSH can show: stuffing allows five), drains rc, clears acc and waits for the
    bus to be idle. `drain` False leaves rc as the early exit left it: the failure the assembler's rule is for."""
    idle = idle or check
    s = rx_sample(n)
    lines = ["CONFIG open_drain01, 1", "CONFIG shift_dir, 1", "PULL", "ACC_LOAD", "PULL", "ACC_LOAD"]
    if idle:
        assert n == 8
        lines += idle_wait("listen") + ["sof: SHIFT_IN 0"]
    else:
        lines += ["listen: SHIFT_IN 0"]
    lines += hold("WAIT 0, 0", s - 2)  # the SOF's first clock, held: the first SHIFT_IN on clock s
    lines += rx_cells("c", bits, n, check)
    if check:
        lines += ["SHIFT_IN 0", "SKIP 0, 1", "JMP err"]  # the CRC delimiter must be recessive: a form error
        lines += hold("SET 0, 0", n)  # the ACK slot, from the delimiter's clock s + 2
    else:
        lines += hold("SHIFT_IN 0", 2)
        lines += hold("SET 0, 0", n)
    lines += hold("SET 0, 1", n)  # the ACK delimiter
    again = loop or check  # back to the SOF's WAIT by the third bit of the intermission, where a SOF may come
    lines += hold("NOP", n - 1, "gap") + [f"REPEAT {9 if again else 10}, gap"]
    lines += ["ACC_PUSH", "ACC_PUSH"]  # the residue, 0 and 0 when the CRC matched; acc clear
    if again:
        lines += ["JMP sof" if idle else "JMP listen"]
    if check:
        # the error flag: six dominant bits from the next bit, then let go and drain rc (the body left early),
        # then wait for the bus to be idle; acc cleared by shifting it out on a spare pin, no host bytes
        assert n == 8
        lines += ["err: SET 0, 0", "SHIFT_IN 0 [4]"] + ["SHIFT_IN 0 [5]"] * 7  # six bits, eight dominant samples
        lines += ["SET 0, 1", "PUSH"]  # let go; 0x00 to the host: this frame is void
        lines += ["drain: NOP", "REPEAT 1, drain"] if drain else []  # rc back to 0 whatever the exit left
        lines += ["clr: ACC_OUT 3", "REPEAT 16, clr", "JMP listen"]
    return "\n".join(lines) + "\n"


def patched(source, isa=None):
    """Assemble `source`, then point every JMP marked `# PATCH err` at the label `err`: a JMP out of a
    REPEAT body, which the assembler refuses and the hardware does, leaving rc as it stood."""
    isa = isa or load_isa()
    marked = [line for line in source.splitlines() if "# PATCH err" in line]
    words = assemble(source, isa)
    # addresses: re-walk the source the way the assembler does
    labels, addr, marks = {}, 0, []
    for line in source.splitlines():
        code = line.split("#", 1)[0].strip()
        if not code:
            continue
        if ":" in code.split()[0]:
            label, _, rest = code.partition(":")
            labels[label.strip()] = addr
            code = rest.strip()
        if code:
            if "# PATCH err" in line:
                marks.append(addr)
            addr += 1
    assert len(marks) == len(marked) and addr == len(words)
    for at in marks:
        old = decode(words[at], isa)
        words[at] = encode(Instruction("JMP", (labels["err"],), old.delay, None), isa)
    return words


# --- the receiver that follows the DLC ------------------------------------------------------


def tree_cell(p, zero, one):
    """A checked bit at 8 clocks whose continuation depends on its value: the cell of 6C, then SKIP 0, 1 on
    the newest sample; a stuff bit after it says the value by the run's level. Not a body: straight line."""
    return [f"{p}: SHIFT_IN 0", "ACC_CRC 0", "PUSH",
            "SKIP_NORUN 5, 1", f"JMP {p}r [3]",  # five recessive: this bit was 1, a stuff bit follows
            "SKIP_NORUN 5, 0", f"JMP {p}d [2]",  # five dominant: 0
            "SKIP 0, 1", f"JMP {zero} [1]", f"JMP {one} [1]",
            f"{p}r: SHIFT_IN 0 [6]", f"JMP {one}",
            f"{p}d: SHIFT_IN 0 [6]", f"JMP {zero}"]


def rx_dlc(loop=False):
    """A receiver for any DLC, base format data frames: SOF..r0 as one body (15 bits), the DLC's four bits a
    tree (DLC3 = 1 is eight bytes, the rest three levels deep), then a chain of loops, eight data bytes of
    eight bits each and the CRC's fifteen, entered where 8 DLC + 15 bits are left."""
    lines = ["CONFIG open_drain01, 1", "CONFIG shift_dir, 1", "PULL", "ACC_LOAD", "PULL", "ACC_LOAD",
             "listen: SHIFT_IN 0", "WAIT 0, 0 [4]"]
    lines += rx_cell("h", 15, 8)
    lines += tree_cell("t3", "t2", "big")  # DLC3
    lines += tree_cell("t2", "t1a", "t1b")  # DLC2
    lines += tree_cell("t1a", "t0a", "t0b") + tree_cell("t1b", "t0c", "t0d")  # DLC1
    for leaf, (lo, hi) in zip("abcd", ((0, 1), (2, 3), (4, 5), (6, 7))):
        lines += tree_cell(f"t0{leaf}", f"L{lo}", f"L{hi}")  # DLC0: the chain entry for that many bytes
    lines += rx_cell("big", 3, 8)  # DLC3 = 1: three more DLC bits, eight bytes whatever they say; falls into L8
    for k in range(8, 0, -1):
        lines += rx_cell(f"L{k}", 8, 8)  # data byte 9 - k: entered with k bytes left
    lines += rx_cell("L0", 15, 8)  # the CRC
    lines += ["SHIFT_IN 0 [1]", "SET 0, 0 [7]", "SET 0, 1 [7]", "gap: NOP [6]", f"REPEAT {9 if loop else 10}, gap",
              "ACC_PUSH", "ACC_PUSH"]
    if loop:
        lines += ["JMP listen"]
    return "\n".join(lines) + "\n"


def rx_dlc_rtr():
    """rx_dlc with remote frames: SOF..ID[0] as a body, a tree cell on RTR, IDE and r0 as a body, the DLC
    tree and chain; RTR = 1 takes a body of 21 bits (IDE, r0, the DLC, the CRC) to the fixed form. Over 256
    words: the assembler refuses it, which is the measurement."""
    lines = ["CONFIG open_drain01, 1", "CONFIG shift_dir, 1", "PULL", "ACC_LOAD", "PULL", "ACC_LOAD",
             "listen: SHIFT_IN 0", "WAIT 0, 0 [4]"]
    lines += rx_cell("h", 12, 8)
    lines += tree_cell("rtr", "ir", "rem")
    lines += rx_cell("ir", 2, 8)
    lines += tree_cell("t3", "t2", "big") + tree_cell("t2", "t1a", "t1b")
    lines += tree_cell("t1a", "t0a", "t0b") + tree_cell("t1b", "t0c", "t0d")
    for leaf, (lo, hi) in zip("abcd", ((0, 1), (2, 3), (4, 5), (6, 7))):
        lines += tree_cell(f"t0{leaf}", f"L{lo}", f"L{hi}")
    lines += rx_cell("rem", 21, 8) + ["JMP fix"]
    lines += rx_cell("big", 3, 8)
    for k in range(8, 0, -1):
        lines += rx_cell(f"L{k}", 8, 8)
    lines += rx_cell("L0", 15, 8)
    lines += ["fix: SHIFT_IN 0 [1]", "SET 0, 0 [7]", "SET 0, 1 [7]", "gap: NOP [6]", "REPEAT 10, gap", "ACC_PUSH", "ACC_PUSH"]
    return "\n".join(lines) + "\n"


# --- arbitration with a retry in the program ------------------------------------------------


_combined = []


def combined():
    """experiments/combined/gen.py, loaded once: 6B's generator."""
    if not _combined:
        import importlib.util
        spec = importlib.util.spec_from_file_location("combined_gen", ROOT / "experiments" / "combined" / "gen.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _combined.append(module)
    return _combined[0]


def arb_retry(ident, dlc=1):
    """6B for `ident` with the loss handled in the program: let go, hand the host one byte (the samples to
    the dominant bit), clear acc by shifting it out on a spare pin, wait for eleven recessive bits and
    arbitrate again. The data byte PULLed before the SOF is still in shift_reg: the header is SETs, so the
    host queues nothing again."""
    source = combined().tx_arbitration(ident, dlc, write=False)
    body = [line for line in source.splitlines() if line and not line.startswith("#")]
    at = next(i for i, line in enumerate(body) if line.startswith("PULL") and "d0[7]" in line)
    body.insert(at + 1, "retry: NOP")  # the header starts here, shift_reg holding {d0[7], 0000000}
    cut = next(i for i, line in enumerate(body) if line.startswith("lost:"))
    body = body[:cut] + ["lost: PUSH", "clr: ACC_OUT 3", "REPEAT 16, clr"] + idle_wait("listen") + ["JMP retry", "done: NOP"]
    return "\n".join(body) + "\n"


def write(name, source, header):
    """experiments/can_stress/<name>.asm: the header, the size (or the assembler's refusal), the source.
    A source with `# PATCH err` JMPs assembles as written and is patched by patched() before it runs."""
    text = "\n".join(f"# {line}" if line else "#" for line in header.strip().splitlines())
    try:
        words = assemble(source) if "# PATCH" not in source else patched(source)
        size = f"# {len(words)} words, {len(set(words))} distinct."
    except SyntaxError as e:
        words, size = None, f"# REFUSED by the assembler ({e}): kept as the measurement."
    (HERE / f"{name}.asm").write_text(f"{text}\n{size}\n\n{source}")
    print(f"{name}: {size[2:]}")
    return words


if __name__ == "__main__":
    write("can_tx_dlc8", tx(8), "6A for DLC 8: the one word that differs from DLC 1 is the body's REPEAT count.")
    write("can_tx_loop", tx(1, loop=True), "6A going round after every frame, acked or not: back-to-back frames,\n"
          "the host reads the ACK byte after each.")
    write("can_rx_loop_idle", rx(42, loop=True, idle=True), "6C for DLC 1 going round, waiting for the bus to be idle\n"
          "(eleven recessive samples) before it syncs on a SOF.")
    write("can_rx_dlc", rx_dlc(), "A receiver that follows the DLC it samples: a tree on the DLC bits into a\n"
          "chain of loops, eight bytes and the CRC.")
    write("can_rx_check", rx(42, check=True), "6C with a stuff check and a CRC delimiter check that answer with an\n"
          "error flag: the JMPs out of the bodies are patched in, the assembler refuses them. rc is drained after.")
    write("can_tx_arb_retry_5a3", arb_retry(0x5A3), "6B for 0x5A3 with the retry in the program after a loss.")
    write("can_tx_n25", tx(1, n=25), "6A at 25 clocks a bit: 1 Mbit/s at 25 MHz.")
    write("can_rx_n25", rx(42, n=25), "6C at 25 clocks a bit: 1 Mbit/s at 25 MHz.")
    write("can_tx_ackflag", tx(1, loop=True, ackflag=True), "6A going round, a missing ACK answered with an error flag.")
    write("can_rx_check_nodrain", rx(42, check=True, drain=False), "can_rx_check without the rc drain: kept as\n"
          "the failure that shows why the assembler forbids a JMP out of a body: a late stuff error leaves rc\n"
          "below 16 and the clear loop no longer clears acc.")
    write("can_rx_dlc_rtr", rx_dlc_rtr(), "can_rx_dlc with remote frames (a tree cell on RTR, a 21-bit path to\n"
          "the fixed form): 272 lines, past 256 words. The failed attempt, kept.")
