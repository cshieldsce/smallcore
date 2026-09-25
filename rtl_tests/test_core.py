"""pytest entry point for the RTL benches.

pytest runs this file; it does not simulate anything itself. It asks cocotb's
runner to (1) have Verilator compile rtl/core.v into a C++ simulator binary in
build/rtl/, then (2) launch that binary with cocotb loaded, which imports
core_tb.py and runs every @cocotb.test() in it against the live design.

The cocotb tests run in a separate process (the simulator's), so a failure
there comes back here as one failed pytest test, with the cocotb log above it.

    python -m pytest rtl_tests -v          # or: make test-rtl
    WAVES=1 python -m pytest rtl_tests     # also writes build/rtl/dump.vcd
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build" / "rtl"


def test_core():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "rtl" / "core.v"],
        hdl_toplevel="core",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),  # core.v has no `timescale; the clock period is in ns
    )
    runner.test(
        hdl_toplevel="core",
        test_module="core_tb",  # rtl_tests/core_tb.py, found on the PYTHONPATH pytest set up
    )
