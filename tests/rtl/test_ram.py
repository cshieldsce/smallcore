"""pytest entry point for rtl/ram.v, the program RAM. Verilator builds ram.v
alone into build/rtl/ram/, cocotb runs ram_tb.py against it.

    python -m pytest tests/rtl/test_ram.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_DIR = ROOT / "build" / "rtl" / "ram"


def test_ram():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "ram.v"],
        hdl_toplevel="ram",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="ram",
        test_module="ram_tb",
        build_dir=BUILD_DIR,
    )
