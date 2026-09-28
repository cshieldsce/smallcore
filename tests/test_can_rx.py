"""CAN receive on the current ISA, staged as the transmitter was, no
candidate spliced in: the bench is a transmitter on the bus and the node
under test listens.

  RX1  synchronize on the SOF: WAIT for the bus to fall;
  RX2  the raw bits at fixed timing, eight clocks a bit, to the host as
       bytes, `can_rx.asm`;
  RX3  detect a stuff condition: the last five samples one level, stage 4's
       tree of SKIPs on the receive side;
  RX4  discard the stuff bit: sample it, since the raw history must hold it,
       but hand it on as nothing;
  RX5  recover the destuffed stream: on pins 2 and 3, the data bit and a
       "this slot is data" flag, `can_rx_destuff.asm`, which also counts the
       frame's data bits and pulls the ACK slot dominant; or through the RX
       FIFO one bit a byte, `can_rx_bits.asm`, which costs a ninth clock;
  RX6  assemble bytes and fields in the core: not on this ISA. The raw
       history the run test reads and the destuffed byte the host wants
       cannot share the one register, and carrying "a stuff bit went by, n
       bits ago, at this level" in the pc instead of a register means no
       REPEAT and every cell written out: the header alone is counted here
       and refused by the assembler.

Measured throughout: words and distinct words, the decision's cycles after
the sample, whether eight clocks a bit survives, and what state a receiver
needs at once."""

import pytest

from cpu import CPU, assemble, load_program
from test_can import BIT, GAP, IDENT, PROGRAMS, Bus, Glitch, bits_to_int, cells, frame_bits, frame_names, stuffed  # noqa: E402

RX = PROGRAMS / "can_rx.asm"
DESTUFF = PROGRAMS / "can_rx_destuff.asm"
BITS = PROGRAMS / "can_rx_bits.asm"
RX_SAMPLE = 6  # the clock of a bit whose level the receivers take: the sixth (75%), read by the SHIFT_IN on the seventh
RAW_BYTES = 6  # can_rx.asm receives 48 raw bits from the SOF and stops: it cannot know where a frame ends
DATA_PIN, VALID_PIN = 2, 3  # can_rx_destuff.asm's destuffed stream: the data bit, and 1 while the slot is a data bit
BITS_BIT = 9  # clocks a bit can_rx_bits.asm needs: the PUSH is the ninth
AT = 10  # the cycle the bench transmitter starts its frame
VECTORS = ((0x5A3, 0x5A), (0x7FF, 0xFF), (0x000, 0x00), (0x07C, 0x00), (0x555, 0xAA), (0x123, 0x01))


class Transmitter:
    """A bench transmitter on the bus: from the update call `at` it drives
    `bits` in turn, each for `bit` cycles, a 0 driven, a 1 let go, then lets
    go for good. `slot`, an index into `bits`, is the ACK slot: not driven,
    its level on its `sample`th clock kept as `acked` (True for dominant).
    `seen` is the bus on that clock of every bit it sent."""

    def __init__(self, bits, at=AT, bit=BIT, slot=None, sample=RX_SAMPLE):
        self.bits, self.at, self.bit, self.slot, self.sample = list(bits), at, bit, slot, sample
        self.i = -1
        self.acked = None
        self.seen = []

    def update(self, line):
        self.i += 1
        k, phase = divmod(self.i - self.at, self.bit)
        if 0 <= k < len(self.bits) and phase == self.sample:
            self.seen.append(line)
            if k == self.slot:
                self.acked = line == 0
        if 0 <= k < len(self.bits) and self.bits[k] == 0 and k != self.slot:
            return 0
        return None


def frame_on_the_bus(ident, data):
    """What a transmitter sends for a frame: the stuffed stream, the CRC
    delimiter, the ACK slot (recessive from the transmitter), the ACK
    delimiter, EOF and the intermission; and the slot's index."""
    bits = stuffed(frame_bits(ident, data)) + [1, 1, 1] + [1] * GAP
    return bits, len(bits) - GAP - 2


def stuff_positions(ident, data):
    """The indices on the bus, from the SOF, of the stuff bits in a frame."""
    stream = frame_bits(ident, data)
    out, level, count, k = [], None, 0, -1
    for bit in stream:
        k += 1
        level, count = (level, count + 1) if bit == level else (bit, 1)
        if count == 5:
            k += 1
            out.append(k)
            level, count = 1 - bit, 1
    return out


def run_rx(program, ident, data, bit=BIT, cycles=None, drain=True, host=None, glitch=None, cpu=None):
    """`program` listening on the bus with a Transmitter sending the frame
    from cycle AT, `bit` cycles a bit."""
    bits, slot = frame_on_the_bus(ident, data)
    tx = Transmitter(bits, AT, bit, slot)
    nodes = [tx] + ([glitch] if glitch else [])
    r = Bus(program, [], nodes, drain=drain, host=host, cpu=cpu).go(cycles or (AT + (len(bits) + 4) * bit + 40)).result()
    return r, tx


def raw_bytes(bits, n=RAW_BYTES):
    """The first 8n bus bits from the SOF as bytes, MSB first, the way can_rx.asm shifts them."""
    padded = bits + [1] * (8 * n - len(bits))
    return [bits_to_int(padded[8 * k : 8 * k + 8]) for k in range(n)]


def stream_from_pins(r, count, bit=BIT):
    """The destuffed stream as pins 2 and 3 show it: for each of `count` bus
    bits from the SOF, the pins at the sixth clock of the bit after, the
    slot's output settled; the data pin where the valid pin is 1, and the
    slots where it is 0, the stuff bits."""
    data, valid = r.cpu.pin_trace(DATA_PIN), r.cpu.pin_trace(VALID_PIN)
    out = [(data[AT + (k + 1) * bit + RX_SAMPLE - 1], valid[AT + (k + 1) * bit + RX_SAMPLE - 1]) for k in range(count)]
    return [d for d, v in out if v], [k for k, (d, v) in enumerate(out) if not v]


@pytest.fixture(params=VECTORS, ids=lambda v: f"{v[0]:03x}-{v[1]:02x}")
def vector(request):
    return request.param


# --- RX1, RX2: the SOF and the raw bits -------------------------------------------------


def test_the_bench_transmitter_puts_the_frame_on_the_bus():
    """The bench's transmitter alone on the bus with a core that only
    listens: the frame's bits from AT, each held BIT cycles, recessive
    before and after, the ACK slot let go, so it reads not acked; with a
    probe pulling the slot dominant on its sample clock it reads acked."""
    listen = CPU(assemble("CONFIG open_drain01, 1\n" + "NOP [31]\n" * 60), gpio_in=1)
    bits, slot = frame_on_the_bus(IDENT, [0x5A])
    r, tx = run_rx(None, IDENT, [0x5A], cpu=listen)
    assert r.line[:AT] == [1] * AT and cells(r.line, AT, len(bits)) == bits
    assert r.line[AT + len(bits) * BIT :] == [1] * len(r.line[AT + len(bits) * BIT :])
    assert tx.acked is False and tx.seen == bits
    listen = CPU(assemble("CONFIG open_drain01, 1\n" + "NOP [31]\n" * 60), gpio_in=1)
    r, tx = run_rx(None, IDENT, [0x5A], cpu=listen, glitch=Glitch(AT + slot * BIT + RX_SAMPLE - 1))
    assert tx.acked is True
    for ident, data in VECTORS:
        assert stuff_positions(ident, [data]) == [k for k, name in enumerate(frame_names(ident, [data])) if name == "stuff"]


def test_raw_bits_reach_the_host(vector):
    """can_rx.asm: the receiver waits for the SOF's edge and samples 48 bits
    at eight clocks a bit, the sixth clock of each, six bytes to the host,
    the SOF bit 7 of the first: the bus as it was, stuff bits and all; it
    never drives the bus; halted after the sixth byte, before the frame is
    over, since nothing tells it where the frame ends."""
    ident, data = vector
    bits, _ = frame_on_the_bus(ident, [data])
    r, tx = run_rx(RX, ident, [data])
    assert r.received == raw_bytes(bits)
    assert r.owned == [False] * len(r.owned), "listening: the pad never drives"
    assert r.cpu.halted and r.cpu.cycle == AT + RX_SAMPLE + RAW_BYTES * 8 * BIT, "halted on the REPEAT after the last byte's PUSH"
    assert not any(r.stalls[AT + 1 :])


def test_the_raw_receiver_samples_the_sixth_clock_of_the_bit():
    """A probe pulls the bus dominant for one cycle of ID[7], recessive, at
    each of its eight clocks: the host's first byte loses ID[7] exactly when
    the pulse is on the sixth."""
    bits, _ = frame_on_the_bus(IDENT, [0x5A])
    k = 4  # ID[7]: 0x5A3 = 101 1010 0011, ID[10:7] = 1011
    assert bits[k] == 1
    for p in range(BIT):
        r, _ = run_rx(RX, IDENT, [0x5A], glitch=Glitch(AT + k * BIT + p))
        hit = p == RX_SAMPLE - 1
        assert r.received[0] == raw_bytes(bits)[0] & ~(hit << (7 - k)), f"pulse on clock {p + 1}"


def test_the_raw_receiver_by_the_numbers():
    """RX2 measured: 13 words, 7 distinct: three of setup, a body of eight
    samples with the PUSH in the eighth, run six times; eight clocks a bit;
    one byte every 64 cycles to the host, 1 in the FIFO at most with a
    prompt host; no decision."""
    words = load_program(RX)
    assert (len(words), len(set(words))) == (13, 7)
    r, _ = run_rx(RX, IDENT, [0x5A])
    assert (r.rx_peak, len(r.received)) == (1, RAW_BYTES)
    pushes = [i for i, op in enumerate(r.issues) if op == "PUSH"]
    assert [b - a for a, b in zip(pushes, pushes[1:])] == [8 * BIT] * (RAW_BYTES - 1)
    samples = [i for i, op in enumerate(r.issues) if op == "SHIFT_IN"]
    assert samples[0] == AT + RX_SAMPLE and [b - a for a, b in zip(samples, samples[1:])] == [BIT] * 47


# --- RX3 to RX5: the stuff test, the stuff bit dropped, the stream on the pins -----------


def test_the_destuffed_stream_leaves_on_the_pins(vector):
    """can_rx_destuff.asm: at eight clocks a bit, after every sample the tree
    of SKIPs asks whether the last five were one level; when they were, the
    next bit is sampled as a stuff bit, into the raw history, and marked
    not data. Pin 2 carries the data bit and pin 3 whether the slot was
    data, so the two together are the destuffed stream, bit for bit the
    frame's, and the stuff slots are exactly where the reference put them;
    the receiver counts 42 data bits, pulls the ACK slot dominant, the pad
    on the bus for that bit alone, and the transmitter sees the ACK; then
    it holds through EOF and the intermission, and hands the host the last
    eight raw samples, the CRC delimiter last."""
    ident, data = vector
    bits, slot = frame_on_the_bus(ident, [data])
    r, tx = run_rx(DESTUFF, ident, [data])
    stream, stuff_slots = stream_from_pins(r, slot - 1)
    assert stream == frame_bits(ident, [data])
    assert stuff_slots == stuff_positions(ident, [data])
    assert tx.acked is True
    ack = slice(AT + slot * BIT, AT + (slot + 1) * BIT)
    assert r.owned[ack] == [True] * BIT and r.line[ack] == [0] * BIT, "the ACK slot pulled dominant"
    assert r.owned[: ack.start] == [False] * ack.start and r.owned[ack.stop :] == [False] * len(r.owned[ack.stop :])
    assert r.line[ack.stop :] == [1] * len(r.line[ack.stop :]), "recessive after the slot"
    assert r.received == [bits_to_int(bits[slot - 8 : slot])], "the last eight raw samples, the delimiter last"
    assert r.cpu.halted and not any(r.stalls[AT + 1 :]), "the WAIT's stall ends on the SOF"


def test_frames_across_the_range_are_destuffed():
    """The walking ones and zeros of the identifier with three payloads and
    every 97th identifier with its low byte: the stream on the pins is the
    frame's, the ACK given."""
    walking = [1 << i for i in range(11)] + [(1 << 11) - 1 - (1 << i) for i in range(11)]
    frames = [(ident, data) for ident in walking for data in (0x00, 0xFF, 0x55)] + [(i, i & 0xFF) for i in range(0, 1 << 11, 97)]
    for ident, data in frames:
        bits, slot = frame_on_the_bus(ident, [data])
        r, tx = run_rx(DESTUFF, ident, [data])
        stream, stuff_slots = stream_from_pins(r, slot - 1)
        assert stream == frame_bits(ident, [data]) and stuff_slots == stuff_positions(ident, [data]), f"frame {ident:03x} {data:02x}"
        assert tx.acked is True, f"frame {ident:03x} {data:02x}"


def test_the_destuffing_receiver_samples_the_sixth_clock_of_the_bit():
    """A probe pulls the bus dominant for one cycle of a recessive bit whose
    four before it are mixed, at each of its eight clocks in turn: the
    stream on the pins loses that bit exactly when the pulse is on the
    sixth clock, and the stuff slots stay where they were."""
    ident, data = IDENT, [0x5A]
    bits, slot = frame_on_the_bus(ident, data)
    stream = frame_bits(ident, data)
    k = next(k for k in range(8, 30) if bits[k] == 1 and len(set(bits[k - 4 : k])) == 2 and k not in stuff_positions(ident, data))
    j = k - sum(1 for s in stuff_positions(ident, data) if s < k)  # the stream bit the bus bit carries
    for p in range(BIT):
        r, _ = run_rx(DESTUFF, ident, data, glitch=Glitch(AT + k * BIT + p))
        got, stuff_slots = stream_from_pins(r, slot - 1)
        hit = p == RX_SAMPLE - 1
        assert got == stream[:j] + [0 if hit else 1] + stream[j + 1 :], f"pulse on clock {p + 1}"
        assert stuff_slots == stuff_positions(ident, data)


def test_the_destuffing_receiver_by_the_numbers():
    """RX3 to RX5 measured: the words, the decision, the bit, the state. 56
    words, 37 distinct: a 23-word cell as a body of 32 and again of 10,
    the 42 data bits; the decision after the sample is stage 4's tree, five
    cycles on the recessive side and six on the dominant, the JMP into the
    dominant tree the asymmetry again, and every exit padded to the REPEAT;
    it fits eight clocks a bit because a receiver's decision has until the
    next sample, not the next edge, and the sample sits at the sixth clock,
    75%: one SHIFT_IN, six of decision, one REPEAT. The state: the raw
    history in in_shift_reg, five bits read by the tree, the sixth for a
    stuff error; the destuffed bit on a pin, with no register to gather it
    in; the count of data bits in rc, which is why the ACK lands: the
    receiver is for DLC 1, the count a constant since nothing loads rc
    from the DLC it received."""
    words = load_program(DESTUFF)
    assert (len(words), len(set(words))) == (56, 37)
    r, tx = run_rx(DESTUFF, IDENT, [0x5A])
    bits, slot = frame_on_the_bus(IDENT, [0x5A])
    samples = [i for i, op in enumerate(r.issues) if op == "SHIFT_IN"]
    assert samples[0] < AT and samples[1] == AT + RX_SAMPLE, "the idle bus once, then the SOF's sixth clock"
    assert [b - a for a, b in zip(samples[1:], samples[2:])] == [BIT] * (len(samples) - 2), "every bus bit sampled, eight clocks apart, stuff bits too"
    assert len(samples) - 1 == slot, "the stuffed stream and the CRC delimiter"
    repeats = [i for i, op in enumerate(r.issues) if op == "REPEAT"]
    data = [samples[1 + k] for k in range(slot - 1) if k not in stuff_positions(IDENT, [0x5A])]
    assert len(repeats) == 42 + GAP and len(data) == 42
    assert all((rep - s) % BIT == 7 for rep, s in zip(repeats, data)), "the body ends a clock before the next data bit's sample, a stuff bit inside it or not"
    assert r.cpu.halted and r.cpu.cycle == AT + (slot + 2 + GAP) * BIT + 1


def test_a_stuff_error_is_the_sixth_sample_of_a_run():
    """Not built, the seed of a later stage: with six recessive bits in a row
    on the bus, no stuff bit, the receiver takes the sixth as a stuff bit
    and marks it not data, so the stream on the pins is short by one and
    the ACK is withheld, since the count never reaches the slot on time:
    what the bus shows a transmitter that skipped a stuff bit."""
    ident, data = 0x7FF, [0xFF]
    raw = frame_bits(ident, data) + [1, 1, 1] + [1] * GAP  # unstuffed
    tx = Transmitter(raw, AT, BIT, len(raw) - GAP - 2)
    r = Bus(DESTUFF, [], [tx]).go(AT + (len(raw) + 4) * BIT + 40).result()
    stream, stuff_slots = stream_from_pins(r, len(raw) - GAP - 3)
    assert stream != frame_bits(ident, data) and stuff_slots[:1] == [6]
    assert tx.acked is False


# --- RX5 through the FIFO: one bit a byte, nine clocks -----------------------------------


def test_the_destuffed_stream_leaves_through_the_fifo_one_bit_a_byte(vector):
    """can_rx_bits.asm: the same receiver with a PUSH after every data
    sample and none after a stuff bit, so bit 0 of each byte the host reads
    is the next data bit and the bytes together are the destuffed stream;
    the PUSH is a ninth cycle in the cell, so the bit is nine clocks and the
    transmitter here runs at nine; the ACK still lands."""
    ident, data = vector
    r, tx = run_rx(BITS, ident, [data], bit=BITS_BIT)
    assert [byte & 1 for byte in r.received] == frame_bits(ident, [data])
    assert tx.acked is True and r.rx_peak == 1 and not any(r.stalls[AT + 1 :])


def test_the_fifo_receiver_at_eight_clocks_a_bit_falls_behind():
    """The same program against a transmitter at eight clocks a bit: a clock
    late per bit, the samples walk out of the bits and the stream is not
    the frame's. Eight plus the PUSH is nine."""
    r, tx = run_rx(BITS, IDENT, [0x5A], bit=BIT)
    assert [byte & 1 for byte in r.received] != frame_bits(IDENT, [0x5A])


@pytest.mark.parametrize("sleep", (4, 5))
def test_a_host_that_does_not_pop_stalls_the_fifo_receiver_inside_the_frame(sleep):
    """The RX FIFO is four deep and a byte comes every bit: a host that
    reads nothing for `sleep` bit times and then drains is fine at four; at
    five the fifth PUSH finds it full and stalls, the receiver stops
    sampling, and the stream is wrong from there. The host must pop within
    four bit times of every byte, 36 cycles, all through the frame."""
    ident, data = IDENT, 0x5A
    first = AT + RX_SAMPLE + 1  # the first PUSH's cycle: the SOF's sample and one

    def host(cpu, received):
        if cpu.cycle >= first + sleep * BITS_BIT and cpu.rx_fifo:
            received.append(cpu.rx_fifo.pop(0))

    r, tx = run_rx(BITS, ident, [data], bit=BITS_BIT, drain=False, host=host)
    stream = [byte & 1 for byte in r.received]
    if sleep <= 4:
        assert not any(r.stalls[AT + 1 :]) and stream == frame_bits(ident, [data]) and r.rx_peak == 4
    else:
        assert r.stalls.count(True) > 0 and stream != frame_bits(ident, [data])


def test_the_fifo_receiver_by_the_numbers():
    """The FIFO as the second stream: a 24-word cell, one PUSH per data bit,
    nine clocks a bit, 42 pops a frame for the host, which then assembles
    the bytes itself."""
    words = load_program(BITS)
    assert (len(words), len(set(words))) == (57, 36)
    r, _ = run_rx(BITS, IDENT, [0x5A], bit=BITS_BIT)
    assert len(r.received) == 42 and r.issues.count("PUSH") == 42
    samples = [i for i, op in enumerate(r.issues) if op == "SHIFT_IN"]
    assert [b - a for a, b in zip(samples[1:], samples[2:])] == [BITS_BIT] * (len(samples) - 2)


# --- RX6: bytes in the core ----------------------------------------------------------------


def shadow_receiver(positions):
    """The receiver that keeps the destuffed data in in_shift_reg and the
    stuff history in the pc, written out: for every data bit k a cell whose
    run test reads the register as the raw history, and after a stuff bit
    of level s at k, four shadow cells for k + 1 to k + 4 whose run test
    knows the stuff bit the register lacks, "the last j bits all s"; a run
    found in a shadow starts the other level's shadow. No REPEAT can carry
    the shadow across its boundary, so every state is its own cell:
    positions x (1 + 2 x 4), less the ones past the end."""
    lines = ["CONFIG open_drain01, 1", "CONFIG shift_dir, 1", "SHIFT_IN 0", "WAIT 0, 0 [5]"]

    def target(name, k):
        return name if k < positions else "done"

    for k in range(positions):
        nxt, s0, s1 = target(f"d{k + 1}", k + 1), target(f"s0_{k + 1}_1", k + 1), target(f"s1_{k + 1}_1", k + 1)
        # the plain cell: the five-bit test on both levels, the exits padded, the stuff bit sampled on a run
        lines += [f"d{k}: SHIFT_IN 0", "SKIP 0, 1", f"JMP d{k}z"]
        for b in range(1, 5):
            lines += [f"SKIP {b}, 1", f"JMP {nxt} [{5 - b}]"]
        lines += [f"JMP d{k}s0 [1]"]
        lines += [f"d{k}z: SKIP 1, 0", f"JMP {nxt} [3]", "SKIP 2, 0", f"JMP {nxt} [2]", "SKIP 3, 0", f"JMP {nxt} [1]", "SKIP 4, 0", f"JMP {nxt}"]
        lines += [f"d{k}s0: SHIFT_IN 0 [5]", f"JMP {s0}", f"d{k}s1: SHIFT_IN 0 [5]", f"JMP {s1}"]
        for level in (0, 1):
            for j in range(1, 5):
                if k + j >= positions:
                    continue
                after = target(f"s{level}_{k + j + 1}_{j + 1}", k + j + 1) if j < 4 else target(f"d{k + j + 1}", k + j + 1)
                other = target(f"s{1 - level}_{k + j + 1}_1", k + j + 1)
                lines += [f"s{level}_{k + j}_{j}: SHIFT_IN 0"]
                for b in range(j):
                    lines += [f"SKIP {b}, {level}", f"JMP {after} [{j - b}]"]
                lines += ["NOP", "SHIFT_IN 0 [5]", f"JMP {other}"]
    lines += ["done: PUSH"]
    return "\n".join(lines) + "\n"


def test_bytes_in_the_core_put_the_stuff_history_in_the_pc_and_do_not_fit():
    """RX6 on this ISA: to hand the host destuffed bytes the register must
    hold data bits only, and then the run test cannot see the stuff bit the
    stream skipped. The only other place to keep "a stuff bit of level s,
    j bits ago" is the pc: four shadow cells per level after every data
    bit, and since a REPEAT body cannot carry that across its boundary,
    every data bit of the frame is its own cell with its own shadows. The
    header alone, nineteen bits, counted and handed to the assembler."""
    source = shadow_receiver(19)
    count = sum(1 for line in source.splitlines() if line.strip())
    assert count > 256, count
    with pytest.raises(SyntaxError):
        assemble(source)
    assert count == 1629, "six programs' worth for nineteen bits"
