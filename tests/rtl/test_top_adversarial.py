"""pytest entry point for the top-level adversarial sweep: the same Verilator
build of top.v as test_top.py, in build/rtl/top/, running every
@cocotb.test() in top_adversarial_tb.py against it.

    python -m pytest tests/rtl/test_top_adversarial.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_DIR = ROOT / "build" / "rtl" / "top"


def test_top_adversarial():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "top.v", ROOT / "rtl" / "core.v", ROOT / "rtl" / "fifo.v"],
        hdl_toplevel="top",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="top",
        test_module="top_adversarial_tb",
        build_dir=BUILD_DIR,
    )
