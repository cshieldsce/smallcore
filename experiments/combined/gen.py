"""Write the combined CAN programs into experiments/combined/.

    python experiments/combined/gen.py

The payoff test for the run test and the accumulator: a whole frame on the
ISA as it is, at 8 clocks a bit, in 256 words. Every checked bit is one
cell, 8 cycles on the path that stuffs nothing and 16 on one that stuffs:

  b1..b3   the bit onto the pad and the words that ride before the sample:
           ACC_CRC on the pad for a data bit, the PULL in a body's first
           cell, or ACC_OUT for a CRC bit, which is the bit
  b4       SHIFT_IN: the level through the third clock, 37.5%
  b5..b8   the run test both ways, a JMP into the stuff code or on
  b9..b16  the stuff bit, SET, sampled on its fourth clock as every bit

can_tx_combined.asm (stage 6A): unopposed, the pad on the bus, the CRC in
the accumulator. The rest of the programs are written by the functions
below as the stages need them.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent.parent / "sim")]

from cpu import assemble  # noqa: E402


def tidy(line):
    if "#" not in line or line.lstrip().startswith("#"):
        return line.rstrip()
    code, comment = line.split("#", 1)
    return f"{code.rstrip():32}# {comment.strip()}"


def out(name, header, lines, write=True):
    """Assemble `lines`; with `write`, experiments/combined/<name>.asm with the
    header's counts filled in. Returns the program's source."""
    lines = [tidy(line) for line in lines]
    words = assemble("\n".join(lines) + "\n")
    text = header.rstrip("\n").replace("{words}", str(len(words))).replace("{distinct}", str(len(set(words))))
    source = text + "\n\n" + "\n".join(lines) + "\n"
    if write:
        (HERE / f"{name}.asm").write_text(source)
        print(f"{name}: {len(words)} words, {len(set(words))} distinct")
    return source


def cell(p, before, nxt, last=False, pin=0):
    """A checked bit: `before`, the words of b1..b3 (three cycles, the bit
    onto the pad first), the sample on b4, the run test, the stuff code.
    `nxt` is the next cell, reached on b9 (b17 after a stuff bit); `last`
    means the next word is the body's REPEAT, reached on b8 (b16)."""
    lines = [f"{p}: {before[0]}"] + before[1:]
    lines += [f"SHIFT_IN {pin}  # b4: the level through the third clock",
              f"SKIP_NORUN 5, 1  # b5: not five recessive? step over",
              f"JMP {p}d [2]  # five recessive: a dominant stuff bit on b9",
              f"SKIP_NORUN 5, 0  # b6: not five dominant? step over",
              f"JMP {p}r [1]  # five dominant: a recessive stuff bit on b9"]
    if last:
        lines += [f"JMP {nxt}  # no run: the REPEAT on b8",
                  f"{p}d: SET 0, 0 [2]  # the stuff bit, dominant, driven", f"SHIFT_IN {pin} [2]  # sampled on its fourth clock", f"JMP {nxt}  # the REPEAT on b16",
                  f"{p}r: SET 0, 1 [2]  # the stuff bit, recessive, let go", f"SHIFT_IN {pin} [3]  # sampled on its fourth clock; the REPEAT on b16"]
    else:
        lines += [f"JMP {nxt} [1]  # no run: the next bit on b9",
                  f"{p}d: SET 0, 0 [2]  # the stuff bit, dominant, driven", f"SHIFT_IN {pin} [3]  # sampled on its fourth clock", f"JMP {nxt}  # the next bit on b17",
                  f"{p}r: SET 0, 1 [2]  # the stuff bit, recessive, let go", f"SHIFT_IN {pin} [4]  # sampled on its fourth clock; the next bit on b17"]
    return lines


DATA = ["SHIFT_OUT [1]  # b1: the bit onto the pad, held to b2", "ACC_CRC 0  # b3: the pad into the CRC, the level through the second clock"]
PULLED = ["SHIFT_OUT  # b1: the bit onto the pad, the byte's last", "PULL  # b2: the next byte (stalls while the FIFO is empty: the bit stretches)", "ACC_CRC 0  # b3: the pad into the CRC, the level through the second clock"]
CRC = ["ACC_OUT 0 [2]  # b1: the CRC's next bit onto the pad from acc[15], held to b3"]

TX_HEADER = """# CAN transmitter, stage 6A: stage 5A's data frame with the run test and
# the accumulator, 8 clocks a bit. Unopposed, the pad on the bus. The CRC is
# the core's: every data bit goes onto the pad and back into ACC_CRC on the
# third clock of its bit, the level through the second, and the fifteen CRC bits leave from acc by ACC_OUT,
# stuffed as every bit, so the host writes no CRC. Every checked bit is one
# cell: the bit and the words that ride before the sample on clocks 1 to 3,
# the sample on the 4th (the level through the 3rd, 37.5%), the run test both
# ways, the stuff bit on the 9th. The body is stage 5A's, eight cells with
# the PULL in the first, run 2 + DLC times, the last data bit a cell of its
# own, then the CRC a one-cell body run fifteen times. The host writes the
# polynomial, 0x32 then 0x8B, once, then per frame {SOF, ID[10], ID[9],
# 00000}, ID[8:1], {ID[0], RTR, IDE, r0, DLC[3:0]} and the data: 3 + DLC
# bytes. After the CRC, stage 5A's fixed form at 8 clocks a bit. Acked, the
# program halts; not acked, it goes round for the host's next frame, the
# polynomial kept. {words} words, {distinct} distinct.
"""


def tx_unopposed(dlc=1):
    lines = ["CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive",
             "CONFIG shift_dir, 1  # MSB first",
             "PULL  # the polynomial's low byte, 0x32", "ACC_LOAD", "PULL  # its high byte, 0x8B", "ACC_LOAD  # poly = 0x4599 left-aligned",
             "frame: SHIFT_IN 0  # the idle bus, recessive: the register below the SOF holds a 1",
             "PULL  # {SOF, ID[10], ID[9], 00000} (stalls while the FIFO is empty: between frames, the bus idle)",
             "lead: SHIFT_OUT [1]  # the SOF and ID[10]: b1 to b2", "ACC_CRC 0  # b3", "SHIFT_IN 0 [3]  # b4 to b7: no run of five can end here",
             "REPEAT 2, lead  # b8"]
    for k in range(8):
        lines += cell(f"b{k}", PULLED if k == 0 else DATA, "end" if k == 7 else f"b{k + 1}", last=k == 7)
    lines += [f"end: REPEAT {2 + dlc}, b0  # 2 + DLC runs: ID[9] to the last data byte's bit 1"]
    lines += cell("tail", DATA, "crc")
    lines += cell("crc", CRC, "crc_end", last=True)
    lines += ["crc_end: REPEAT 15, crc  # the CRC, CRC[14] first; acc clear after the fifteenth",
              "SET 0, 1 [7]  # the CRC delimiter: recessive, let go, a full bit",
              "NOP [2]  # the ACK slot: let go still, and",
              "SHIFT_IN 0 [4]  # sampled on its fourth clock: a receiver that took the frame pulls it dominant",
              "PUSH [7]  # the ACK delimiter: {the last seven samples, ACK} to the host",
              "gap: NOP [6]  # EOF and the intermission: ten recessive bits", "REPEAT 10, gap",
              "SKIP 0, 0  # acked? step over the JMP: halted, the bus idle",
              "JMP frame  # not acked: the frame again, from the host's next bytes"]
    return out("can_tx_combined", TX_HEADER, lines)


ARB_HEADER = """# CAN transmitter, stage 6B: stage 6A with arbitration, for identifier
# {ident:#05x} and DLC {dlc}. Arbitration wants the bit a node sent beside the
# bit on the bus, and stuffing the last five bus bits, from the one register
# the run test and SKIP read: two samples a bit leave four bits of history,
# so the run test cannot see five. The identifier in the program makes the
# comparison the assembler's: the header, SOF, ID, RTR, IDE, r0 and the
# DLC, is written out bit by bit with its stuff bits, known in advance; a
# recessive bit samples the bus and leaves for `lost` if it reads dominant,
# a dominant bit only samples it, and every sample goes into the register so
# the run test is right when the data starts. The pad is on the bus,
# open-drain, one pin. The data and the CRC are stage 6A's. The host writes
# the polynomial once, then per frame the data shifted a bit, {{d0[7],
# 0000000}}, {{d0[6:0], d1[7]}}, ..., {{d[DLC-1][6:0], 0}}: DLC + 1 bytes. Lost,
# the pad lets go on the bit it lost on, the host reads two bytes, the
# samples to the dominant bit, and the program halts. {{words}} words,
# {{distinct}} distinct.
"""


def header_bits(ident, dlc):
    """SOF, ID[10:0], RTR, IDE, r0, DLC[3:0]: the stuffed region before the data, a data frame in base format."""
    return [0] + [(ident >> i) & 1 for i in range(10, -1, -1)] + [0, 0, 0] + [(dlc >> i) & 1 for i in range(3, -1, -1)]


def stuffed_with_flags(bits):
    """The bits as they go on the bus, each with True if it is a stuff bit."""
    out, level, count = [], None, 0
    for bit in bits:
        out.append((bit, False))
        level, count = (level, count + 1) if bit == level else (bit, 1)
        if count == 5:
            out.append((1 - bit, True))
            level, count = 1 - bit, 1
    return out


def static_cell(k, bit, stuff):
    """One header bit the program knows: driven on b1, into the CRC on b2 unless a stuff bit, sampled on b4;
    recessive, a dominant sample is a lost arbitration, or a bit error past it."""
    name = "stuff" if stuff else "bit"
    lines = [f"h{k}: SET 0, {bit} [{2 if stuff else 1}]  # b1: header {name} {k}, {'recessive, let go' if bit else 'dominant, driven'}"]
    if not stuff:
        lines += ["ACC_CRC 0  # b3: the pad into the CRC, the level through the second clock"]
    if bit:
        lines += ["SHIFT_IN 0  # b4: the bus", "SKIP 0, 1 [3]  # recessive as sent? step over the JMP on b9: the next bit",
                  "JMP lost  # dominant: lost"]
    else:
        lines += ["SHIFT_IN 0 [4]  # b4: the bus, held to b8"]
    return lines


def tx_arbitration(ident, dlc=1, write=True):
    """Stage 6B for `ident`: the source, written to can_tx_arb_<ident>.asm when `write`."""
    lines = ["CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive",
             "CONFIG shift_dir, 1  # MSB first",
             "PULL  # the polynomial's low byte, 0x32", "ACC_LOAD", "PULL  # its high byte, 0x8B", "ACC_LOAD  # poly = 0x4599 left-aligned",
             "frame: SHIFT_IN 0  # the idle bus, recessive: the register below the SOF holds a 1",
             "PULL  # {d0[7], 0000000} (stalls while the FIFO is empty: between frames, the bus idle)"]
    for k, (bit, stuff) in enumerate(stuffed_with_flags(header_bits(ident, dlc))):
        lines += static_cell(k, bit, stuff)
    for k in range(8):
        lines += cell(f"b{k}", PULLED if k == 0 else DATA, "end" if k == 7 else f"b{k + 1}", last=k == 7)
    lines += [f"end: REPEAT {dlc}, b0  # DLC runs: every data bit, the PULL in each run's first cell taking the next byte"]
    lines += cell("crc", CRC, "crc_end", last=True)
    lines += ["crc_end: REPEAT 15, crc  # the CRC, CRC[14] first; acc clear after the fifteenth",
              "SET 0, 1 [7]  # the CRC delimiter: recessive, let go, a full bit",
              "NOP [2]  # the ACK slot: let go still, and",
              "SHIFT_IN 0 [4]  # sampled on its fourth clock: a receiver that took the frame pulls it dominant",
              "PUSH [7]  # the ACK delimiter: {the last seven samples, ACK} to the host",
              "gap: NOP [6]  # EOF and the intermission: ten recessive bits", "REPEAT 10, gap",
              "SKIP 0, 0  # acked? step over the JMP: halted, the bus idle",
              "JMP frame  # not acked: the frame again, from the host's next bytes",
              "JMP done  # halted",
              "lost: PUSH  # lost: let go since the recessive bit, the samples to the dominant one to the host",
              "PUSH  # twice: a won frame hands the host one byte",
              "done: NOP"]
    header = ARB_HEADER.format(ident=ident, dlc=dlc)
    return out(f"can_tx_arb_{ident:03x}", header, lines, write)


RX_HEADER = """# CAN receiver, stage 6C: three streams, two places. The raw history for the
# run test in in_shift_reg; the CRC in the accumulator, ACC_CRC on the pad
# the clock after every data sample, stuff bits left out; and the data, which
# has nowhere left to go, through the RX FIFO one bit a byte as in
# can_rx_bits_C.asm: a PUSH of in_shift_reg after every data sample, the
# data bit its bit 0. 8 clocks a bit, the sample on the 7th clock (the level
# through the 6th), the CRC's on the 8th. The CRC runs over the whole
# destuffed stream, the frame's CRC included, so what is left is 0 when the
# CRC matched: after the intermission two ACC_PUSHes hand the host that
# residue, low byte first. The ACK is pulled whatever the CRC said: the
# residue is in acc, and nothing but a pin and a sample takes a bit of acc to
# the pc, fifteen of them, where the CRC delimiter leaves eight clocks. For
# DLC 1, as the other receivers. The host writes the polynomial, 0x32 then
# 0x8B, and pops 42 + 2 bytes a frame. {words} words, {distinct} distinct.
"""


def rx_crc():
    lines = ["CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening",
             "CONFIG shift_dir, 1  # MSB first: a sample enters at bit 0",
             "PULL  # the polynomial's low byte, 0x32", "ACC_LOAD", "PULL  # its high byte, 0x8B", "ACC_LOAD  # poly = 0x4599 left-aligned",
             "SHIFT_IN 0  # the idle bus, recessive: the register below the SOF holds a 1",
             "WAIT 0, 0 [4]  # the SOF's edge, held through its fifth clock"]
    for p, count in (("bit", 32), ("bit2", 10)):
        lines += [f"{p}: SHIFT_IN 0  # b1: the seventh clock of a data bit, the level through the sixth",
                  "ACC_CRC 0  # b2: the level through the seventh into the CRC",
                  "PUSH  # b3: the register to the host, the data bit its bit 0",
                  "SKIP_NORUN 5, 1  # b4: not five recessive? step over the JMP",
                  f"JMP {p}s [3]  # b5 to b8: five recessive: the stuff bit on b9",
                  "SKIP_NORUN 5, 0  # b5: not five dominant? step over the JMP",
                  f"JMP {p}s [2]  # b6 to b8: five dominant",
                  f"JMP {p}e [1]  # b6 to b7: no run: the REPEAT on b8",
                  f"{p}s: SHIFT_IN 0 [6]  # b9 to b15: the stuff bit into the raw history, not the CRC, no PUSH",
                  f"{p}e: REPEAT {count}, {p}  # " + ("the SOF to bit 31" if count == 32 else "bits 32 to 41, the CRC's last")]
    lines += ["SHIFT_IN 0 [1]  # the CRC delimiter, sampled; the slot's edge two clocks on",
              "SET 0, 0 [7]  # the ACK slot: pulled dominant for the bit, whatever the CRC said",
              "SET 0, 1 [7]  # the ACK delimiter: let go",
              "gap: NOP [6]  # EOF and the intermission", "REPEAT 10, gap",
              "ACC_PUSH  # the CRC residue's low byte: 0 and 0 when the CRC matched", "ACC_PUSH  # its high byte; halted"]
    return out("can_rx_crc", RX_HEADER, lines)


if __name__ == "__main__":
    tx_unopposed()
    tx_arbitration(0x5A3)
    tx_arbitration(0x7FF)
    tx_arbitration(0x000)
    rx_crc()
