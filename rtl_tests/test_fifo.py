"""pytest entry point for rtl/fifo.v on its own. Same shape as test_core.py:
Verilator compiles the FIFO into build/rtl/fifo_<DEPTH>/, then cocotb runs every
@cocotb.test() in fifo_tb.py against it, once per DEPTH. 3 is there so the
wrap-at-LAST pointer logic is tested against a depth that is not a power of two.

    python -m pytest rtl_tests/test_fifo.py -v
"""

from pathlib import Path

import pytest
from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("depth", [4, 3])
def test_fifo(depth):
    build_dir = ROOT / "build" / "rtl" / f"fifo_{depth}"
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "fifo.v"],
        hdl_toplevel="fifo",
        parameters={"DEPTH": depth},
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="fifo",
        test_module="fifo_tb",
        build_dir=build_dir,
        extra_env={"FIFO_DEPTH": str(depth)},  # fifo_tb.py sizes its tests from this
    )
