"""pytest entry point for rtl/fifo.v on its own. Same shape as test_core.py:
Verilator compiles the FIFO into build/rtl/fifo/, then cocotb runs every
@cocotb.test() in fifo_tb.py against it.

    python -m pytest rtl_tests/test_fifo.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build" / "rtl" / "fifo"


def test_fifo():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "fifo.v"],
        hdl_toplevel="fifo",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="fifo",
        test_module="fifo_tb",
    )
