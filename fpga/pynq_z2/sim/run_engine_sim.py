"""Simulate host_engine (can_host_engine.v) on its own interface, the one smallcore_axi.v
drives, with rtl/smallcore.v in Vivado xsim: tb_host_engine.v. The RAM-load case loads
programs/spi/spi_duplex_msb.asm, assembled here by model/cpu.py, and runs it through a
loopback jumper.

    python fpga/pynq_z2/sim/run_engine_sim.py [--vivado <Vivado install dir>]

The VIO interface, can_host_engine, has its own regression: run_sim.py.
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "model"))
from cpu import assemble  # noqa: E402

sys.path.insert(0, str(HERE))
from run_sim import RTL, default_vivado, tool  # noqa: E402

WORK = ROOT / "build" / "pynq_z2_can" / "sim_engine"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vivado", default=default_vivado())
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    words = assemble((ROOT / "programs" / "spi" / "spi_duplex_msb.asm").read_text())
    (WORK / "prog.mem").write_text("\n".join(f"{w:04x}" for w in words) + "\n")
    (WORK / "params.txt").write_text(f"{len(words)}\n")
    srcs = [str(ROOT / "rtl" / f) for f in RTL] + [str(HERE.parent / "can_host_engine.v"),
                                                   str(HERE / "tb_host_engine.v")]
    subprocess.run([tool(a.vivado, "xvlog")] + srcs, cwd=WORK, check=True, capture_output=True)
    subprocess.run([tool(a.vivado, "xelab"), "tb", "-s", "tb_engine", "-timescale", "1ns/1ps"], cwd=WORK,
                   check=True, capture_output=True)
    r = subprocess.run([tool(a.vivado, "xsim"), "tb_engine", "-R"], cwd=WORK, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith(("PASS", "FAIL", "RESULT"))]
    print("\n".join(lines) if lines else r.stdout[-3000:])
    ok = bool(lines) and lines[-1] == "RESULT PASS"
    sys.exit(0 if ok else 1)
