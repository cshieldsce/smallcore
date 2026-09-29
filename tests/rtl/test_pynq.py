"""pytest entry point for fpga/pynq_z2/smallcore_pynq.v, the PYNQ-Z2 board
wrapper around rtl/smallcore.v. Verilator compiles it with the six RTL files
into build/rtl/pynq/, DEBOUNCE_BITS shrunk to 3 so a button press is short,
and cocotb runs pynq_tb.py against it.

    python -m pytest tests/rtl/test_pynq.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent.parent
RTL = ROOT / "rtl"
BUILD_DIR = ROOT / "build" / "rtl" / "pynq"


def test_pynq():
    runner = get_runner("verilator")
    runner.build(
        sources=[ROOT / "fpga" / "pynq_z2" / "smallcore_pynq.v"]
        + [RTL / f for f in ("smallcore.v", "host.v", "rom.v", "top.v", "core.v", "fifo.v")],
        hdl_toplevel="smallcore_pynq",
        build_dir=BUILD_DIR,
        parameters={"DEBOUNCE_BITS": 3},
        build_args=["--pins-inout-enables"],  # ja becomes the input side, ja__out/ja__en what the design drives
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="smallcore_pynq",
        test_module="pynq_tb",
        build_dir=BUILD_DIR,
    )
