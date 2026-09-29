"""Write the 10BASE-T experiment programs into experiments/ethernet/.

    python experiments/ethernet/gen.py

The question: how far does Protocol Engine v2 stretch for 10BASE-T if only
programs may be written? Nothing in the ISA, the model or the RTL changes
here. Every clock rate is a program shape: C clocks a bit, a half-bit C / 2.

Pins, every TX program: gpio 0 TD, the Manchester line (SHIFT_OUT's pin);
gpio 2 TX_EN, a line driver's enable, so that "idle" (no differential
voltage) is TX_EN low; gpio_in 1 RD, the squelched receive pair, 0 while
the wire is quiet, pad 1 released. The on-core encoder (eth_txr_*) needs
pad 0 as a scratch bit and so puts TD on gpio 3. Every RX program listens
on gpio_in 0, pad 0 released.

IEEE 802.3 Manchester, the convention checked by the tests: a 0 is high then
low, a 1 low then high, the transition at mid-bit; the second half is the
bit. Bytes go LSB first.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent.parent / "model")]

from cpu import assemble  # noqa: E402

TD, RD, TX_EN, TD_R = 0, 1, 2, 3  # TD on pin 0; RD on gpio_in 1; TX_EN on pin 2; TD of the on-core encoder on pin 3


def tidy(line):
    if "#" not in line or line.lstrip().startswith("#"):
        return line.rstrip()
    code, comment = line.split("#", 1)
    return f"{code.rstrip():34}# {comment.strip()}"


def out(name, header, lines, write=True):
    """Assemble `lines`; with `write`, experiments/ethernet/<name>.asm with the
    word counts in the header. Returns the source."""
    lines = [tidy(line) for line in lines]
    words = assemble("\n".join(lines) + "\n")
    text = header.strip("\n").replace("{words}", str(len(words))).replace("{distinct}", str(len(set(words))))
    source = text + "\n\n" + "\n".join(lines) + "\n"
    if write:
        (HERE / f"{name}.asm").write_text(source)
        print(f"{name}: {len(words)} words, {len(set(words))} distinct")
    return source


def d(n):
    """A delay suffix: `[n]`, or nothing for 0."""
    if n < 0:
        raise ValueError(f"negative delay {n}: the shape does not fit")
    return f" [{n}]" if n else ""


def halves_of(mhz):
    """Cycles per half-bit, first and second half, at `mhz`: 10 Mb/s is 100 ns a
    bit. 50 MHz has 5 clocks a bit, halves of 3 and 2."""
    c = mhz // 10
    return (c - c // 2, c // 2)


def manchester(bits):
    """Half-bit levels, IEEE 802.3: a 0 is (1, 0), a 1 is (0, 1)."""
    return [h for b in bits for h in (1 - b, b)]


def lsb_bits(data):
    return [(byte >> i) & 1 for byte in data for i in range(8)]


# ---------------------------------------------------------------------------
# Stage 1: a fixed pattern, every half-bit a SET


def tx_fixed(byte=0xA5, mhz=40, write=True):
    h1, h2 = halves_of(mhz)
    lines = [
        f"        SET {TX_EN}, 0                     # TX_EN low: the wire idle (reset drives every pad high)",
        f"        SET {TD}, {1 - (byte & 1)}                     # TD at the first half of bit 0 while still idle",
    ]
    levels = manchester(lsb_bits([byte]))
    for i, level in enumerate(levels):
        hold = h1 if i % 2 == 0 else h2
        if i == 0:
            lines.append(f"        SET {TX_EN}, 1{d(hold - 1)}                # TX_EN: the first half of bit 0, TD already there")
            continue
        lines.append(f"        SET {TD}, {level}{d(hold - 1)}                 # bit {i // 2} {'second' if i % 2 else 'first'} half")
    lines += [
        f"        SET {TD}, 1{d(3 * (h1 + h2) - 1)}                # TP_IDL: high for three bit times, 300 ns",
        f"        SET {TX_EN}, 0                     # idle",
    ]
    header = f"""# 10BASE-T stage 1: the byte {byte:#04x} Manchester-encoded, LSB first, at
# {mhz} MHz ({h1} + {h2} clocks a bit), every half-bit a SET on TD (gpio {TD}), TX_EN
# (gpio {TX_EN}) high around it, then TP_IDL and idle. {{words}} words. Halts."""
    return out(f"eth_tx_fixed", header, lines, write)


# ---------------------------------------------------------------------------
# Stage 3: preamble and SFD from the program


def tx_preamble(mhz=40, write=True):
    """7 x 0x55 then 0xD5, LSB first: 1 0 1 0 ... 1 0 1 1. Each (1, 0) pair is
    low, high, high, low: a square wave at 5 MHz with an edge at every
    mid-bit. The body starts at the mid-bit rise of a 1."""
    h1, h2 = halves_of(mhz)
    assert h1 == h2, "the preamble body assumes equal halves"
    h = h1
    lines = [
        f"        SET {TX_EN}, 0                     # idle",
        f"        SET {TD}, 0                        # TD low: bit 0 is a 1, its first half low",
        f"        SET {TX_EN}, 1{d(h - 1)}                # TX_EN: the first half of bit 0",
        f"pair:   SET {TD}, 1{d(2 * h - 1)}                 # mid-bit rise of a 1: its second half, the first half of the 0 after it",
        f"        SET {TD}, 0{d(2 * h - 2)}                 # mid-bit fall of the 0: its second half, the first half of the next 1",
        f"        REPEAT 31, pair                   # 31 pairs: bits 0..61, and the first half of bit 62",
        f"        SET {TD}, 1{d(h - 1)}                 # bit 62, the SFD's seventh, a 1: second half",
        f"        SET {TD}, 0{d(h - 1)}                 # bit 63, a 1: first half",
        f"        SET {TD}, 1{d(h - 1 + 3 * 2 * h)}                # its second half, then TP_IDL held high three bit times",
        f"        SET {TX_EN}, 0                     # idle",
    ]
    header = f"""# 10BASE-T stage 3: the preamble (7 x 0x55) and the SFD (0xD5), LSB first, from
# the program alone at {mhz} MHz: the 62 alternating bits are one REPEAT of a
# two-word pair, the SFD's closing 1 1 written out. {{words}} words. Halts."""
    return out("eth_tx_preamble", header, lines, write)


# ---------------------------------------------------------------------------
# Stages 2, 4, 5, 8: the host-encoded transmitter
#
# The host sends half-bits: a data byte is two host bytes, bit 2i of a host
# byte the first half of data bit i, bit 2i + 1 its second half. SHIFT_OUT
# puts one half-bit on TD. Between SHIFT_OUTs k and k + 1 there are halves[k]
# - 1 free clocks, one timed job each:
#
#   after S1, S2   SHIFT_IN 0: TD read back through its own pad
#   after S3       SKIP_NORUN 2, 1 over JMP end: S1 = S2 = 1 is no data bit,
#                  the host's end marker, and the start of TP_IDL
#   after S4, S6   SHIFT_IN 1: RD, two samples a host byte
#   after S7       SKIP_RUN 2, 0 over JMP collide: RD active while we send
#   after S8       PULL
#   after S5       JMP top, the loop's back edge
#
# A SKIP's skipped JMP costs nothing on the path that skips it, so each check
# is one timed clock.


def tx_host(mhz, write=True):
    c = mhz // 10
    h1, h2 = halves_of(mhz)
    halves = [h1, h2] * 4
    slot = [h - 1 for h in halves]  # free clocks after S1..S8
    if min(slot) < 1:
        return tx_host_no_slots(mhz, write)

    def s(k, extra=""):
        return f"SHIFT_OUT{extra}{d(slot[k - 1] - 1)}"

    tp_idl = 3 * c  # clocks TD stays high from the end marker's S1 before TX_EN drops
    to_end = halves[0] + halves[1] + halves[2] + 1  # S1 to the first word at `end`
    lines = [
        f"        CONFIG open_drain01, 2            # RD's pad (1) released; TD (0) push-pull",
        f"        SET {TX_EN}, 0                     # TX_EN low: idle (reset drives every pad high)",
        f"frame:  PULL                              # the frame's first host byte; the idle wire waits safely",
        f"cs:     SHIFT_IN {RD}{d(h2 - 1)}                # carrier sense: RD four times, {h2} clocks apart, a half-bit:",
        f"        SHIFT_IN {RD}{d(h2 - 1)}                # a high run is never shorter, so one sample is high",
        f"        SHIFT_IN {RD}{d(h2 - 1)}",
        f"        SHIFT_IN {RD}",
        f"        SKIP_RUN 4, 0                     # all quiet: go",
        f"        JMP cs                            # carrier: defer",
        f"        JMP s1",
        f"top:    {s(6)}                            # S6",
        f"        SHIFT_IN {RD}                        # RD",
        f"        {s(7)}                            # S7",
        f"        SKIP_RUN 2, 0                     # RD quiet at both samples: skip the JMP",
        f"        JMP collide                       # not taken while RD is quiet: costs no clock",
        f"        {s(8)}                            # S8",
        f"        PULL                              # the next host byte; a stall here breaks the frame",
        f"s1:     {s(1, f' {TX_EN}, 1')}                   # S1, and TX_EN (already high after the first)",
        f"        SHIFT_IN {TD}                        # S1 back through the pad",
        f"        {s(2)}                            # S2",
        f"        SHIFT_IN {TD}                        # S2 back",
        f"        {s(3)}                            # S3",
        f"        SKIP_NORUN 2, 1                   # a real bit, S1 != S2: skip the JMP",
        f"        JMP end                           # S1 = S2 = 1: the host's end marker, TP_IDL has begun",
        f"        {s(4)}                            # S4",
        f"        SHIFT_IN {RD}                        # RD",
        f"        {s(5)}                            # S5",
        f"        JMP top",
        f"end:    NOP{d(tp_idl - to_end - 1)}                            # TP_IDL: TD high since the marker's S1",
        f"        SET {TX_EN}, 0                     # {tp_idl} clocks, 300 ns, after the marker: idle",
        f"        SHIFT_IN {TX_EN}                        # status: TX_EN read back, 0 = sent",
        f"        PUSH                              # to the host: bit 7 of the byte",
        f"        JMP frame",
        f"collide: SET {TD}, 1{d(h1 - 1)}                # the jam, 32 bits of 0",
        f"        SET {TD}, 0{d(h2 - 2)}",
        f"        REPEAT 32, collide",
        f"        SET {TD}, 1{d(tp_idl - 2)}                # TP_IDL after the jam",
        f"        SHIFT_IN {TX_EN}                        # status: TX_EN read back while still high, 1 = collision",
        f"        SET {TX_EN}, 0                     # idle",
        f"        PUSH                              # to the host",
        f"drain:  PULL                              # the rest of the frame, TX_EN low, up to the end marker",
        f"        SHIFT_OUT",
        f"        SHIFT_IN {TD}",
        f"        SHIFT_OUT",
        f"        SHIFT_IN {TD}",
        f"        SKIP_NORUN 2, 1",
        f"        JMP frame                         # the end marker: the next frame",
        f"        JMP drain",
    ]
    header = f"""# 10BASE-T transmitter at {mhz} MHz, the host's half-bits: {c} clocks a bit, halves of
# {h1} and {h2}. The host sends each data byte as two bytes of Manchester half-bits
# (bit 2i = the first half of data bit i, bit 2i + 1 its second half), the
# preamble and SFD likewise, the FCS it computed likewise, then an end marker
# 0xFF: a first bit cell of two highs, which no data bit is. SHIFT_OUT puts
# one half-bit a word on TD (gpio {TD}); between two SHIFT_OUTs sits one word:
# TD read back twice for the end marker, RD (gpio_in {RD}) sampled twice for a
# collision, the PULL, the loop's JMP. Carrier sense before the frame; after
# it TP_IDL, TX_EN (gpio {TX_EN}) low and a status byte to the host, bit 7 set on a
# collision, which sends the jam and drains the frame's remaining bytes.
# {{words}} words, {{distinct}} distinct."""
    return out(f"eth_tx_{mhz}", header, lines, write)


def tx_host_no_slots(mhz, write=True):
    """At one clock a half-bit there is no free clock: the PULL and the loop's
    JMP stretch the last half-bit of every host byte by two clocks."""
    lines = [
        f"        SET {TX_EN}, 0                     # idle",
        f"top:    PULL                              # a host byte of half-bits",
        f"        SHIFT_OUT {TX_EN}, 1                   # S1 and TX_EN",
        "        SHIFT_OUT                         # S2",
        "        SHIFT_OUT                         # S3",
        "        SHIFT_OUT                         # S4",
        "        SHIFT_OUT                         # S5",
        "        SHIFT_OUT                         # S6",
        "        SHIFT_OUT                         # S7",
        "        SHIFT_OUT                         # S8: held three clocks, through the JMP and the PULL",
        "        JMP top",
    ]
    header = f"""# 10BASE-T transmitter at {mhz} MHz, the host's half-bits, one clock a half-bit:
# there is no free clock for the PULL or the JMP, so the last half-bit of every
# host byte lasts three clocks, not one. Kept as the record of why {mhz} MHz
# fails: 10 clocks for 8 half-bits. No end marker, no carrier sense.
# {{words}} words."""
    return out(f"eth_tx_{mhz}", header, lines, write)


# ---------------------------------------------------------------------------
# Stage 2 again: Manchester from raw bytes, on the core
#
# The data bit has to be known before its first half goes out, which is its
# complement. SHIFT_OUT puts the next bit on pad 0, a scratch pad nothing
# listens to; SHIFT_IN reads it back; a SKIP on it picks one of two copies of
# the next bit's block, one per value, whose SETs are constants. So each bit
# is a block, for each of 8 bit positions and 2 values:
#
#   SHIFT_OUT 3, !c   TD = !c (first half), pad 0 = the next bit
#   SHIFT_IN 0        the next bit read back
#   SKIP 7, 1, 3, c   TD = c at mid-bit; a 1 next skips to the second JMP
#   JMP next0 / JMP next1
#
# 4 clocks at least, and bit 7's block needs a PULL before its SHIFT_OUT, a
# fifth: 33 clocks a byte where 40 MHz has 32.


def tx_raw(mhz, write=True):
    c = mhz // 10
    h1, h2 = halves_of(mhz)
    if c == 4:  # the shape that fails: halves of 2, bit 7's first half 3
        h1, h2 = 2, 2
    lines = [
        f"        SET {TX_EN}, 0                     # idle",
        "        PULL                              # the first byte",
        "        SHIFT_OUT                         # its bit 0 on the scratch pad",
        "        SHIFT_IN 0                        # read back",
        "        SKIP 7, 1",
        "        JMP go0",
        "        SET 3, 0                          # TD = !1 before TX_EN",
        "        JMP go",
        "go0:    SET 3, 1                          # TD = !0 before TX_EN",
        "go:     SKIP 7, 1, 2, 1                   # TX_EN high: bit 0's first half from here, two clocks long",
        "        JMP b0v0",
        "        JMP b0v1",
    ]
    for k in range(8):
        for v in (0, 1):
            nxt = (k + 1) % 8
            if k < 7:
                body = [
                    f"b{k}v{v}:  SHIFT_OUT {TD_R}, {1 - v}{d(h1 - 2)}             # bit {k} = {v}: TD = {1 - v}; pad 0 = bit {k + 1}",
                    "        SHIFT_IN 0                        # bit {} read back".format(k + 1),
                ]
            else:
                body = [
                    f"b{k}v{v}:  PULL {TD_R}, {1 - v}                      # bit 7 = {v}: TD = {1 - v}; the next byte",
                    f"        SHIFT_OUT{d(max(h1, 3) - 3)}                  # pad 0 = its bit 0",
                    "        SHIFT_IN 0                        # read back",
                ]
            body += [
                f"        SKIP 7, 1, {TD_R}, {v}{d(h2 - 2)}              # mid-bit: TD = {v}; a 1 next skips",
                f"        JMP b{nxt}v0",
                f"        JMP b{nxt}v1",
            ]
            lines += body
    note = ("bit 7's block has a PULL too and lasts 5, so one half-bit a byte is 3 clocks: the record of why 40 MHz fails"
            if c == 4 else f"halves of {h1} and {h2}")
    header = f"""# 10BASE-T transmitter at {mhz} MHz, Manchester from raw host bytes on the core:
# TD on gpio {TD_R}, TX_EN on gpio {TX_EN}, pad 0 a scratch bit read back through its pad.
# {c} clocks a bit, {note}. Each bit is a block in two copies, one per value;
# the SKIP on the next bit, read back from pad 0, picks the next block. No
# frame end: every byte value is data, no count longer than 32 exists, so the
# PULL after the last byte stalls mid-bit with TX_EN high.
# {{words}} words, {{distinct}} distinct."""
    return out(f"eth_txr_{mhz}", header, lines, write)


# ---------------------------------------------------------------------------
# Stage 5: normal link pulses while idle


def nlp(mhz=40, inner=39, write=True):
    """A 100 ns pulse every ~16 ms. REPEAT does not nest and counts to 32, so
    16 ms (640 000 clocks at 40 MHz) is a Johnson counter in in_shift_reg:
    pad 3 set to NOT the oldest sample and read back, 16 states, all ones
    once, around an inner REPEAT of `inner` NOP [31]."""
    c = mhz // 10
    lines = [
        f"        SET {TX_EN}, 0                     # idle",
        f"        SET {TD}, 1                        # TD high: a pulse is TX_EN with TD high",
        f"pulse:  SET {TX_EN}, 1{d(c - 1)}                # the link pulse, 100 ns",
        f"        SET {TX_EN}, 0                     # idle",
    ]
    lines.append("wait:   NOP [31]")
    lines += ["        NOP [31]"] * (inner - 1)
    lines += [
        "        REPEAT 32, wait                   # 32 x (32 x inner + 1) clocks",
        "        SET 3, 0                          # the Johnson step: pad 3 = NOT the oldest sample",
        "        SKIP 0, 1",
        "        SET 3, 1",
        "        SHIFT_IN 3                        # read back: the newest sample",
        "        SKIP_RUN 8, 1                     # all ones: once in 16 steps",
        "        JMP wait",
        "        JMP pulse",
    ]
    header = f"""# 10BASE-T normal link pulses at {mhz} MHz: TX_EN (gpio {TX_EN}) high for 100 ns with TD
# high, about every 16 ms. The core cannot count past 32 and REPEAT does not
# nest, so the long wait is an inner REPEAT and a Johnson counter kept in
# in_shift_reg through pad 3 (a scratch pad read back). Idle only: a program
# waiting for the host can only stall on PULL, which stops the pulses.
# {{words}} words."""
    return out("eth_nlp", header, lines, write)


# ---------------------------------------------------------------------------
# Stage 7: receivers


def rx_fixed(mhz, write=True):
    """WAIT for a preamble rise, the mid-bit of a 1, then sample the second
    half of every bit at a fixed clock; the SFD is the first 1 1."""
    c = mhz // 10
    lines = [
        "        CONFIG open_drain01, 1            # pad 0 released: RD",
        "        WAIT 0, 0                         # quiet or a low half",
        "        WAIT 0, 1                         # a rise: the preamble's mid-bit of a 1 (m)",
        "hunt:   SHIFT_IN 0                        # the second half of the bit, m + 1: the bit",
        "        SKIP_RUN 2, 1                     # 1 1: the SFD's end",
        f"        JMP hunt{d(c - 3)}",
    ]
    lines.append(f"        NOP{d(c - 3)}                              # the SFD found: on to bit 0's sample")
    lines += [
        f"data:   SHIFT_IN 0{d(c - 2)}                # bits 0..6, one sample every {c} clocks",
        "        REPEAT 7, data",
        f"        SHIFT_IN 0{d(c - 3)}                # bit 7",
        "        PUSH                              # the byte, LSB first",
        "        JMP data",
    ]
    header = f"""# 10BASE-T receiver at {mhz} MHz with fixed sampling: one WAIT for a preamble rise,
# then every bit sampled one clock after where its mid-bit edge should be, {c}
# clocks a bit, never re-aligned; the SFD is the first two 1s in a row. RD on
# gpio_in 0. Runs forever: the frame's end is the carrier going away, which
# nothing waits for. {{words}} words."""
    return out(f"eth_rx_fixed_{mhz}", header, lines, write)


def track_offset(c):
    """The first-half sample's clock after the edge: as late as the fall
    path's WAIT allows (a <= C - 3), but one earlier from 8 clocks a bit on,
    so the WAIT is up a clock before an early edge; at 8, a = 4 leaves the
    sample on the boundary at the worst phase and a = 5 the WAIT on the edge."""
    return c - 3 if c < 8 else c - 4


def rx_track(mhz, a=None, write=True):
    """Re-align on every mid-bit edge. The first half of bit k is sampled a
    clocks after bit k - 1's mid-bit edge (m); it is the complement of the
    bit, so it also says which way bit k's edge goes: SKIP picks WAIT 0, 1
    or WAIT 0, 0, and the WAIT issues on the edge, the next m. The path that
    does not skip takes a JMP first, so its WAIT is up at m + a + 3, which
    must be no later than the next edge: a <= C - 3. The sample must be past
    the boundary, m - 1 + C / 2 at the worst phase: a >= C / 2. The byte is
    the complement of the data: the host inverts it."""
    c = mhz // 10
    a = track_offset(c) if a is None else a
    name = f"eth_rx_track_{mhz}" + ("" if a == track_offset(c) else f"_a{a}")
    lines = [
        "        CONFIG open_drain01, 1            # pad 0 released: RD",
        "        WAIT 0, 0",
        "        WAIT 0, 1                         # a preamble rise: m",
        "hunt:   SHIFT_IN 0                        # m + 1: the bit, from its second half",
        "        SKIP_RUN 2, 1                     # 1 1: the SFD's end",
        f"        JMP hunt{d(c - 3)}",
    ]
    if a >= 3:
        if a > 3:
            lines.append(f"        NOP{d(a - 4)}                              # to bit 0's first half, m + {a}")
    else:  # the SFD found lands at m + 3, later than m + a: bit 0 is a fixed cell
        lines += [
            "        SHIFT_IN 0                        # m + 3: bit 0's first half, not re-aligned",
            f"        JMP c1{d(c + a - 5)}",
        ]
    for k in range(8):
        if k == 7 and a < 3:  # no room for the PUSH after a WAIT: bit 7 is a fixed cell
            lines += [
                "c7:     SHIFT_IN 0                        # bit 7's first half, not re-aligned",
                "        PUSH                              # the byte, inverted",
                f"        JMP c0{d(c - 3)}",
            ]
            continue
        lines += [
            f"c{k}:     SHIFT_IN 0                        # bit {k}'s first half: its complement",
            "        SKIP 7, 0                         # a 0 there: the bit is 1, a rise at mid-bit",
            f"        JMP f{k}                           # a 1: a fall, its WAIT a clock later",
        ]
        if k == 7:
            lines += [
                "        WAIT 0, 1                         # the rise: m",
                f"        PUSH{d(a - 3)}                              # the byte, inverted",
                "        JMP c0",
                "f7:     WAIT 0, 0                         # the fall: m",
                f"        PUSH{d(a - 3)}",
                "        JMP c0",
            ]
        else:
            lines.append(f"        WAIT 0, 1{d(a - 1)}                 # the rise: m, then on into bit {k + 1}")
    for k in range(7):
        lines += [
            f"f{k}:     WAIT 0, 0{d(a - 2)}                 # the fall: m",
            f"        JMP c{k + 1}",
        ]
    note = (f"the sample {a} clocks after the edge, the WAIT up {c - a - 3} clock(s)\n# before the next"
            if a >= 3 else f"the sample {a} clocks after the edge, past the boundary\n# at only some phases")
    header = f"""# 10BASE-T receiver at {mhz} MHz re-aligning on every mid-bit edge, {c} clocks a
# bit: {note}. Each bit's first half, the complement of the bit, is sampled
# and picks WAIT 0, 1 or WAIT 0, 0 for the edge at its mid-bit; the WAIT
# issues on it. The byte pushed is the data inverted. The preamble and SFD
# are found at fixed timing as eth_rx_fixed does. RD on gpio_in 0. Runs
# forever. {{words}} words, {{distinct}} distinct."""
    return out(name, header, lines, write)


TX_CLOCKS = (20, 40, 50, 60, 80, 100)
TXR_CLOCKS = (40, 50, 60, 80)
RX_CLOCKS = (40, 50, 60, 80, 100)
TRACK_CLOCKS = (50, 60, 80, 90, 100)

if __name__ == "__main__":
    tx_fixed()
    tx_preamble()
    for mhz in TX_CLOCKS:
        tx_host(mhz)
    for mhz in TXR_CLOCKS:
        tx_raw(mhz)
    nlp()
    for mhz in RX_CLOCKS:
        rx_fixed(mhz)
    for mhz in TRACK_CLOCKS:
        rx_track(mhz)
    rx_track(80, a=5)
