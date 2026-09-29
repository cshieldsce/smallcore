"""pytest entry point for the CAN stress programs on rtl/top.v: Verilator
builds top.v into build/rtl/can_stress/ (its own directory, so it does not
race test_top.py's build), then cocotb runs can_stress_tb.py against it.

    python -m pytest tests/rtl/test_can_stress.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_DIR = ROOT / "build" / "rtl" / "can_stress"


def test_can_stress():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "top.v", ROOT / "rtl" / "core.v", ROOT / "rtl" / "fifo.v"],
        hdl_toplevel="top",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="top",
        test_module="can_stress_tb",
        build_dir=BUILD_DIR,
    )
