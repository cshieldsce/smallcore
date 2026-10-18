"""Independent Classical CAN 2.0A reference for the PYNQ-Z2 CAN bring-up.

Written from the frame format, not from the repository's model, so it can
check smallcore's waveforms without sharing a mistake with them:

    SOF, ID[10:0], RTR, IDE, r0, DLC[3:0], data, CRC-15 (0x4599) | stuffed
    CRC delimiter, ACK slot, ACK delimiter, EOF x7                | fixed form

Also the host bytes smallcore's programs take and give, and a bit-level
decoder for a bus or CTX trace sampled once per core clock.
"""

BIT = 8  # core clocks a bit in the CAN programs


def crc15(bits):
    crc = 0
    for b in bits:
        nxt = b ^ ((crc >> 14) & 1)
        crc = (crc << 1) & 0x7FFF
        if nxt:
            crc ^= 0x4599
    return crc


def bits_of(value, n):
    return [(value >> i) & 1 for i in range(n - 1, -1, -1)]


def stream(ident, data, rtr=0):
    """The stuffed region before stuffing, CRC included."""
    assert 0 <= ident < 0x800 and len(data) <= 8
    bits = [0] + bits_of(ident, 11) + [rtr, 0, 0] + bits_of(len(data), 4)
    for d in data:
        bits += bits_of(d, 8)
    return bits + bits_of(crc15(bits), 15)


def stuff(bits):
    out, last, run = [], None, 0
    for b in bits:
        out.append(b)
        run = run + 1 if b == last else 1
        last = b
        if run == 5:
            out.append(1 - b)
            last, run = 1 - b, 1
    return out


def frame(ident, data, acked):
    """The whole frame on the bus, SOF to the end of EOF."""
    return stuff(stream(ident, data)) + [1, 0 if acked else 1, 1] + [1] * 7


def tx_host_bytes(ident, data, rtr=0):
    """What can_tx_crc.asm takes per frame after the polynomial:
    {SOF, ID[10], ID[9], 00000}, ID[8:1], {ID[0], RTR, IDE, r0, DLC[3:0]}, data."""
    return [((ident >> 9) & 3) << 5, (ident >> 1) & 0xFF,
            ((ident & 1) << 7) | (rtr << 6) | len(data)] + list(data)


POLY = [0x32, 0x8B]


def sample(trace, n, phase=4, sof=None, per_clock=1):
    """n bits from a trace sampled `per_clock` times a core clock, from its first falling edge
    (the SOF), at core clock `phase` of each bit."""
    if sof is None:
        sof = next(i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0)
    step, at = BIT * per_clock, phase * per_clock
    return [trace[sof + step * k + at] for k in range(n) if sof + step * k + at < len(trace)], sof


def destuff(bits):
    """Decode a bus bit list from the SOF: returns (fields dict, errors list)."""
    out, errors, last, run, i = [], [], None, 0, 0
    while i < len(bits) and len(out) < 19:  # up to the DLC
        b = bits[i]; i += 1
        if run == 5:
            if b == last:
                errors.append(f"stuff error at bus bit {i - 1}")
            last, run = b, 1
            continue
        out.append(b)
        run = run + 1 if b == last else 1
        last = b
    dlc = int("".join(map(str, out[15:19])), 2) if len(out) >= 19 else 0
    need = 19 + 8 * min(dlc, 8) + 15
    while i < len(bits) and len(out) < need:
        b = bits[i]; i += 1
        if run == 5:
            if b == last:
                errors.append(f"stuff error at bus bit {i - 1}")
            last, run = b, 1
            continue
        out.append(b)
        run = run + 1 if b == last else 1
        last = b
    tail = bits[i:i + 10]
    f = {
        "sof": out[0] if out else None,
        "id": int("".join(map(str, out[1:12])), 2) if len(out) >= 12 else None,
        "rtr": out[12] if len(out) > 12 else None,
        "ide": out[13] if len(out) > 13 else None,
        "r0": out[14] if len(out) > 14 else None,
        "dlc": dlc,
        "data": [int("".join(map(str, out[19 + 8 * k:27 + 8 * k])), 2) for k in range(min(dlc, 8))],
        "crc": int("".join(map(str, out[need - 15:need])), 2) if len(out) >= need else None,
        "crc_ok": len(out) >= need and crc15(out[:need - 15]) == int("".join(map(str, out[need - 15:need])), 2),
        "crc_delim": tail[0] if len(tail) > 0 else None,
        "ack": tail[1] if len(tail) > 1 else None,
        "ack_delim": tail[2] if len(tail) > 2 else None,
        "eof": tail[3:10],
        "bus_bits": i,
    }
    if f["sof"] != 0: errors.append("SOF not dominant")
    if f["ide"] != 0 or f["r0"] != 0: errors.append("IDE/r0 not dominant")
    if not f["crc_ok"]: errors.append("CRC mismatch")
    if f["crc_delim"] != 1: errors.append("CRC delimiter not recessive")
    if f["ack_delim"] != 1: errors.append("ACK delimiter not recessive")
    if f["eof"] != [1] * 7: errors.append(f"EOF not 7 recessive: {f['eof']}")
    return f, errors


def edge_phases(trace, sof, nbits, per_clock=1):
    """Offsets in samples (mod a bit) of every edge in the frame: all 0 when every bit is BIT clocks."""
    step = BIT * per_clock
    return sorted({(i - sof) % step for i in range(sof + 1, min(len(trace), sof + step * nbits))
                   if trace[i] != trace[i - 1]})
