"""Simulate the ARM host path below the AXI clock converter in Vivado xsim: AXI4-Lite ->
smallcore_axi.v -> host_engine -> rtl/smallcore.v -> smallcore_pads.v (tb_axi_host.v), with
the registers used as the ARM driver uses them. The CAN frames are checked against the
independent reference, fpga/pynq_z2/can_ref.py, as run_sim.py does.

    python fpga/pynq_z2/sim/run_axi_sim.py [--vivado <Vivado install dir>]

Cases: the register map and its flags; SPI from ROM slot 8 on PMOD B through the jumper;
spi_duplex_msb loaded into RAM over TX_DATA and run; CAN TX (slot 13, acked) and CAN RX
(slot 15) and CAN RX with the CRC checked by SmallCore (slot 14) on PMOD A for IDs 0x123,
0x5A3, 0x7FF and 0x000 with data 0x5A; and experiments/can_stress/can_tx_crc_pin1.asm (6A with
the CRC from gpio_in 1, PMOD A pin 3 jumpered to CTX) loaded into RAM and run, through a
transceiver loop of 0 to 2 clocks. --limits also prints how slot 13 and the RAM variant do
through loops of 0 to 3 clocks, and for the ACK sampled on clocks 4, 5 and 6 of the slot
(can_tx_crc_pin1{,_ack5,_ack6}.asm) the latest ACK still taken.
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(HERE))
import can_ref as ref  # noqa: E402
from cpu import assemble  # noqa: E402
from run_sim import RTL, check, default_vivado, tool  # noqa: E402

WORK = ROOT / "build" / "pynq_z2_axi" / "sim_axi"
SRCS = ["smallcore_axi.v", "can_host_engine.v", "smallcore_pads.v"]


def build(vivado):
    WORK.mkdir(parents=True, exist_ok=True)
    srcs = ([str(ROOT / "rtl" / f) for f in RTL] + [str(HERE.parent / f) for f in SRCS]
            + [str(HERE / "tb_axi_host.v")])
    subprocess.run([tool(vivado, "xvlog")] + srcs, cwd=WORK, check=True, capture_output=True)
    subprocess.run([tool(vivado, "xelab"), "tb", "-s", "tb_axi", "-timescale", "1ns/1ps"], cwd=WORK,
                   check=True, capture_output=True)


def run(vivado, mode, n=0, rx_n=0, ack_at=0, limit=0, tx=(), rx_bits=(), prog=(), delay=0):
    (WORK / "params.txt").write_text(f"{mode} {n} {rx_n} {ack_at} {limit} {delay}\n")
    (WORK / "tx.mem").write_text("\n".join(f"{b:02x}" for b in tx) + "\n")
    (WORK / "rx.mem").write_text("\n".join(map(str, rx_bits)) + "\n")
    (WORK / "prog.mem").write_text("\n".join(f"{w:04x}" for w in prog) + "\n")
    r = subprocess.run([tool(vivado, "xsim"), "tb_axi", "-R"], cwd=WORK, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith(("PASS", "FAIL", "RESULT"))]
    if not lines or not lines[-1].startswith("RESULT"):
        print(r.stdout[-3000:], r.stderr[-2000:])
        raise SystemExit("xsim produced no RESULT")
    for l in lines:
        if l.startswith("FAIL"):
            print("  " + l)
    results = {}
    for l in lines:
        if l.startswith("RESULT "):
            key, _, rest = l[len("RESULT "):].partition(" ")
            results.setdefault(key, []).append(rest)
    passes = sum(l.startswith("PASS") for l in lines)
    ok = lines[-1] == "RESULT PASS"
    ctx = [int(c) for c in (WORK / "ctx.txt").read_text().strip()] if mode in (3, 4, 6) else []
    bus = [int(c) for c in (WORK / "bus.txt").read_text().strip()] if mode in (3, 4, 6) else []
    return ok, passes, results, ctx, bus


def self_checked(name, ok, passes):
    return check(f"{name} ({passes} register-level checks)", ok)


def can_tx(vivado, ident, data):
    seq = ref.POLY + ref.tx_host_bytes(ident, data)
    slot = len(ref.frame(ident, data, True)) - 9
    ok, passes, res, ctx, bus = run(vivado, 3, n=len(seq), ack_at=8 * slot, limit=2500, tx=seq)
    print(f"CAN TX id=0x{ident:03X} data={[hex(d) for d in data]} ({len(seq)} host bytes)")
    want = ref.frame(ident, data, True)
    got_bus, sof = ref.sample(bus, len(want))
    got_ctx, _ = ref.sample(ctx, len(want), sof=sof)
    f, errors = ref.destuff(got_bus)
    ok &= self_checked("driver flow", ok, passes)
    ok &= check("prefill: TX_COMMITTED = 4 before RUN", res["committed"][0] == "before RUN 4", res["committed"][0])
    ok &= check("bus matches the reference frame bit for bit", got_bus == want,
                "" if got_bus == want else f"\n      want {''.join(map(str, want))}\n      got  {''.join(map(str, got_bus))}")
    ok &= check("decoded fields", f["id"] == ident and f["data"] == list(data) and not errors,
                f"id=0x{f['id']:03X} dlc={f['dlc']} crc=0x{f['crc'] or 0:04X} {errors}")
    ok &= check("smallcore leaves the ACK slot recessive", got_ctx[len(want) - 9] == 1)
    ok &= check("acked: halted", res["halted"][0] == "1")
    ok &= check(f"TX_COMMITTED = {len(seq)} after", res["committed"][1] == f"after {len(seq)}", res["committed"][1])
    print(f"     post-ACK byte over RX_DATA:{res['rx'][0]}")
    return ok


def can_tx_frame_checks(ident, data, ok, res, ctx, bus, acked=True):
    """The checks can_tx makes on a transmitted frame, for any way of running the transmitter; `acked`
    is the exit expected, the ACK taken (halted) or missed."""
    want = ref.frame(ident, data, True)
    got_bus, sof = ref.sample(bus, len(want))
    got_ctx, _ = ref.sample(ctx, len(want), sof=sof)
    f, errors = ref.destuff(got_bus)
    ok &= check("bus matches the reference frame bit for bit", got_bus == want,
                "" if got_bus == want else f"\n      want {''.join(map(str, want))}\n      got  {''.join(map(str, got_bus))}")
    ok &= check("CTX matches the reference up to the ACK slot", got_ctx[:len(want) - 9] == want[:len(want) - 9])
    ok &= check("decoded fields, CRC-15 and stuffing", f["id"] == ident and f["data"] == list(data) and not errors,
                f"id=0x{f['id']:03X} dlc={f['dlc']} crc=0x{f['crc'] or 0:04X} {errors}")
    ok &= check("smallcore leaves the ACK slot recessive", got_ctx[len(want) - 9] == 1)
    ok &= check("acked: halted" if acked else "ACK missed: not halted", res["halted"][0] == ("1" if acked else "0"))
    return ok


def variant_words(ack=4):
    """experiments/can_stress/can_tx_crc_pin1.asm, assembled: 6A with ACC_CRC on gpio_in 1; with `ack`
    5 or 6 the _ack5/_ack6 variant, the ACK sampled on that clock of the slot."""
    name = "can_tx_crc_pin1" + ("" if ack == 4 else f"_ack{ack}")
    return assemble((ROOT / "experiments" / "can_stress" / f"{name}.asm").read_text())


def can_tx_ram(vivado, ident, data, delay, words=None, quiet=False, ack_lag=0, acked=True):
    """The RAM-loaded variant transmitting through a loop of `delay` clocks, the other node ACKing
    `ack_lag` clocks into the slot (its own lag behind the bus; smallcore sees the ACK `delay` later)."""
    words = words or variant_words()
    seq = ref.POLY + ref.tx_host_bytes(ident, data)
    slot = len(ref.frame(ident, data, True)) - 9
    ok, passes, res, ctx, bus = run(vivado, 6, n=len(words), rx_n=len(seq), ack_at=8 * slot + ack_lag, limit=2500,
                                    tx=seq, prog=words, delay=delay)
    if not quiet:
        print(f"CAN TX from RAM, crc_pin 1 + jumper, id=0x{ident:03X} data={[hex(d) for d in data]}, "
              f"loop {delay} clocks, ACK {ack_lag} late")
    ok &= self_checked("driver flow", ok, passes)
    ok &= check(f"TX_COMMITTED = {len(seq)} after", res["committed"][0] == f"after {len(seq)}", res["committed"][0])
    return can_tx_frame_checks(ident, data, ok, res, ctx, bus, acked)


def can_tx_rom(vivado, ident, data, delay, ack_lag=0):
    """Slot 13 as can_tx runs it, through a loop of `delay` clocks: for --limits."""
    seq = ref.POLY + ref.tx_host_bytes(ident, data)
    slot = len(ref.frame(ident, data, True)) - 9
    ok, passes, res, ctx, bus = run(vivado, 3, n=len(seq), ack_at=8 * slot + ack_lag, limit=2500, tx=seq, delay=delay)
    return can_tx_frame_checks(ident, data, ok, res, ctx, bus)



def can_rx_crc(vivado, ident, data):
    idle = [1] * 20
    bits = idle + ref.stuff(ref.stream(ident, data)) + [1, 1, 1] + [1] * 7 + [1] * 13
    ok, passes, res, ctx, bus = run(vivado, 5, n=len(ref.POLY), rx_n=len(bits), limit=len(bits) * 8 + 400,
                                    rx_bits=bits, tx=ref.POLY)
    print(f"CAN RX slot 14 id=0x{ident:03X} data={[hex(d) for d in data]}")
    s = ref.stream(ident, data)
    got = [int(x, 16) for x in res["rx"][0].split()]
    ok &= self_checked("driver flow", ok, passes)
    ok &= check("can_rx_crc: one stream bit a byte", [b & 1 for b in got[:len(s)]] == s)
    ok &= check("can_rx_crc: CRC residue 0, 0", got[len(s):] == [0, 0], str(got[len(s):]))
    return ok


def can_rx(vivado, ident, data):
    idle = [1] * 20
    bits = idle + ref.stuff(ref.stream(ident, data)) + [1, 1, 1] + [1] * 7 + [1] * 13
    ok, passes, res, ctx, bus = run(vivado, 4, rx_n=len(bits), limit=len(bits) * 8 + 200, rx_bits=bits)
    print(f"CAN RX id=0x{ident:03X} data={[hex(d) for d in data]}")
    s = ref.stream(ident, data)
    padded = s + [0] * (-len(s) % 8)
    want = [int("".join(map(str, padded[i:i + 8])), 2) for i in range(0, len(padded), 8)]
    tail = len(s) % 8
    if tail:
        want[-1] = int("".join(map(str, s[-tail:])), 2)
    got = [int(x, 16) for x in res["rx"][0].split()]
    ok &= self_checked("driver flow", ok, passes)
    ok &= check("RX_DATA pops: the destuffed stream", got == want, f"want {[hex(w) for w in want]} got {[hex(g) for g in got]}")
    want_bus = ref.frame(ident, data, True)
    got_bus, _ = ref.sample(bus, len(want_bus))
    ok &= check("smallcore ACKs: the bus dominant in the ACK slot", got_bus[len(want_bus) - 9] == 0)
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vivado", default=default_vivado())
    ap.add_argument("--limits", action="store_true")
    a = ap.parse_args()
    build(a.vivado)
    ok = True

    r = run(a.vivado, 0)
    print("REGISTERS")
    ok &= self_checked("map, RAW, staging full/flush, TX_COMMITTED, flags", r[0], r[1])

    spi = [0x96, 0x3C, 0xA5, 0x00, 0xFF]
    r = run(a.vivado, 1, n=len(spi), tx=spi)
    print("SPI slot 8 on PMOD B: " + " ".join(r[2].get("spi", [])))
    ok &= self_checked(f"{len(spi)} bytes back through the jumper", r[0], r[1])

    words = assemble((ROOT / "programs" / "spi" / "spi_duplex_msb.asm").read_text())
    r = run(a.vivado, 2, n=len(words), rx_n=3, tx=[0x96, 0x3C, 0xA5], prog=words)
    print(f"RAM load: spi_duplex_msb, {len(words)} words, {2 * len(words)} bytes: " + " ".join(r[2].get("ram", [])))
    ok &= self_checked("load, run from RAM, 3 bytes back", r[0], r[1])

    for ident in (0x123, 0x5A3, 0x7FF, 0x000):
        ok &= can_tx(a.vivado, ident, [0x5A])
        ok &= can_rx(a.vivado, ident, [0x5A])
        ok &= can_rx_crc(a.vivado, ident, [0x5A])
    for ident, data in ((0x123, [0x5A]), (0x7FF, [0xFF]), (0x000, [0x00]), (0x5A3, [0xA5])):
        # the frame exact through a one-clock loop, where slot 13's CRC already fails; the ACK
        # sampled as 6A samples it is missed there (bringup_log item 10), recorded as found
        ok &= can_tx_ram(a.vivado, ident, data, 0)
        ok &= can_tx_ram(a.vivado, ident, data, 1, acked=False)
    if a.limits:
        import contextlib
        import io
        for delay in range(4):
            for lag in range(4):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rom = can_tx_rom(a.vivado, 0x123, [0x5A], delay, ack_lag=lag)
                    rom_log = out.getvalue()
                    out.truncate(0); out.seek(0)
                    ram = can_tx_ram(a.vivado, 0x123, [0x5A], delay, quiet=True, ack_lag=lag)
                    ram_log = out.getvalue()
                def verdict(passed, log):
                    if passed:
                        return "frame ok, acked"
                    frame_bad = "FAIL  bus matches" in log or "FAIL  decoded" in log
                    return "FRAME BAD" if frame_bad else "frame ok, ACK missed"
                print(f"LIMIT loop {delay}, ACK lag {lag}: slot 13: {verdict(rom, rom_log)}; "
                      f"RAM crc_pin 1: {verdict(ram, ram_log)}")
    if a.limits:
        # the latest ACK each sample clock takes: the other node's lag into the slot, 0..8 clocks
        for ack in (4, 5, 6):
            words = variant_words(ack)
            for delay in (0, 1):
                taken = []
                for lag in range(9):
                    with contextlib.redirect_stdout(io.StringIO()):
                        if can_tx_ram(a.vivado, 0x123, [0x5A], delay, words=words, quiet=True, ack_lag=lag):
                            taken.append(lag)
                late = max(taken) if taken else None
                print(f"ACK-LIMIT sample clock {ack}, loop {delay}: ACK taken at lags {taken}; latest "
                      f"{late}" + ("" if late is None else f" (lag + loop = {late + delay} clocks late)"))
    print("ALL PASS" if ok else "FAILURES")
    sys.exit(0 if ok else 1)
