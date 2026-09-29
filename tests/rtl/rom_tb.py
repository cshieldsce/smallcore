"""cocotb test for rtl/rom.v: every (sel, addr) reads what the assembler
makes of the manifest's program for that slot, 0 past its end, and 0 for slot
0 and any slot the manifest does not name. Run through test_rom.py."""

from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from cpu import load_program  # model/cpu.py
from gen_rom import read_manifest  # tools/gen_rom.py

PROGRAMS = Path(__file__).resolve().parent.parent.parent / "programs"


@cocotb.test()
async def every_slot_and_address_matches_the_assembler(dut):
    slots = read_manifest()
    assert slots, "empty manifest"
    for sel in range(16):
        words = load_program(PROGRAMS / slots[sel]) if sel in slots else []
        for addr in range(256):
            dut.sel.value = sel
            dut.addr.value = addr
            await Timer(1, "ns")
            expected = words[addr] if addr < len(words) else 0
            assert int(dut.word.value) == expected, f"slot {sel} addr {addr}: {int(dut.word.value):#06x} != {expected:#06x}"
            assert int(dut.words.value) == len(words), f"slot {sel}: words {int(dut.words.value)} != {len(words)}"
