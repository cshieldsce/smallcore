"""pytest entry point for fpga/pynq_z2/smallcore_axi.v: rtl/smallcore.v behind
the AXI4-Lite bridge, axi_host.v, on a gated core clock. Verilator compiles
it with the seven RTL files into build/rtl/pynq_axi/ and cocotb runs
pynq_axi_tb.py, whose tests call the board's own driver,
fpga/pynq_z2/smallcore.py, through an AXI master in the bench.

    python -m pytest tests/rtl/test_pynq_axi.py -v
"""

from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parent.parent.parent
RTL = ROOT / "rtl"
FPGA = ROOT / "fpga" / "pynq_z2"
BUILD_DIR = ROOT / "build" / "rtl" / "pynq_axi"


def test_pynq_axi():
    runner = get_runner("verilator")
    runner.build(
        sources=[FPGA / "smallcore_axi.v", FPGA / "axi_host.v"]
        + [RTL / f for f in ("smallcore.v", "host.v", "rom.v", "ram.v", "top.v", "core.v", "fifo.v")],
        hdl_toplevel="smallcore_axi",
        build_dir=BUILD_DIR,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="smallcore_axi",
        test_module="pynq_axi_tb",
        build_dir=BUILD_DIR,
    )
