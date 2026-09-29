"""pytest entry point for rtl/host.v alone, the host register block. Verilator
builds host.v into build/rtl/host/, cocotb runs host_tb.py against it.

    python -m pytest tests/rtl/test_host.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_DIR = ROOT / "build" / "rtl" / "host"


def test_host():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "host.v"],
        hdl_toplevel="host",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="host",
        test_module="host_tb",
        build_dir=BUILD_DIR,
    )
