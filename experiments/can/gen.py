"""Write the spliced CAN programs, one per candidate, into experiments/can/.

    python experiments/can/gen.py

Arbitration: can_tx_arb.asm, 95 words, with the candidate's words in place
of the two-sample SKIP/JMP decision, at 8 cycles a bit, the bus held to the
baseline's. Stuffing: can_tx_stuff.asm, 224 words, with the candidate's
decision after every checked bit, at the shortest bit in which the decision
fits with the sample point at 50% or later (the baseline's), and a second
form with each run of checked bits a REPEAT body. Every cell's cycles are
counted in the comments; tests/model/test_can_candidates.py holds each program to
the baseline's bits on the bus.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent / "model")]

from candidates import CANDIDATES, Candidate, assemble  # noqa: E402

ID_CELLS = [f"id{i}" for i in range(10, -1, -1)]  # ID[10] down to ID[0]


def exit_of(n):
    """A loss before ID[4]'s PULL leaves the second byte queued: lost1 takes it."""
    return "lost1" if ID_CELLS.index(n) < ID_CELLS.index("id4") else "lost"
CHECKED = [f"id{i}" for i in range(7, -1, -1)]  # the bits a run of five can end on


def tidy(line):
    """Code padded to column 32, then the comment, as the baselines are written."""
    if "#" not in line or line.lstrip().startswith("#"):
        return line.rstrip()
    code, comment = line.split("#", 1)
    return f"{code.rstrip():32}# {comment.strip()}"


def out(name, header, lines, cls):
    lines = [tidy(line) for line in lines]
    words = assemble("\n".join(lines) + "\n", cls)
    text = header.rstrip("\n").replace("{words}", str(len(words))).replace("{distinct}", str(len(set(words))))
    (HERE / f"{name}.asm").write_text(text + "\n\n" + "\n".join(lines) + "\n")
    print(f"{name}: {len(words)} words, {len(set(words))} distinct")


# --- arbitration -----------------------------------------------------------------------------

ARB_HEADER = """# can_tx_arb.asm with {what}: the SOF and the 11-bit identifier under
# arbitration, 8 cycles a bit, {view}. {decision}
# The exits are the baseline's: lost1 takes the stranded second byte, lost
# lets go and hands the host {byte}. {words} words, {distinct} distinct.
"""

ARB = {
    "A": dict(
        what="BRANCH", view="the transceiver's view: TXD on pin 0, its readback on gpio_in 0, the bus on gpio_in 1",
        decision="Per bit: TXD driven on the first cycle, the sent bit sampled on the second, the bus on the sixth (the level\n"
                 "# through the fifth, 62.5%), then BRANCH sent dominant -> a pad, BRANCH seen recessive -> the next bit, else\n"
                 "# JMP lost: two cycles on every path that goes on, the pad's NOP making the first as long as the second.",
        byte="the last four (sent, seen) pairs, a loss (1, 0) last",
        config="CONFIG open_drain01, 2  # RXD, pin 1, is a pad we listen on: open-drain, its reset 1 lets go; TXD, pin 0, stays push-pull",
        cell=lambda n, nxt, pad, pull: [
            f"{n}:{' ' * (7 - len(n))}SHIFT_OUT               # {n.upper()}: TXD = the bit",
            "        SHIFT_IN 0 [3]          #        the bit as sent, TXD read back" if not pull else "        SHIFT_IN 0 [2]          #        the bit as sent, TXD read back, and",
            *(["        PULL                    #        {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
            "        SHIFT_IN 1              #        the bus, the sixth cycle",
            f"        BRANCH 1, 0, {pad}{' ' * (9 - len(pad))}#        sent dominant: nothing to lose, the pad then the next bit",
            f"        BRANCH 0, 1, {nxt}{' ' * (9 - len(nxt))}#        saw recessive: still in",
            f"        JMP {exit_of(n)}{' ' * (12 if exit_of(n) == 'lost1' else 13)}#        sent recessive, saw dominant: lost",
        ],
        pad=lambda n, nxt: [f"{n}:{' ' * (7 - len(n))}NOP" if nxt != "lost" else f"{n}:{' ' * (7 - len(n))}JMP lost"],
    ),
    "B": dict(
        what="SHIFT_SENT", view="the pad on the bus, one pin",
        decision="Per bit: the bit driven on the first cycle, its register sampled on the second by SHIFT_SENT, the bus on\n"
                 "# the fifth, then the baseline's SKIP, JMP, SKIP, JMP, three cycles on every path; the words are the\n"
                 "# baseline's with SHIFT_SENT 0 for SHIFT_IN 0 and SHIFT_IN 0 for SHIFT_IN 1.",
        byte="the last four (sent, seen) pairs, a loss (1, 0) last",
        config="CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive",
        cell=lambda n, nxt, pad, pull: [
            f"{n}:{' ' * (7 - len(n))}SHIFT_OUT               # {n.upper()}: the bit, a 0 pulls the bus dominant, a 1 lets go",
            "        SHIFT_SENT 0 [2]        #        the bit as sent: the register behind the pad" if not pull else "        SHIFT_SENT 0 [1]        #        the bit as sent: the register behind the pad, and",
            *(["        PULL                    #        {ID[3:0], 0000} in the fourth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
            "        SHIFT_IN 0              #        the bus, the fifth cycle",
            "        SKIP 1, 1               #        sent recessive? step over the JMP",
            f"        JMP {nxt} [1]{' ' * (12 - len(nxt))}#        sent dominant: nothing to lose",
            "        SKIP 0, 0               #        saw dominant? step over the JMP",
            f"        JMP {nxt}{' ' * (16 - len(nxt))}#        saw recessive: still in",
            f"        JMP {exit_of(n)}{' ' * (12 if exit_of(n) == 'lost1' else 13)}#        sent recessive, saw dominant: lost",
        ],
        pad=None,
    ),
    "Bc": dict(
        what="SKIP_SENT", view="the pad on the bus, one pin",
        decision="Per bit: the bit driven on the first cycle, the bus sampled on the fifth, then SKIP_SENT on the register\n"
                 "# behind the pad, JMP, SKIP on the sample, JMP: the baseline's decision without its first sample.",
        byte="the last eight bus samples, in which a loss does not show",
        config="CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive",
        cell=lambda n, nxt, pad, pull: [
            f"{n}:{' ' * (7 - len(n))}SHIFT_OUT [3]           # {n.upper()}: the bit, a 0 pulls the bus dominant, a 1 lets go" if not pull else f"{n}:{' ' * (7 - len(n))}SHIFT_OUT [2]           # {n.upper()}: the bit, and",
            *(["        PULL                    #        {ID[3:0], 0000} in the fourth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
            "        SHIFT_IN 0              #        the bus, the fifth cycle",
            "        SKIP_SENT 0, 1          #        sent recessive? step over the JMP",
            f"        JMP {nxt} [1]{' ' * (12 - len(nxt))}#        sent dominant: nothing to lose",
            "        SKIP 0, 0               #        saw dominant? step over the JMP",
            f"        JMP {nxt}{' ' * (16 - len(nxt))}#        saw recessive: still in",
            f"        JMP {exit_of(n)}{' ' * (12 if exit_of(n) == 'lost1' else 13)}#        sent recessive, saw dominant: lost",
        ],
        pad=None,
    ),
    "AB": dict(
        what="BRANCH and SHIFT_SENT", view="the pad on the bus, one pin",
        decision="Per bit: the bit driven on the first cycle, its register sampled on the second by SHIFT_SENT, the bus on\n"
                 "# the sixth (the level through the fifth, 62.5%), then BRANCH sent dominant -> a pad, BRANCH seen recessive\n"
                 "# -> the next bit, else JMP lost: two cycles on every path that goes on.",
        byte="the last four (sent, seen) pairs, a loss (1, 0) last",
        config="CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive",
        cell=lambda n, nxt, pad, pull: [
            f"{n}:{' ' * (7 - len(n))}SHIFT_OUT               # {n.upper()}: the bit, a 0 pulls the bus dominant, a 1 lets go",
            "        SHIFT_SENT 0 [3]        #        the bit as sent: the register behind the pad" if not pull else "        SHIFT_SENT 0 [2]        #        the bit as sent: the register behind the pad, and",
            *(["        PULL                    #        {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
            "        SHIFT_IN 0              #        the bus, the sixth cycle",
            f"        BRANCH 1, 0, {pad}{' ' * (9 - len(pad))}#        sent dominant: nothing to lose, the pad then the next bit",
            f"        BRANCH 0, 1, {nxt}{' ' * (9 - len(nxt))}#        saw recessive: still in",
            f"        JMP {exit_of(n)}{' ' * (12 if exit_of(n) == 'lost1' else 13)}#        sent recessive, saw dominant: lost",
        ],
        pad=lambda n, nxt: [f"{n}:{' ' * (7 - len(n))}NOP" if nxt != "lost" else f"{n}:{' ' * (7 - len(n))}JMP lost"],
    ),
    "ABc": dict(
        what="BRANCH and BRANCH_SENT", view="the pad on the bus, one pin",
        decision="Per bit: the bit driven on the first cycle, the bus sampled on the sixth (the level through the fifth,\n"
                 "# 62.5%), then BRANCH_SENT on the register behind the pad, dominant -> a pad, BRANCH seen recessive -> the\n"
                 "# next bit, else JMP lost: two cycles on every path that goes on, one sample a bit.",
        byte="the last eight bus samples, in which a loss does not show",
        config="CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive",
        cell=lambda n, nxt, pad, pull: [
            f"{n}:{' ' * (7 - len(n))}SHIFT_OUT [4]           # {n.upper()}: the bit, a 0 pulls the bus dominant, a 1 lets go" if not pull else f"{n}:{' ' * (7 - len(n))}SHIFT_OUT [3]           # {n.upper()}: the bit, and",
            *(["        PULL                    #        {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
            "        SHIFT_IN 0              #        the bus, the sixth cycle",
            f"        BRANCH_SENT 0, 0, {pad}{' ' * (4 - len(pad))}#        sent dominant: nothing to lose, the pad then the next bit",
            f"        BRANCH 0, 1, {nxt}{' ' * (9 - len(nxt))}#        saw recessive: still in",
            f"        JMP {exit_of(n)}{' ' * (12 if exit_of(n) == 'lost1' else 13)}#        sent recessive, saw dominant: lost",
        ],
        pad=None if False else (lambda n, nxt: [f"{n}:{' ' * (7 - len(n))}NOP" if nxt != "lost" else f"{n}:{' ' * (7 - len(n))}JMP lost"]),
    ),
}


def arbitration(tag):
    spec = ARB[tag]
    lines = [
        f"        {spec['config']}",
        "        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]",
        "        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)",
        "        SHIFT_OUT [7]           # SOF: dominant, every node's; nothing to decide",
        "",
    ]
    for i, n in enumerate(ID_CELLS):
        nxt = ID_CELLS[i + 1] if i + 1 < len(ID_CELLS) else "lost"
        pad = f"p{n[2:]}"
        lines += spec["cell"](n, nxt, pad, pull=(n == "id4"))
        if spec["pad"]:
            lines += spec["pad"](pad, nxt)
    lines += [
        "lost1:  PULL                    # lost before ID[4]'s PULL: {ID[3:0], 0000} is still queued; take it and drop it",
        "lost:   PUSH 0, 1               # let go, as a loss already has; the byte to the host",
    ]
    header = wrap(ARB_HEADER.format(what=spec["what"], view=spec["view"], decision=spec["decision"], byte=spec["byte"],
                                    words="{words}", distinct="{distinct}").replace("# ", " ").replace("#", " "))
    out(f"can_tx_arb_{tag}", header, lines, CANDIDATES[tag])


# --- stuffing ---------------------------------------------------------------------------------
#
# A cell is one checked bit: SHIFT_OUT [k] drives it on its first cycle and holds it, SHIFT_IN 0
# samples it on clock k + 2 (the level the bus held through k + 1), the decision runs in the
# cycles after, and the next bit's first word runs on clock L + 1. `unrolled` gives the cell
# with `nxt` the next cell's label; `looped` gives the body of a REPEAT with `end` the REPEAT,
# whose cycle and the JMP over the stuff code, where one is needed, are paid for by sampling
# earlier. A stuff bit is a SET of the other level held L cycles and sampled like any bit, so
# the next window counts it. The four bits before ID[7] cannot end a run of five.

STUFF_HEADER = """# can_tx_stuff.asm with {what}: the SOF and the 11-bit identifier with dynamic
# bit stuffing, the pad on the bus, {bit} cycles a bit, driven on the first and
# sampled on the {sample}{ordinal} (the level through the {before}{ordinal2}, {pct}). {decision}
# {form} The host writes {SOF 0, ID[10:4]} and {ID[3:0], 0000} as for can_tx.asm
# and reads the last eight samples, stuff bits among them. {words} words, {distinct} distinct.
"""


def ordinal(n):
    return {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")


def wrap(text, width=78):
    """A header paragraph as comment lines."""
    import textwrap

    return "\n".join("# " + line for line in textwrap.wrap(" ".join(text.split()), width - 2))


def stuff_program(tag, cls, L, k, cell, blocks, what, decision, loop):
    """The program around the cells: k is the SHIFT_OUT's hold for the sample point the
    checked cells use; `cell(n, nxt, pull)` the unrolled cell, or with `loop` the body
    `cell(n, "end", pull)` that ends at the REPEAT; `blocks(n, nxt)` the out-of-line words
    of a cell, if any, put after the exit."""
    S = k + 2
    head = STUFF_HEADER.replace("{what}", what).replace("{bit}", str(L)).replace("{sample}", str(S)).replace("{ordinal}", ordinal(S))
    head = head.replace("{before}", str(S - 1)).replace("{ordinal2}", ordinal(S - 1)).replace("{pct}", f"{100 * (S - 1) / L:g}%")
    head = head.replace("{decision}", decision)
    lines = [
        "        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive",
        "        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]",
        "        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)",
        f"first:  SHIFT_OUT [{k}]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held {k + 1}",
        f"        SHIFT_IN 0 [{L - k - 3}]{' ' * (10 - len(str(L - k - 3)))}# sampled on the {S}{ordinal(S)}, held {L - k - 2}, and",
        "        REPEAT 4, first         # the last cycle: no run of five can end here",
    ]
    tail = []
    if not loop:
        for i, n in enumerate(CHECKED):
            nxt = CHECKED[i + 1] if i + 1 < len(CHECKED) else "done"
            lines += cell(n, nxt, n == "id4")
            tail += blocks(n, nxt)
        form = "Every checked bit written out, ID[7] to ID[0]: a run of five cannot end before ID[7]."
        if tail:
            form += " The stuff code sits after the exit, which jumps past the end to halt, since only a branch enters it."
    else:
        # ID[7], ID[6], ID[5] a body run three times; ID[4] with the PULL written out, the unrolled cell; ID[3] to ID[0] a body run four times.
        lines += cell("id7", "end1", False) + ["end1:   REPEAT 3, id7           # ID[7], ID[6], ID[5]"]
        lines += UNROLLED[tag][2]("id4", "id3", True)
        tail += UNROLLED[tag][3]("id4", "id3")
        lines += cell("id3", "end2", False) + ["end2:   REPEAT 4, id3           # ID[3] down to ID[0]"]
        form = ("ID[7], ID[6], ID[5] one REPEAT body, ID[3] to ID[0] another, ID[4] with its PULL written out between them "
                "in the unrolled cell's shape; the REPEAT's cycle" + (" and the JMP over the stuff code are" if tag in ("C", "AC", "D", "AD", "base") else " is")
                + " paid for by sampling earlier.")
    lines.append("done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them")
    if tail:
        lines += ["        JMP halt                # past the end: halted; the stuff code below is entered by branch only", *tail, "halt:"]
    head = wrap(head.replace("{form}", form).replace("# ", " ").replace("#", " "))
    name = "can_tx_stuff_loop" if tag == "base" else f"can_tx_stuff_{tag}" + ("_loop" if loop else "")
    out(name, head, lines, cls)


def lab(n):
    return f"{n}:{' ' * (7 - len(n))}"


# -- today's ISA, the baseline's cell as a REPEAT body: the correction ---------------------------

def base_loop_cell(n, end, pull):
    assert not pull
    z = n + "z"
    return [
        f"{lab(n)}SHIFT_OUT [6]           # {n.upper()}: driven, held seven",
        "        SHIFT_IN 0              # sampled on the eighth",
        "        SKIP 0, 1               # recessive? step over the JMP: the recessive tree",
        f"        JMP {z}{' ' * (17 - len(z))}# dominant: the dominant tree",
        "        SKIP 1, 1               # the bit before recessive too? step over the JMP",
        f"        JMP {end} [4]           # no run: the REPEAT on the sixteenth cycle",
        "        SKIP 2, 1",
        f"        JMP {end} [3]",
        "        SKIP 3, 1",
        f"        JMP {end} [2]",
        "        SKIP 4, 1",
        f"        JMP {end} [1]",
        "        NOP [2]                 # five recessive: a dominant stuff bit follows on the seventeenth",
        "        SET 0, 0 [7]            # the stuff bit, dominant, driven, held eight",
        "        SHIFT_IN 0 [5]          # sampled on its eighth like every bit, held six, and",
        f"        JMP {end}{' ' * (16 - len(end))}# the REPEAT: the next bit",
        f"{lab(z)}SKIP 1, 0               # the dominant tree: the bit before dominant too? step over the JMP",
        f"        JMP {end} [3]",
        "        SKIP 2, 0",
        f"        JMP {end} [2]",
        "        SKIP 3, 0",
        f"        JMP {end} [1]",
        "        SKIP 4, 0",
        f"        JMP {end}",
        "        NOP [1]                 # five dominant: a recessive stuff bit follows",
        "        SET 0, 1 [7]            # the stuff bit, recessive, let go, held eight",
        "        SHIFT_IN 0 [6]          # sampled on its eighth, held seven: the REPEAT follows",
    ]


def base_cell(n, nxt, pull):
    """The baseline's cell, can_tx_stuff.asm's, for ID[4] in the loop form."""
    z = n + "z"
    return [
        f"{lab(n)}SHIFT_OUT [{6 if pull else 7}]           # {n.upper()}: driven, held {'seven, and' if pull else 'eight'}",
        *(["        PULL                    # {ID[3:0], 0000} in the eighth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
        "        SHIFT_IN 0              # sampled on the ninth",
        "        SKIP 0, 1               # recessive? step over the JMP",
        f"        JMP {z}{' ' * (17 - len(z))}# dominant: the dominant tree",
        "        SKIP 1, 1",
        f"        JMP {nxt} [4]",
        "        SKIP 2, 1",
        f"        JMP {nxt} [3]",
        "        SKIP 3, 1",
        f"        JMP {nxt} [2]",
        "        SKIP 4, 1",
        f"        JMP {nxt} [1]",
        "        NOP [1]",
        "        SET 0, 0 [7]",
        "        SHIFT_IN 0 [6]",
        f"        JMP {nxt}",
        f"{lab(z)}SKIP 1, 0",
        f"        JMP {nxt} [3]",
        "        SKIP 2, 0",
        f"        JMP {nxt} [2]",
        "        SKIP 3, 0",
        f"        JMP {nxt} [1]",
        "        SKIP 4, 0",
        f"        JMP {nxt}",
        "        NOP",
        "        SET 0, 1 [7]",
        "        SHIFT_IN 0 [7]",
    ]


# -- A: BRANCH trees and a ladder of NOPs, 12 cycles a bit ------------------------------------

def a_cell(n, nxt, pull):
    z, l2, l3, l4 = n + "z", n + "l2", n + "l3", n + "l4"
    return [
        f"{lab(n)}SHIFT_OUT [{4 if pull else 5}]           # {n.upper()}: driven, held {'five, and' if pull else 'six'}",
        *(["        PULL                    # {ID[3:0], 0000} in the sixth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
        "        SHIFT_IN 0              # sampled on the seventh",
        f"        BRANCH 0, 1, {z}{' ' * (10 - len(z))}# recessive: the recessive tree, cycle 8",
        f"        BRANCH 1, 1, {l2}{' ' * (10 - len(l2))}# dominant: the bit before recessive? no run, three rungs of the ladder",
        f"        BRANCH 2, 1, {l3}",
        f"        BRANCH 3, 1, {l4}",
        f"        BRANCH 4, 1, {nxt}{' ' * (10 - len(nxt))}# the bit before that recessive? no run, the last rung is the next bit",
        "        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth",
        "        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and",
        f"        JMP {nxt}{' ' * (16 - len(nxt))}# the twelfth: the next bit",
        f"{lab(z)}BRANCH 1, 0, {l2}{' ' * (10 - len(l2))}# the recessive tree, cycle 9: the bit before dominant? no run",
        f"        BRANCH 2, 0, {l3}",
        f"        BRANCH 3, 0, {l4}",
        f"        BRANCH 4, 0, {nxt}",
        "        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six",
        "        SHIFT_IN 0 [4]",
        f"        JMP {nxt}",
        f"{lab(l2)}NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth",
        f"{lab(l3)}NOP",
        f"{lab(l4)}NOP",
    ]


def a_loop_cell(n, end, pull):
    assert not pull
    z, l2, l3, l4 = n + "z", n + "l2", n + "l3", n + "l4"
    return [
        f"{lab(n)}SHIFT_OUT [4]           # {n.upper()}: driven, held five",
        "        SHIFT_IN 0              # sampled on the sixth",
        f"        BRANCH 0, 1, {z}{' ' * (10 - len(z))}# recessive: the recessive tree, cycle 7",
        f"        BRANCH 1, 1, {l2}{' ' * (10 - len(l2))}# dominant: the bit before recessive? no run, the ladder",
        f"        BRANCH 2, 1, {l3}",
        f"        BRANCH 3, 1, {l4}",
        f"        BRANCH 4, 1, {end}{' ' * (10 - len(end))}# the last rung is the REPEAT",
        "        NOP                     # five dominant: a recessive stuff bit on the thirteenth",
        "        SET 0, 1 [5]",
        "        SHIFT_IN 0 [3]",
        f"        JMP {end}",
        f"{lab(z)}BRANCH 1, 0, {l2}{' ' * (10 - len(l2))}# the recessive tree: the bit before dominant? no run",
        f"        BRANCH 2, 0, {l3}",
        f"        BRANCH 3, 0, {l4}",
        f"        BRANCH 4, 0, {end}",
        "        NOP",
        "        SET 0, 0 [5]",
        "        SHIFT_IN 0 [3]",
        f"        JMP {end}",
        f"{lab(l2)}NOP",
        f"{lab(l3)}NOP",
        f"{lab(l4)}NOP",
    ]


# -- C: two run tests, SKIP and JMP, 8 cycles a bit -----------------------------------------------

def c_cell(n, nxt, pull):
    d, r = n + "d", n + "r"
    return [
        f"{lab(n)}SHIFT_OUT [{2 if pull else 3}]           # {n.upper()}: driven, held {'three, and' if pull else 'four'}",
        *(["        PULL                    # {ID[3:0], 0000} in the fourth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
        "        SHIFT_IN 0              # sampled on the fifth",
        "        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP",
        f"        JMP {d} [1]{' ' * (12 - len(d))}# five recessive: a dominant stuff bit on the ninth",
        "        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP",
        f"        JMP {r}{' ' * (16 - len(r))}# five dominant: a recessive stuff bit on the ninth",
        f"        JMP {nxt}{' ' * (16 - len(nxt))}# no run: the next bit on the ninth",
        f"{lab(d)}SET 0, 0 [3]            # the stuff bit, dominant, driven, held four",
        "        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and",
        f"        JMP {nxt}{' ' * (16 - len(nxt))}# the eighth: the next bit",
        f"{lab(r)}SET 0, 1 [3]            # the stuff bit, recessive, let go, held four",
        "        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows",
    ]


def c_loop_cell(n, end, pull):
    assert not pull
    d, r = n + "d", n + "r"
    return [
        f"{lab(n)}SHIFT_OUT [2]           # {n.upper()}: driven, held three",
        "        SHIFT_IN 0              # sampled on the fourth",
        "        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP",
        f"        JMP {d} [2]{' ' * (12 - len(d))}# five recessive: a dominant stuff bit on the ninth",
        "        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP",
        f"        JMP {r} [1]{' ' * (12 - len(r))}# five dominant: a recessive stuff bit on the ninth",
        f"        JMP {end}{' ' * (16 - len(end))}# no run: the REPEAT on the eighth",
        f"{lab(d)}SET 0, 0 [3]            # the stuff bit, dominant",
        "        SHIFT_IN 0 [1]",
        f"        JMP {end}",
        f"{lab(r)}SET 0, 1 [3]            # the stuff bit, recessive",
        "        SHIFT_IN 0 [2]          # the REPEAT follows",
    ]


# -- AC: two BRANCH_RUNs, the fall-through the next bit, the stuff code out of line, 8 cycles -----

def ac_cell(n, nxt, pull):
    p, r = n + "p", n + "r"
    return [
        f"{lab(n)}SHIFT_OUT [{3 if pull else 4}]           # {n.upper()}: driven, held {'four, and' if pull else 'five'}",
        *(["        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
        "        SHIFT_IN 0              # sampled on the sixth",
        f"        BRANCH_RUN 5, 1, {p}{' ' * (6 - len(p))}# five recessive: a dominant stuff bit, a pad's cycle first",
        f"        BRANCH_RUN 5, 0, {r}{' ' * (6 - len(r))}# five dominant: a recessive stuff bit on the ninth; no run: the next bit follows",
    ]


def ac_blocks(n, nxt):
    p, d, r = n + "p", n + "d", n + "r"
    return [
        f"{lab(p)}NOP                     # {n.upper()}'s stuff bits: the pad, then",
        f"{lab(d)}SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth",
        "        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and",
        f"        JMP {nxt}{' ' * (16 - len(nxt))}# the eighth: the next bit",
        f"{lab(r)}SET 0, 1 [4]            # the recessive stuff bit, let go, held five",
        "        SHIFT_IN 0 [1]",
        f"        JMP {nxt}",
    ]


def ac_loop_cell(n, end, pull):
    assert not pull
    p, r = n + "p", n + "r"
    return [
        f"{lab(n)}SHIFT_OUT [2]           # {n.upper()}: driven, held three",
        "        SHIFT_IN 0              # sampled on the fourth",
        f"        BRANCH_RUN 5, 1, {p}{' ' * (6 - len(p))}# five recessive: a dominant stuff bit",
        f"        BRANCH_RUN 5, 0, {r}{' ' * (6 - len(r))}# five dominant: a recessive stuff bit",
        f"        JMP {end}{' ' * (16 - len(end))}# no run: the REPEAT on the eighth",
        f"{lab(p)}NOP [2]                 # the dominant stuff bit on the ninth",
        "        SET 0, 0 [4]",
        "        SHIFT_IN 0",
        f"        JMP {end}",
        f"{lab(r)}NOP [1]                 # the recessive stuff bit on the ninth",
        "        SET 0, 1 [4]",
        "        SHIFT_IN 0 [1]          # the REPEAT follows",
    ]


# -- D: the counter's test, then the level, SKIP and JMP, 10 cycles a bit -------------------------

def d_cell(n, nxt, pull):
    d, r = n + "d", n + "r"
    return [
        f"{lab(n)}SHIFT_OUT [{3 if pull else 4}]           # {n.upper()}: driven, held {'four, and' if pull else 'five'}",
        *(["        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
        "        SHIFT_IN 0              # sampled on the sixth",
        "        SKIP_SAME 5             # five the same? step over the JMP",
        f"        JMP {nxt} [2]{' ' * (12 - len(nxt))}# no run: the next bit on the eleventh",
        "        SKIP 0, 0               # dominant? step over the JMP",
        f"        JMP {d} [1]{' ' * (12 - len(d))}# five recessive: a dominant stuff bit on the eleventh",
        "        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh",
        f"{lab(r)}SET 0, 1 [4]            # the stuff bit, recessive, let go, held five",
        "        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and",
        f"        JMP {nxt}{' ' * (16 - len(nxt))}# the tenth: the next bit",
        f"{lab(d)}SET 0, 0 [4]            # the stuff bit, dominant, driven, held five",
        "        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows",
    ]


def d_loop_cell(n, end, pull):
    assert not pull
    d, r = n + "d", n + "r"
    return [
        f"{lab(n)}SHIFT_OUT [3]           # {n.upper()}: driven, held four",
        "        SHIFT_IN 0              # sampled on the fifth",
        "        SKIP_SAME 5             # five the same? step over the JMP",
        f"        JMP {end} [2]{' ' * (12 - len(end))}# no run: the REPEAT on the tenth",
        "        SKIP 0, 0               # dominant? step over the JMP",
        f"        JMP {d} [2]{' ' * (12 - len(d))}# five recessive: a dominant stuff bit on the eleventh",
        "        NOP [2]                 # five dominant: a recessive stuff bit on the eleventh",
        f"{lab(r)}SET 0, 1 [4]",
        "        SHIFT_IN 0 [2]",
        f"        JMP {end}",
        f"{lab(d)}SET 0, 0 [4]",
        "        SHIFT_IN 0 [3]          # the REPEAT follows",
    ]


# -- AD: BRANCH_SAME, then BRANCH on the level, the stuff code out of line, 8 cycles a bit --------

def ad_cell(n, nxt, pull):
    s = n + "s"
    return [
        f"{lab(n)}SHIFT_OUT [{3 if pull else 4}]           # {n.upper()}: driven, held {'four, and' if pull else 'five'}",
        *(["        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)"] if pull else []),
        "        SHIFT_IN 0              # sampled on the sixth",
        f"        BRANCH_SAME 5, {s}{' ' * (8 - len(s))}# five the same: a stuff bit, which level to decide",
        "        NOP                     # no run: the next bit follows, on the ninth",
    ]


def ad_blocks(n, nxt):
    s, r = n + "s", n + "r"
    return [
        f"{lab(s)}BRANCH 0, 0, {r}{' ' * (10 - len(r))}# {n.upper()}'s stuff bits: dominant run? a recessive stuff bit",
        "        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth",
        "        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and",
        f"        JMP {nxt}{' ' * (16 - len(nxt))}# the eighth: the next bit",
        f"{lab(r)}SET 0, 1 [4]            # the recessive stuff bit, let go, held five",
        "        SHIFT_IN 0 [1]",
        f"        JMP {nxt}",
    ]


def ad_loop_cell(n, end, pull):
    assert not pull
    s, r = n + "s", n + "r"
    return [
        f"{lab(n)}SHIFT_OUT [2]           # {n.upper()}: driven, held three",
        "        SHIFT_IN 0              # sampled on the fourth",
        f"        BRANCH_SAME 5, {s}{' ' * (8 - len(s))}# five the same: a stuff bit, which level to decide",
        f"        JMP {end} [1]{' ' * (12 - len(end))}# no run: the REPEAT on the eighth",
        f"{lab(s)}BRANCH 0, 0, {r}{' ' * (10 - len(r))}# dominant run? a recessive stuff bit",
        "        NOP [1]                 # the dominant stuff bit on the ninth",
        "        SET 0, 0 [4]",
        "        SHIFT_IN 0",
        f"        JMP {end}",
        f"{lab(r)}NOP [1]                 # the recessive stuff bit on the ninth",
        "        SET 0, 1 [4]",
        "        SHIFT_IN 0 [1]          # the REPEAT follows",
    ]


NONE = lambda n, nxt: []  # noqa: E731

# tag -> (L, k, unrolled cell, out-of-line blocks, looped cell, k in the loop, what, decision)
UNROLLED = {
    "base": (16, 7, base_cell, NONE),
    "A": (12, 5, a_cell, NONE),
    "C": (8, 3, c_cell, NONE),
    "AC": (8, 4, ac_cell, ac_blocks),
    "D": (10, 4, d_cell, NONE),
    "AD": (8, 4, ad_cell, ad_blocks),
}
LOOPED = {
    "base": (6, base_loop_cell),
    "A": (4, a_loop_cell),
    "C": (2, c_loop_cell),
    "AC": (2, ac_loop_cell),
    "D": (3, d_loop_cell),
    "AD": (2, ad_loop_cell),
}
WHAT = {
    "base": ("today's ISA and REPEAT",
             "The baseline's tree of single-bit SKIPs, seven cycles on the longest path after the sample, every exit a JMP\n"
             "# to the REPEAT: a JMP may land on the REPEAT that ends its body, so the cell is a body, which the 224-word\n"
             "# baseline did not use."),
    "A": ("BRANCH",
          "The decision is a tree of BRANCHes: the newest sample picks a side, four BRANCHes ask whether the four\n"
          "# before it match, out at the first that does not to a ladder of NOPs that lands every exit on the next bit\n"
          "# edge, the stuff bit at the end of the fall-through: five cycles on every path after the sample."),
    "C": ("SKIP_NORUN",
          "The decision is two run tests: five recessive? five dominant? each a SKIP_NORUN over the JMP to its stuff\n"
          "# bit, the no-run path's JMP to the next bit: three cycles on every path after the sample. The SKIP is the\n"
          "# negated test: the word after a SKIP is the case it does not cover, and a run's other case is not a level."),
    "AC": ("BRANCH_RUN",
           "The decision is two run tests, five recessive? five dominant? each a BRANCH_RUN to its stuff bit, the\n"
           "# fall-through the next bit: two cycles on every path after the sample, the stuff code out of line."),
    "D": ("SKIP_SAME, the run counter",
          "The decision is the counter's test, five the same? a SKIP_SAME over the JMP to the next bit, then the level,\n"
          "# SKIP 0 over the JMP to the dominant stuff bit: four cycles on every path after the sample."),
    "AD": ("BRANCH_SAME, the run counter",
           "The decision is the counter's test, five the same? a BRANCH_SAME to the stuff code out of line, where a\n"
           "# BRANCH on the newest bit picks the level; a NOP pads the no-run path: two cycles on every path."),
}

if __name__ == "__main__":
    for tag in ARB:
        arbitration(tag)
    for tag, (L, k, cell, blocks) in UNROLLED.items():
        cls = Candidate if tag == "base" else CANDIDATES[tag]
        what, decision = WHAT[tag]
        if tag != "base":
            stuff_program(tag, cls, L, k, cell, blocks, what, decision, loop=False)
        kl, lcell = LOOPED[tag]
        stuff_program(tag, cls, L, kl, lcell, NONE, what, decision, loop=True)
