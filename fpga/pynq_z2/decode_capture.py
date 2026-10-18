"""Decodes the SPI frame in an ILA capture from ila_capture.tcl.

    python fpga/pynq_z2/decode_capture.py [build/pynq_z2_ila/capture.csv]

Samples MOSI and MISO on each rising SCLK edge while CS is low, from the pads as
read back (ja_IBUF), and prints the bytes. Through the PMOD jumper MISO should
match MOSI; MISO stuck at 0xFF means pin 4 is floating, so the jumper is not
joining pin 1 to pin 4.
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOSI, SCLK, CS, MISO = 0, 1, 2, 3


def pads(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    col = next(i for i, name in enumerate(rows[0]) if name.startswith("ja_IBUF"))
    # row 1 is the radix line; the pads are one hex digit
    return [int(r[col], 16) for r in rows[2:] if r]


def decode(samples, msb_first=True):
    frames, mosi, miso = [], [], []
    if not samples:
        return frames
    prev = samples[0]
    for s in samples[1:]:
        bit = lambda v, n: (v >> n) & 1
        if bit(prev, CS) == 0 and bit(s, CS) == 1:
            frames.append((mosi, miso))
            mosi, miso = [], []
        elif bit(s, CS) == 0 and bit(prev, SCLK) == 0 and bit(s, SCLK) == 1:
            mosi.append(bit(s, MOSI))
            miso.append(bit(s, MISO))
        prev = s
    return [(to_byte(o, msb_first), to_byte(i, msb_first), len(o)) for o, i in frames]


def to_byte(bits, msb_first):
    if not msb_first:
        bits = bits[::-1]
    return sum(b << (len(bits) - 1 - n) for n, b in enumerate(bits))


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "pynq_z2_ila" / "capture.csv"
    frames = decode(pads(path))
    if not frames:
        print("no complete frame (CS low then high) in the capture")
    for n, (mosi, miso, bits) in enumerate(frames):
        print(f"frame {n}: {bits} bits  MOSI 0x{mosi:02X}  MISO 0x{miso:02X}"
              + ("" if mosi == miso else "  <- MISO differs: check the pin 1 to pin 4 jumper"))
