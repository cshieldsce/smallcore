"""Simulate can_host_engine.v + rtl/smallcore.v in Vivado xsim and check the CAN frames
against the independent reference, fpga/pynq_z2/can_ref.py.

    python fpga/pynq_z2/sim/run_sim.py [--vivado <Vivado install dir>] [--limits]

The regression: for IDs 0x123, 0x5A3, 0x7FF and 0x000 with one data byte (the ROM CAN
programs are DLC 1), can_tx_crc unacked and acked, then can_rx_bytes and can_rx_crc
through transceiver loop delays of 0 to 3 clocks, each through the same bus model as
smallcore_pynq_can.v. --limits also prints where can_tx_crc stops working: its own
recessive must read back within a clock, and the ACK must arrive by the slot's
second clock (bringup_log items 8 and 10, the reason for 125 kbit/s on hardware).
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import can_ref as ref  # noqa: E402

RTL = ["smallcore.v", "host.v", "rom.v", "ram.v", "top.v", "core.v", "fifo.v"]
WORK = ROOT / "build" / "pynq_z2_can" / "sim"


def tool(vivado, name):
    return str(Path(vivado) / "bin" / (name + ".bat"))


def build(vivado):
    WORK.mkdir(parents=True, exist_ok=True)
    srcs = [str(ROOT / "rtl" / f) for f in RTL] + [str(HERE.parent / "can_host_engine.v"), str(HERE / "tb_can_engine.v")]
    subprocess.run([tool(vivado, "xvlog")] + srcs, cwd=WORK, check=True, capture_output=True, shell=False)
    subprocess.run([tool(vivado, "xelab"), "tb", "-s", "tb_sim", "-timescale", "1ns/1ps"], cwd=WORK, check=True,
                   capture_output=True)


def run(vivado, args):
    p = dict(a.split("=") for a in args)
    keys = ["mode", "slot", "tx_len", "rx_n", "ack_at", "delay", "limit"]
    p["mode"] = "1" if p.get("mode") == "rx" else "0"
    (WORK / "params.txt").write_text(" ".join(p.get(k, "0") for k in keys) + "\n")
    r = subprocess.run([tool(vivado, "xsim"), "tb_sim", "-R"], cwd=WORK, capture_output=True, text=True)
    results = [l[len("RESULT "):] for l in r.stdout.splitlines() if l.startswith("RESULT ")]
    if not results:
        print(r.stdout[-3000:], r.stderr[-2000:])
        raise SystemExit("xsim produced no RESULT lines")
    ctx = [int(c) for c in (WORK / "ctx.txt").read_text().strip()]
    bus = [int(c) for c in (WORK / "bus.txt").read_text().strip()]
    return results, ctx, bus


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
    return ok


def tx_case(vivado, ident, data, ack_at, delay):
    seq = ref.POLY + ref.tx_host_bytes(ident, data)
    (WORK / "tx.mem").write_text("\n".join(f"{b:02x}" for b in seq) + "\n")
    res, ctx, bus = run(vivado, ["mode=tx", "slot=13", f"tx_len={len(seq)}", f"ack_at={ack_at}", f"delay={delay}",
                                 "limit=2500"])
    acked = ack_at > 0
    print(f"TX id=0x{ident:03X} data={[hex(d) for d in data]} ack_at={ack_at} delay={delay}")
    for r in res:
        print("  ", r)
    want = ref.frame(ident, data, acked)
    got_bus, sof = ref.sample(bus, len(want))
    got_ctx, _ = ref.sample(ctx, len(want), sof=sof)
    f, errors = ref.destuff(got_bus)
    ok = True
    ok &= check("bus matches the reference frame bit for bit", got_bus == want,
                "" if got_bus == want else f"\n      want {''.join(map(str, want))}\n      got  {''.join(map(str, got_bus))}")
    ok &= check("decoded fields", f["id"] == ident and f["data"] == list(data) and not errors,
                f"id=0x{f['id']:03X} dlc={f['dlc']} data={[hex(d) for d in f['data']]} crc=0x{f['crc'] or 0:04X} {errors}")
    ok &= check("smallcore leaves the ACK slot recessive", got_ctx[len(want) - 9] == 1)
    ok &= check("bit timing: every edge on a bit boundary", ref.edge_phases(ctx, sof, len(want)) in ([], [0]),
                str(ref.edge_phases(ctx, sof, len(want))))
    halted = res[1].split("status=")[1][0] == "1"
    ok &= check("halted iff acked", halted == acked)
    return ok


def rx_case(vivado, slot, ident, data, delay):
    idle = [1] * 20
    bits = idle + ref.stuff(ref.stream(ident, data)) + [1, 1, 1] + [1] * 7 + [1] * 13
    (WORK / "rx.mem").write_text("\n".join(map(str, bits)) + "\n")
    seq = ref.POLY if slot == 14 else []
    if seq:
        (WORK / "tx.mem").write_text("\n".join(f"{b:02x}" for b in seq) + "\n")
    res, ctx, bus = run(vivado, ["mode=rx", f"slot={slot}", f"tx_len={len(seq)}", f"rx_n={len(bits)}",
                                 f"delay={delay}", f"limit={len(bits) * 8 + 200}"])
    print(f"RX slot {slot} id=0x{ident:03X} data={[hex(d) for d in data]} delay={delay}")
    for r in res:
        print("  ", r)
    rx = [int(x, 16) for x in res[-1].split()[1:]]
    s = ref.stream(ident, data)
    ok = True
    if slot == 15:
        padded = s + [0] * (-len(s) % 8)
        want = [int("".join(map(str, padded[i:i + 8])), 2) for i in range(0, len(padded), 8)]
        # the last byte holds the stream's last bits in its low end
        tail = len(s) % 8
        if tail:
            want[-1] = int("".join(map(str, s[-tail:])), 2)
        ok &= check("can_rx_bytes: destuffed stream", rx == want, f"want {[hex(w) for w in want]} got {[hex(r) for r in rx]}")
    else:
        ok &= check("can_rx_crc: one stream bit a byte", [b & 1 for b in rx[:len(s)]] == s)
        ok &= check("can_rx_crc: CRC residue 0, 0", rx[len(s):] == [0, 0], str(rx[len(s):]))
    want_bus = ref.frame(ident, data, True)
    got_bus, sof = ref.sample(bus, len(want_bus))
    ok &= check("smallcore ACKs: the bus dominant in the ACK slot", got_bus[len(want_bus) - 9] == 0)
    return ok


def default_vivado():
    for d in ("C:/Xilinx/Vivado/2023.2", "C:/AMDDesignTools/2026.1/Vivado"):
        if (Path(d) / "bin" / "xsim.bat").exists():
            return d
    return "C:/Xilinx/Vivado/2023.2"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vivado", default=default_vivado())
    ap.add_argument("--limits", action="store_true")
    a = ap.parse_args()
    build(a.vivado)
    ok = True
    for ident in (0x123, 0x5A3, 0x7FF, 0x000):
        slot = len(ref.frame(ident, [0x5A], True)) - 9
        ok &= tx_case(a.vivado, ident, [0x5A], ack_at=0, delay=0)
        ok &= tx_case(a.vivado, ident, [0x5A], ack_at=8 * slot, delay=0)  # the ACK from the slot's first clock
        for delay in range(4):
            ok &= rx_case(a.vivado, 15, ident, [0x5A], delay)
            ok &= rx_case(a.vivado, 14, ident, [0x5A], delay)
    if a.limits:
        import contextlib
        import io
        slot = len(ref.frame(0x123, [0x5A], True)) - 9
        for delay in range(3):
            with contextlib.redirect_stdout(io.StringIO()):
                r = tx_case(a.vivado, 0x123, [0x5A], ack_at=8 * slot, delay=delay)
            print(f"LIMIT can_tx_crc, loop delay {delay} clocks: {'PASS' if r else 'FAIL'}")
        for late in range(3):
            with contextlib.redirect_stdout(io.StringIO()):
                r = tx_case(a.vivado, 0x123, [0x5A], ack_at=8 * slot + late, delay=0)
            print(f"LIMIT can_tx_crc, ACK {late} clocks late: {'PASS' if r else 'FAIL'}")
    print("ALL PASS" if ok else "FAILURES")
    sys.exit(0 if ok else 1)
