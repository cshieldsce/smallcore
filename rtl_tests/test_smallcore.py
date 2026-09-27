"""pytest entry point for rtl/smallcore.v, the chip: host register block,
program ROM and top (the core with its FIFOs). Verilator compiles the six
files into build/rtl/smallcore/, cocotb runs smallcore_tb.py against it.

    python -m pytest rtl_tests/test_smallcore.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
BUILD_DIR = ROOT / "build" / "rtl" / "smallcore"


def test_smallcore():
    runner = get_runner("verilator")
    runner.build(
        sources=[RTL / f for f in ("smallcore.v", "host.v", "rom.v", "top.v", "core.v", "fifo.v")],
        hdl_toplevel="smallcore",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="smallcore",
        test_module="smallcore_tb",
        build_dir=BUILD_DIR,
    )
