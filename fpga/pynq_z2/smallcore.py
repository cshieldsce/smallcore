#!/usr/bin/env python3
"""SmallCore from the PYNQ-Z2's ARM: a driver for the AXI bridge,
fpga/pynq_z2/axi_host.v, and a command line on top of it.

    sc = SmallCore(DevMem())         # or SmallCore.open()
    sc.load("programs/spi/spi_duplex_msb.asm")
    sc.run()
    sc.write(0x96)
    sc.status()                      # Status(halted=True, tx_full=False, rx_empty=False)
    sc.read()                        # 0x96 with the PMOD jumper from pin 1 to pin 4

    $ smallcore overlay build/pynq_z2_axi/overlay/smallcore.bit
    $ smallcore load programs/spi/spi_duplex_msb.asm
    $ smallcore tx 96
    $ smallcore rx
    96

Every method is a few register accesses through `regs`, anything with
read(offset) and write(offset, value): DevMem on the board, the cocotb
bench's AXI master in simulation (tests/rtl/pynq_axi_tb.py), so the code the
bench proves is the code the board runs. The bridge keeps SmallCore's host
protocol as it is: each CMD write is one strobe on the chip's host bus.
"""

import argparse
import mmap
import os
import struct
import sys
import time
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = 0x43C00000  # M_AXI_GP0 window, as fpga/pynq_z2/create_project_axi.tcl assigns it
SPAN = 0x1000

# axi_host.v's registers
ID, CTRL, CLKDIV, CMD, LAST, PADS = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14
PEEK = 0x20  # + 4 * host address
ID_VALUE = 0x534D4331  # "SMC1"

# host.v's registers, the chip's own
TX_DATA, RX_DATA, STATUS, CONTROL = 0, 1, 2, 3
RUN_RAM, LOAD_RAM = 0x10, 0x20  # CONTROL values besides a ROM slot 0..15
RAM_WORDS = 256
WE, RE = 1 << 16, 1 << 17


class Status(NamedTuple):
    halted: bool
    tx_full: bool
    rx_empty: bool

    @classmethod
    def of(cls, value):
        return cls(bool(value & 4), bool(value & 2), bool(value & 1))


class Pads(NamedTuple):
    gpio_in: int  # the pad levels, synchronized
    gpio_oe: int
    gpio_out: int


class DevMem:
    """The bridge's registers through /dev/mem (root, or pynq's own MMIO)."""

    def __init__(self, base=BASE, span=SPAN):
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        try:
            self.mem = mmap.mmap(fd, span, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        finally:
            os.close(fd)

    def read(self, offset):
        return struct.unpack_from("<I", self.mem, offset)[0]

    def write(self, offset, value):
        struct.pack_into("<I", self.mem, offset, value & 0xFFFFFFFF)


def assemble_file(path):
    """A .asm file through model/cpu.py's assembler, or a .hex file of one
    16-bit word per line, as instruction words."""
    path = Path(path)
    if path.suffix == ".hex":
        return [int(line.split("#")[0], 16) for line in path.read_text().splitlines() if line.split("#")[0].strip()]
    sys.path.insert(0, str(ROOT / "model"))
    from cpu import load_program  # noqa: E402  needs pyyaml

    return load_program(path)


class Timeout(Exception):
    pass


class SmallCore:
    def __init__(self, regs, timeout=1.0):
        self.regs = regs
        self.timeout = timeout  # seconds a wait on STATUS may take

    @classmethod
    def open(cls, base=BASE, **kw):
        return cls(DevMem(base), **kw)

    # --- the bridge ---------------------------------------------------------------------

    def id(self):
        return self.regs.read(ID)

    def check(self):
        found = self.id()
        if found != ID_VALUE:
            raise RuntimeError(f"no SmallCore bridge: ID reads {found:#010x}, not {ID_VALUE:#010x}; is the overlay loaded?")

    def reset(self):
        """Hard reset: the core, both FIFOs, slot 0 and ROM mode; a fresh chip sits halted."""
        self.regs.write(CTRL, 1)
        self._until(lambda: self.regs.read(CTRL) == 0, "reset")

    @property
    def clkdiv(self):
        """aclk cycles per core clock: 100 MHz / clkdiv is the core clock."""
        return self.regs.read(CLKDIV)

    @clkdiv.setter
    def clkdiv(self, n):
        self.regs.write(CLKDIV, n)

    def pads(self):
        v = self.regs.read(PADS)
        return Pads((v >> 8) & 0xF, (v >> 4) & 0xF, v & 0xF)

    # --- the chip's host bus ------------------------------------------------------------

    def strobe_write(self, addr, data):
        """One write strobe on the host bus: what a button or a pin used to do."""
        self.regs.write(CMD, WE | (addr & 3) << 8 | (data & 0xFF))

    def strobe_read(self, addr):
        """One read strobe; returns host_rdata as the strobe rose."""
        self.regs.write(CMD, RE | (addr & 3) << 8)
        return self.regs.read(LAST)

    def peek(self, addr):
        """host_rdata at `addr`, no strobe."""
        return self.regs.read(PEEK + 4 * (addr & 3))

    def status(self):
        return Status.of(self.peek(STATUS))

    def control(self):
        return self.peek(CONTROL)

    def select(self, slot):
        """Run ROM program `slot`, 1..15 (0 is none): the core restarts at pc 0, the FIFOs keep their bytes."""
        if not 0 <= slot <= 15:
            raise ValueError(f"slot {slot} outside 0..15")
        self.strobe_write(CONTROL, slot)

    def load(self, program):
        """Upload a program to the RAM: a path (.asm or .hex) or a list of
        16-bit words. The core sits halted in load mode until run()."""
        words = assemble_file(program) if isinstance(program, (str, Path)) else list(program)
        if not 1 <= len(words) <= RAM_WORDS:
            raise ValueError(f"{len(words)} words: the RAM holds 1..{RAM_WORDS}")
        self.strobe_write(CONTROL, LOAD_RAM)
        for word in words:
            self.strobe_write(TX_DATA, word & 0xFF)
            self.strobe_write(TX_DATA, word >> 8)
        return words

    def run(self):
        """Run the program in RAM from pc 0; again restarts it."""
        self.strobe_write(CONTROL, RUN_RAM)

    def write(self, byte):
        """Queue a byte in the TX FIFO, waiting while it is full."""
        self._until(lambda: not self.status().tx_full, "TX FIFO full")
        self.strobe_write(TX_DATA, byte)

    def read(self):
        """Pop a byte from the RX FIFO, waiting while it is empty."""
        self._until(lambda: not self.status().rx_empty, "RX FIFO empty")
        return self.strobe_read(RX_DATA)

    def wait_halted(self):
        self._until(lambda: self.status().halted, "still running")

    def _until(self, ready, what):
        end = time.monotonic() + self.timeout
        while not ready():
            if time.monotonic() > end:
                raise Timeout(f"{what} after {self.timeout} s")


# --- the command line ---------------------------------------------------------------------


def byte(text):
    """A byte as written on the command line: hex, with or without 0x."""
    value = int(text, 16)
    if not 0 <= value <= 0xFF:
        raise argparse.ArgumentTypeError(f"{text} is not a byte")
    return value


def main(argv=None):
    p = argparse.ArgumentParser(prog="smallcore", description="SmallCore on the PYNQ-Z2, from Linux through the AXI bridge.")
    p.add_argument("--base", type=lambda s: int(s, 0), default=BASE, help=f"bridge base address (default {BASE:#x})")
    p.add_argument("--timeout", type=float, default=1.0, help="seconds to wait on a FIFO or the halt")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("overlay", help="load the bitstream with pynq (sets FCLK0 from the .hwh)").add_argument("bit")
    sub.add_parser("id", help="the bridge's ID register")
    sub.add_parser("reset", help="hard reset: core, FIFOs, slot 0")
    sub.add_parser("status", help="STATUS and CONTROL")
    sub.add_parser("pads", help="gpio_in, gpio_oe, gpio_out")
    sub.add_parser("clkdiv", help="read or set aclk cycles per core clock").add_argument("n", nargs="?", type=int)
    sub.add_parser("select", help="run a ROM slot").add_argument("slot", type=int)
    load = sub.add_parser("load", help="upload a program to RAM and run it")
    load.add_argument("file")
    load.add_argument("--no-run", action="store_true", help="leave the core in load mode")
    sub.add_parser("run", help="restart the program in RAM")
    sub.add_parser("tx", help="queue bytes, hex").add_argument("bytes", nargs="+", type=byte)
    rx = sub.add_parser("rx", help="pop bytes, printed in hex")
    rx.add_argument("-n", type=int, default=1)
    sub.add_parser("wait", help="wait for the halt")
    a = p.parse_args(argv)

    if a.cmd == "overlay":
        from pynq import Overlay  # the PYNQ image's library: programs the PL and sets the clocks

        Overlay(a.bit)
        SmallCore.open(a.base).check()
        print("loaded")
        return 0

    sc = SmallCore.open(a.base, timeout=a.timeout)
    sc.check()
    if a.cmd == "id":
        print(f"{sc.id():#010x}")
    elif a.cmd == "reset":
        sc.reset()
    elif a.cmd == "status":
        s = sc.status()
        print(f"halted={int(s.halted)} tx_full={int(s.tx_full)} rx_empty={int(s.rx_empty)} control={sc.control():#04x}")
    elif a.cmd == "pads":
        pads = sc.pads()
        print(f"in={pads.gpio_in:04b} oe={pads.gpio_oe:04b} out={pads.gpio_out:04b}")
    elif a.cmd == "clkdiv":
        if a.n is not None:
            sc.clkdiv = a.n
        print(sc.clkdiv)
    elif a.cmd == "select":
        sc.select(a.slot)
    elif a.cmd == "load":
        words = sc.load(a.file)
        if not a.no_run:
            sc.run()
        print(f"{len(words)} words")
    elif a.cmd == "run":
        sc.run()
    elif a.cmd == "tx":
        for b in a.bytes:
            sc.write(b)
    elif a.cmd == "rx":
        for _ in range(a.n):
            print(f"{sc.read():02x}")
    elif a.cmd == "wait":
        sc.wait_halted()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Timeout, RuntimeError, ValueError) as e:
        print(f"smallcore: {e}", file=sys.stderr)
        sys.exit(1)
