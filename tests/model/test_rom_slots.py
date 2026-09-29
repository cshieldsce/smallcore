"""Slots 12..15, taken 2026-09-28 so the fixed ROM carries programs that use
what the architecture grew: REPEAT, the run test and the accumulator. A fixed
ROM is everything the chip can ever fetch, and synthesis keeps only the logic
those words reach, as it did with REPEAT while no ROM program used it.

Each ROM copy is the program its experiment tests, word for word: the SWD
read in REPEAT form (tests/model/test_repeat.py holds it to the 103-word wire), CAN
stage 6A and 6C (tests/model/test_can_combined.py), and the destuffing receiver on
the accumulator (tests/model/test_acc.py). And the coverage, pinned: every
instruction the ISA has is in the ROM but SKIP_RUN, which no program uses;
every CAN and SWD program says SKIP_NORUN."""

from pathlib import Path

import pytest

from cpu import decode, load_isa, load_program
from gen_rom import read_manifest

ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = ROOT / "programs"
ISA = load_isa()
SLOTS = {
    12: ("swd/swd_read_loop.asm", "experiments/repeat/swd_read_A.asm"),
    13: ("can/can_tx_crc.asm", "experiments/combined/can_tx_combined.asm"),
    14: ("can/can_rx_crc.asm", "experiments/combined/can_rx_crc.asm"),
    15: ("can/can_rx_bytes.asm", "experiments/acc/can_rx_bytes.asm"),
}


@pytest.mark.parametrize("slot", sorted(SLOTS))
def test_each_new_slot_is_its_experiments_program(slot):
    name, source = SLOTS[slot]
    assert read_manifest()[slot] == name
    assert load_program(PROGRAMS / name, ISA) == load_program(ROOT / source, ISA)


def test_the_rom_uses_every_instruction_but_skip_run():
    used = {decode(w, ISA).op for name in read_manifest().values() for w in load_program(PROGRAMS / name, ISA)}
    assert set(ISA["instructions"]) - used == {"SKIP_RUN"}
