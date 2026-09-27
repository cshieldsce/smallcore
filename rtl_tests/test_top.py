"""pytest entry point for rtl/top.v, the core wired to its TX FIFO. Same shape
as test_core.py: Verilator compiles top.v with core.v and fifo.v under it into
build/rtl/top/, then cocotb runs every @cocotb.test() in top_tb.py against it.

    python -m pytest rtl_tests/test_top.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build" / "rtl" / "top"


def test_top():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "top.v", ROOT / "rtl" / "core.v", ROOT / "rtl" / "fifo.v"],
        hdl_toplevel="top",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="top",
        test_module="top_tb",
        build_dir=BUILD_DIR,
    )
