"""Decode the PYNQ-Z2 CAN ILA captures with the independent reference, can_ref.py.

    python fpga/pynq_z2/can_decode.py tx  <core.csv> <id> <data...>   [--loop loop.csv] [--div N]
    python fpga/pynq_z2/can_decode.py bus <core.csv>                  [--loop loop.csv] [--div N]

core.csv is ila_can (8 MHz, --div samples a core clock): CTX is what smallcore drives, CRX the bus as
the transceiver reports it. loop.csv is ila_loop (125 MHz): the transceiver's
loop delay, CTX edge to CRX edge.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import can_ref as ref  # noqa: E402


def column(path, prefix):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    col = next(i for i, h in enumerate(rows[0]) if h.startswith(prefix))
    return [int(r[col], 16) for r in rows[2:] if r]


def show(label, bits):
    print(f"  {label:<5}{''.join(map(str, bits))}")


def report(name, trace, sof, want=None, k=1):
    n = len(want) if want else 160
    bits, _ = ref.sample(trace, n, sof=sof, per_clock=k)
    f, errors = ref.destuff(bits)
    print(f"{name}: SOF at clock {sof}")
    if want:
        show("want", want)
    show("got", bits[: f["bus_bits"] + 10])
    print(f"  id=0x{f['id']:03X} rtr={f['rtr']} ide={f['ide']} r0={f['r0']} dlc={f['dlc']} "
          f"data={[hex(d) for d in f['data']]} crc=0x{(f['crc'] or 0):04X} crc_ok={f['crc_ok']}")
    print(f"  crc_delim={f['crc_delim']} ack={f['ack']} ack_delim={f['ack_delim']} eof={''.join(map(str, f['eof']))}")
    print(f"  edge phases (clock mod 8 from SOF): {ref.edge_phases(trace, sof, f['bus_bits'] + 10, k)} (samples; {k} a core clock)")
    print(f"  errors: {errors or 'none'}")
    return f, errors, bits


def loop_delay(path, div):
    ctx, crx = column(path, "ctx_f"), column(path, "crx_f")
    out = []
    for i in range(1, len(ctx)):
        if ctx[i] != ctx[i - 1]:
            j = next((k for k in range(i, min(len(crx), i + 200)) if crx[k] == ctx[i] and crx[k - 1] != ctx[i]), None)
            if j is not None:
                out.append((("fall" if ctx[i] == 0 else "rise"), (j - i) * 8))
    falls = [d for e, d in out if e == "fall"]
    rises = [d for e, d in out if e == "rise"]
    clock_ns = 125 * div
    print(f"loop delay CTX->CRX at 8 ns resolution ({len(out)} edges): "
          f"dominant {min(falls, default=0)}..{max(falls, default=0)} ns, "
          f"recessive {min(rises, default=0)}..{max(rises, default=0)} ns; core clock {clock_ns} ns")
    return falls, rises


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["tx", "bus"])
    ap.add_argument("core")
    ap.add_argument("frame", nargs="*")
    ap.add_argument("--loop")
    ap.add_argument("--div", type=int, default=1)
    a = ap.parse_args()
    ctx, crx = column(a.core, "can_ctx"), column(a.core, "crx_s")
    if a.mode == "tx":
        ident, data = int(a.frame[0], 16), [int(x, 16) for x in a.frame[1:]]
        sof = next(i for i in range(1, len(ctx)) if ctx[i - 1] == 1 and ctx[i] == 0)
        print(f"reference: id=0x{ident:03X} data={[hex(d) for d in data]} CRC-15 0x{ref.crc15(ref.stream(ident, data)[:-15]):04X}")
        f, errors, bits = report("CTX (smallcore drives)", ctx, sof, ref.frame(ident, data, acked=False), a.div)
        want = ref.frame(ident, data, acked=False)
        print(f"  CTX == reference (ACK slot left recessive): {bits == want}")
        crx_sof = next(i for i in range(1, len(crx)) if crx[i - 1] == 1 and crx[i] == 0)
        report("CRX (the bus)", crx, crx_sof, None, a.div)
    else:
        sof = next(i for i in range(1, len(crx)) if crx[i - 1] == 1 and crx[i] == 0)
        report("CRX (the bus)", crx, sof, None, a.div)
    if a.loop:
        loop_delay(a.loop, a.div)
