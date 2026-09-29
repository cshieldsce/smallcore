"""pytest entry point for rtl/rom.v, the generated program ROM. Verilator
builds rom.v alone into build/rtl/rom/, cocotb runs rom_tb.py against it.

    python -m pytest tests/rtl/test_rom.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_DIR = ROOT / "build" / "rtl" / "rom"


def test_rom():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "rom.v"],
        hdl_toplevel="rom",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="rom",
        test_module="rom_tb",
        build_dir=BUILD_DIR,
    )
