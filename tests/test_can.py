"""CAN transmitter checks, staged the way SWD was: the smallest piece of the
protocol first, and the core is assumed able until a piece proves otherwise.
Classical CAN, standard 11-bit identifiers, one bus pin, no clock line: a bit
is BIT cycles long and every node samples it at the same point.

  1. the SOF and the identifier: the host composes the 12 bits as two bytes,
     the node drives each for a bit time, dominant 0 driven, recessive 1 let
     go, samples the bus on every bit, and lets go after ID[0]; an ideal
     receiver on the bus, synchronized on the SOF's edge, reads the identifier
     back;
  2. arbitration: a second transmitter starts on the same SOF with its own
     identifier; a node that sent recessive and sees dominant has lost and
     sends nothing more, so the bus carries the lower identifier whole;
  3. the ACK slot: after the identifier the transmitter lets go for one bit
     and samples it; a receiver that took the frame pulls it dominant; the
     ACK delimiter is recessive; not acked, the transmitter reports, waits
     out EOF and the intermission and sends the frame again when the host
     queues it again;
  4. bit stuffing: after five bits of one level the transmitter inserts one
     of the other, a full bit, and a receiver drops it; six of one level are
     a stuff error.

programs/can_tx.asm is stage 1; can_tx_arb.asm is stage 2, and sees the bus
the way a controller behind a transceiver does, because with the pad on the
bus the core cannot tell a lost bit from its own dominant one; can_tx_ack.asm
is stage 3, stage 1's frame with the ACK slot after it; can_tx_stuff.asm is
stage 4, stage 1's frame stuffed, at 16 cycles a bit because the decision
takes seven after the sample. Stages 1 and 2 stay as they are, the baselines.

The bench is the bus and the other nodes. The bus is a wired AND resolved
every cycle from the node under test and every other node: 0, dominant, if
anyone drives it, else 1, recessive. With the pad on the bus (`rxd` None)
the pad drives its 0s and lets go for its 1s, a push-pull 1 against a
dominant bit is a fight and fails here, and gpio_in 0 is the bus. Behind a
transceiver (`rxd` a pin) pin 0 is TXD, gpio_in 0 its own pad readback, the
bit as sent, and the bus comes back on gpio_in[rxd], RXD. A receiver syncs
on the recessive-to-dominant edge of the SOF and samples on a fixed clock of
every bit after it, the level the bus held as that clock began, the way the
transmitter's SHIFT_IN on the next clock does; it never resynchronizes and
knows no stuffing, later stages' business. A competitor is a receiver that
also transmits, and withdraws the way a node must."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
TX = PROGRAMS / "can_tx.asm"
ARB = PROGRAMS / "can_tx_arb.asm"
RXD = 1  # gpio_in pin can_tx_arb.asm listens to the bus on, behind a transceiver; pin 0 is then TXD
ARB_SAMPLE = 4  # can_tx_arb.asm samples the bus on the fourth clock of a bit: the decision needs the three after it
CAN_TX = 0  # the same pin number on gpio (the pad) and gpio_in (the bus): the shift pin
BIT = 8  # cycles per bit
SAMPLE = 6  # the clock of a bit whose level a node takes, 1..BIT: the sixth, read by the instruction on the seventh
ID_BITS = 11
HEADER = 1 + ID_BITS  # the SOF and the identifier, the bits stage 1 sends
IDENT = 0x5A3  # 101 1010 0011: no run longer than three, not a palindrome (0x62D backwards)
IDENTS = (IDENT, 0x62D, 0x000, 0x7FF, 0x400, 0x001)
NAMES = ("sof",) + tuple(f"id{i}" for i in range(ID_BITS - 1, -1, -1))
ACK = PROGRAMS / "can_tx_ack.asm"
ACK_FRAME = HEADER + 2  # the header, the ACK slot, the ACK delimiter: the bits stage 3 sends
GAP = 10  # EOF and the intermission: recessive bits before the next frame may start
STUFF = PROGRAMS / "can_tx_stuff.asm"
STUFF_BIT = 16  # cycles per bit in can_tx_stuff.asm: the stuffing decision takes seven after the sample
STUFF_SAMPLE = 8  # the clock of a bit can_tx_stuff.asm samples on: the eighth
STUFF_IDENTS = (0x7FF, 0x000, 0x07C, 0x7C0, 0x5A3, 0x555)  # runs of eleven, of five then five, and none


def stuffed(bits):
    """The bits as they go on the bus: after five of one level, one of the
    other, which starts the count again; the SOF counts."""
    out, level, count = [], None, 0
    for bit in bits:
        out.append(bit)
        level, count = (level, count + 1) if bit == level else (bit, 1)
        if count == 5:
            out.append(1 - bit)
            level, count = 1 - bit, 1
    return out


def header_bytes(ident):
    """The two bytes the host writes for the SOF and the identifier, MSB first:
    {SOF 0, ID[10:4]} and {ID[3:0], 0000}, the low nibble not sent."""
    assert 0 <= ident < 1 << ID_BITS
    return [ident >> 4, (ident & 0xF) << 4]


def header_bits(ident):
    """The order the bits appear on the bus: the SOF, then ID[10] down to ID[0]."""
    return [0] + [(ident >> i) & 1 for i in range(ID_BITS - 1, -1, -1)]


def bits_to_int(bits):
    """Bits as they came off the bus, first one most significant."""
    return sum(bit << (len(bits) - 1 - i) for i, bit in enumerate(bits))


class Node:
    """An ideal receiver on the bus. `update(line)` is called every cycle with
    the bus as it stood at the end of the cycle before and returns what the
    node drives this cycle: 0 or None. Idle, it waits for the bus to fall,
    the SOF, and counts clocks from that edge, `bit` to a bit: on the
    `sample`th clock of every bit it takes the level it was handed, the one
    the bus held as that clock began. When the HEADER bits are over it
    appends the identifier to `seen`; then, if it `ack`s the frame (a bool,
    or one per frame, the last repeating), it pulls the next bit, the ACK
    slot, dominant and lets go for the delimiter; a receiver that does not
    ack goes idle at once, ready for the next SOF, as stage 1's did.
    `samples` is every level taken this frame, the ACK slot's and the
    delimiter's included when it acks; `data` is the samples without the
    stuff bits when it `destuff`s: after five of one level the next is a
    stuff bit and is dropped, and if it is the same level again that is a
    stuff error, its index in `samples` appended to `errors`; the header is
    over when its twelve data bits and the stuff bit a run of five at its
    end calls for are in."""

    def __init__(self, sample=SAMPLE, ack=False, bit=BIT, destuff=False):
        self.sample, self.bit, self.destuff = sample, bit, destuff
        self.acks = list(ack) if isinstance(ack, (list, tuple)) else [ack]
        self.line = 1  # the bus as last seen
        self.clock = None  # clocks since the SOF's edge, None between frames
        self.phase = "idle"  # "header", then "ack" and "delimiter" when it acks
        self.samples, self.data, self.errors = [], [], []
        self.level, self.count = None, 0  # the run: the last level and how many of it
        self.seen = []
        self.frames = 0

    @property
    def acking(self):
        return self.acks[min(self.frames, len(self.acks) - 1)]

    def update(self, line):
        if self.clock is None and line == 0 and self.line == 1:
            self.clock, self.phase, self.samples, self.data = 0, "header", [], []
            self.level, self.count = None, 0
        if self.clock is not None:
            self.clock += 1
            if self.clock % self.bit == self.sample:
                self.samples.append(line)
                if self.phase == "header" and self.destuff and self.count == 5:
                    if line == self.level:
                        self.errors.append(len(self.samples) - 1)
                    self.level, self.count = line, 1
                else:
                    if self.phase == "header":
                        self.data.append(line)
                        self.sampled(len(self.data) - 1, line)
                    self.level, self.count = (self.level, self.count + 1) if line == self.level else (line, 1)
            if self.clock % self.bit == 0:
                if self.phase == "header" and len(self.data) == HEADER and not (self.destuff and self.count == 5):
                    assert self.data[0] == 0, "the SOF: the edge it synced on"
                    self.seen.append(bits_to_int(self.data[1:HEADER]))
                    self.phase = "ack" if self.acking else "idle"
                elif self.phase == "ack":
                    self.phase = "delimiter"
                elif self.phase == "delimiter":
                    self.phase = "idle"
                if self.phase == "idle":
                    self.clock, self.frames = None, self.frames + 1
        self.line = line
        return self.drive()

    def feed(self, bits):
        """Drive this node from a bus the bench makes up: `bits`, each held
        for a bit time, then idle; returns nothing, the node's lists tell."""
        for level in [1] + bits + [1] * 2:
            for _ in range(self.bit):
                self.update(level)

    def drive(self):
        return 0 if self.phase == "ack" else None

    def sampled(self, k, level):
        """Bit k of the frame, the SOF k = 0, sampled at `level`."""


class Competitor(Node):
    """A second transmitter, ideal and synchronized: it starts its frame on
    the SOF's edge, its own SOF the same dominant bit, and drives bit k of
    its header, `ident`, through the BIT cycles of bit k, a 0 driven, a 1 let
    go. It samples like a Node and, when it let go and sampled dominant, it
    has lost: `lost` is the bit it lost on, it drives nothing more and reads
    the rest as a receiver. After ID[0] it lets go: stage 2 sends nothing
    after the identifier."""

    def __init__(self, ident, sample=SAMPLE):
        super().__init__(sample)
        self.ident = ident
        self.bits = header_bits(ident)
        self.lost = None

    def drive(self):
        if self.clock is None or self.lost is not None or self.phase != "header":
            return super().drive()
        return 0 if self.bits[self.clock // self.bit] == 0 else None

    def sampled(self, k, level):
        if self.lost is None and k < HEADER and self.bits[k] == 1 and level == 0:
            self.lost = k


class Glitch:
    """Not a node: a probe that pulls the bus dominant for exactly one cycle,
    the one whose index is `at` (the cycle the run's `line` list indexes it
    by), to find where a bit is sampled."""

    def __init__(self, at):
        self.at = at
        self.i = -1

    def update(self, line):
        self.i += 1
        return 0 if self.i == self.at else None


class Run(NamedTuple):
    line: list  # the bus, one level per cycle: 0 if the node under test or any other drove it, else 1
    owned: list  # one per cycle: was the pad driving pin 0
    txd: list  # one per cycle: what the node under test put out, 0 or 1, a let-go pin a 1
    driven: list  # one per cycle: what the nodes drove, 0 or None, in node order
    received: list  # the bytes the host popped, in order
    nodes: list
    cpu: CPU
    stalls: list  # one per cycle: was the core stalled
    rx_peak: int  # the most bytes the RX FIFO held after any cycle, before the host's pop
    tx_peak: int  # the most bytes the TX FIFO held after any cycle


class Bus:
    """The bench: `program` in the core with `tx_data` waiting in the TX FIFO,
    `nodes` on the bus, and a host that, when `drain`, pops the RX FIFO as
    soon as a byte is there and runs `host(cpu, received)` every cycle to
    push what it decides to. `go(cycles)` steps that many cycles or up to the
    halt, the bus resolved after every cycle from the node under test and
    the others and fed back to gpio_in for the next. With `rxd` None the pad
    is on the bus: it drives its 0s, lets go for its 1s, and reads the bus
    back on gpio_in 0; the pad driving a 1 against a node's 0 is a fight,
    which no CAN node ever has, and fails here. With `rxd` a pin the node is
    behind a transceiver: pin 0 is TXD, gpio_in 0 its pad readback, the bit
    as sent, and the bus is on gpio_in[rxd], which pin the program must have
    let go."""

    def __init__(self, program, tx_data, nodes=(), drain=True, host=None, rxd=None):
        self.cpu = CPU(load_program(program), gpio_in=1, tx_data=list(tx_data))
        self.nodes = list(nodes)
        self.drain, self.host, self.rxd = drain, host, rxd
        self.line = 1
        self.lines, self.owned, self.txds, self.driven, self.received, self.stalls = [], [], [], [], [], []
        self.rx_peak = self.tx_peak = 0

    def go(self, cycles):
        cpu = self.cpu
        end = cpu.cycle + cycles
        while not cpu.halted and cpu.cycle < end:
            if self.host:
                self.host(cpu, self.received)
            self.tx_peak = max(self.tx_peak, len(cpu.tx_fifo))
            cpu.step()
            self.rx_peak = max(self.rx_peak, len(cpu.rx_fifo))
            drives = [node.update(self.line) for node in self.nodes]
            driving = cpu.gpio_oe[CAN_TX] == 1
            pad = cpu.gpio[CAN_TX] if driving else None
            if self.rxd is None:
                assert not (pad == 1 and 0 in drives), f"cycle {cpu.cycle}: the pad drives a 1 against a node's dominant 0"
                txd = 0 if pad == 0 else 1
                self.line = 0 if txd == 0 or 0 in drives else 1
                cpu.gpio_in[CAN_TX] = self.line
            else:
                assert cpu.gpio_oe[self.rxd] == 0, f"cycle {cpu.cycle}: pin {self.rxd} drives against RXD"
                txd = 1 if pad is None else pad
                self.line = 0 if txd == 0 or 0 in drives else 1
                cpu.gpio_in[CAN_TX] = txd
                cpu.gpio_in[self.rxd] = self.line
            self.lines.append(self.line)
            self.owned.append(driving)
            self.txds.append(txd)
            self.driven.append(drives)
            self.stalls.append(cpu.stalled)
            if self.drain and cpu.rx_fifo:
                self.received.append(cpu.rx_fifo.pop(0))
        return self

    def result(self):
        return Run(self.lines, self.owned, self.txds, self.driven, self.received, self.nodes, self.cpu, self.stalls, self.rx_peak, self.tx_peak)


def run(program, tx_data, nodes=None, cycles=2000, drain=True, host=None, rxd=None):
    """A Bus run for `cycles` or to the halt, as a Run, with one receiver on the bus unless told otherwise."""
    return Bus(program, tx_data, [Node()] if nodes is None else nodes, drain, host, rxd).go(cycles).result()


def arb(ident, nodes, **kw):
    """can_tx_arb.asm behind the transceiver, `ident` from the host, `nodes` on the bus."""
    return run(ARB, header_bytes(ident), nodes, rxd=RXD, **kw)


def pairs(bits):
    """The byte can_tx_arb.asm hands the host after sending `bits` unopposed:
    the last four (sent, seen) pairs, each bit twice."""
    return bits_to_int([b for bit in bits[-4:] for b in (bit, bit)])


def cells(line, start, count=HEADER, bit=BIT):
    """The bus from `start`, the SOF's edge, cut into `count` bits of `bit`
    cycles: what a receiver with a perfect clock sees. Every cycle of a bit
    must hold the same level, so a bit that stretches or glitches fails here
    rather than decoding by luck."""
    bits = []
    for k in range(count):
        cell = line[start + k * bit : start + (k + 1) * bit]
        assert len(cell) == bit, f"the bus ends inside bit {k}"
        assert len(set(cell)) == 1, f"bit {k} ({NAMES[k] if k < len(NAMES) else k}) not held for {bit} cycles: {cell}"
        bits.append(cell[0])
    return bits


def show(wave, r, bit=BIT, sample=SAMPLE, names=NAMES):
    wave.add("bus", r.line, group="bus")
    wave.add("txd", r.txd, group="bus")
    wave.add("pad drives", [int(o) for o in r.owned], group="bus")
    for i in range(len(r.nodes)):
        wave.add(f"node {i} drives", ["-" if d[i] is None else str(d[i]) for d in r.driven], group="bus")
    labels = ["-"] * len(r.line)
    sof = r.line.index(0)
    for k, name in enumerate(names):
        at = sof + k * bit + sample - 1
        if at < len(labels):
            labels[at] = name
    wave.add("sampled", labels)


@pytest.fixture(params=IDENTS, ids=lambda i: f"{i:03x}")
def ident(request):
    return request.param


# --- stage 1: the SOF and the identifier ------------------------------------------


def test_sof_and_identifier_reach_the_node_msb_first(ident, wave):
    """The host writes {SOF, ID[10:4]} and {ID[3:0], 0000}; on the bus, from
    the SOF's edge, twelve bits of exactly BIT cycles each, a dominant SOF and
    then ID[10] down to ID[0]; the receiver, syncing on that edge, reads the
    identifier back; the bus is recessive before the SOF and from ID[0]'s
    end to the halt, the pad off it; the host reads the last eight samples,
    ID[7:0] as the bus showed them, and nothing else."""
    r = run(TX, header_bytes(ident))
    show(wave, r)
    sof = r.line.index(0)
    assert cells(r.line, sof) == header_bits(ident)
    assert r.nodes[0].seen == [ident], "the receiver's own view"
    end = sof + HEADER * BIT
    assert r.line[:sof] == [1] * sof and r.line[end:] == [1] * len(r.line[end:]), "recessive around the frame"
    assert r.cpu.halted and r.cpu.gpio_oe[CAN_TX] == 0, "halted with the bus let go"
    assert r.received == [ident & 0xFF]


def test_identifiers_across_the_range_reach_the_node():
    """The eleven identifiers with one bit set, the eleven with one bit clear
    and every eleventh of the 2048, one frame each: twelve held bits in
    order, the identifier back from the receiver, ID[7:0] back to the host."""
    walking = [1 << i for i in range(ID_BITS)] + [(1 << ID_BITS) - 1 - (1 << i) for i in range(ID_BITS)]
    for ident in walking + list(range(0, 1 << ID_BITS, ID_BITS)):
        r = run(TX, header_bytes(ident))
        sof = r.line.index(0)
        assert cells(r.line, sof) == header_bits(ident), f"identifier {ident:03x}"
        assert r.nodes[0].seen == [ident] and r.received == [ident & 0xFF], f"identifier {ident:03x}"


def test_dominant_is_driven_and_recessive_is_let_go(ident):
    """A CAN node pulls the bus down for a dominant bit and lets go for a
    recessive one, so that another node's dominant can win: on every cycle
    the pad drives exactly when the bus is 0, and drives a 0 then. The same
    program with its first word a NOP, the pin push-pull, drives its 1s: an
    active recessive, which the bus cannot resolve against a dominant."""
    r = run(TX, header_bytes(ident))
    assert r.owned == [level == 0 for level in r.line]
    assert all(r.cpu.gpio_oe[CAN_TX] == 0 for _ in [0]) and r.cpu.gpio[CAN_TX] == 1

    words = load_program(TX)
    assert decode(words[0], load_isa()).op == "CONFIG"
    push_pull = Bus(TX, header_bytes(ident))
    push_pull.cpu.program[0] = 0  # NOP: pin 0 stays push-pull
    push_pull.go(2000)
    assert push_pull.owned == [True] * len(push_pull.owned), "push-pull: the pad drives its recessive bits too"


def test_the_sample_point_is_the_sixth_clock_of_the_bit():
    """Where in a bit the node samples, seen from outside: a second node pulls
    the bus dominant for one cycle of ID[7], a recessive bit, at each of its
    eight cycles in turn. The transmitter's sample of that bit, bit 7 of the
    byte the host reads, and the receiver's, its view of the identifier, both
    see the glitch on exactly one cycle, the bit's sixth, and on no other;
    they agree because they sample at the same point. The transmitter lets go
    for a recessive bit, so the glitch is on the bus, not a fight."""
    sof = run(TX, header_bytes(IDENT)).line.index(0)
    k = NAMES.index("id7")
    assert header_bits(IDENT)[k] == 1, "a recessive bit"
    for p in range(BIT):
        at = sof + k * BIT + p
        r = run(TX, header_bytes(IDENT), [Node(), Glitch(at)])
        cell = r.line[sof + k * BIT : sof + (k + 1) * BIT]
        assert cell == [int(i != p) for i in range(BIT)], f"one dominant cycle in a recessive bit: {cell}"
        hit = p == SAMPLE - 1
        assert r.received == [IDENT & 0xFF & ~(hit << 7)], f"the transmitter's sample, glitch on cycle {p + 1} of the bit"
        assert r.nodes[0].seen == [IDENT & ~(hit << 7)], f"the receiver's sample, glitch on cycle {p + 1} of the bit"


@pytest.mark.parametrize("late", (1, 5, 6, 40))
def test_a_host_late_with_the_second_byte_stretches_id4(late):
    """CAN has no clock line to stop. The second byte's PULL issues in ID[4]'s
    eighth cycle; a host that pushes the byte `late` cycles after that
    stretches ID[4] by exactly `late`, the bus holding its level, and every
    later bit is late by as much. The transmitter's own samples move with its
    bits, so the byte it hands the host is right regardless; a receiver
    counting from the SOF reads the frame right while the sample still falls
    inside the moved bit, up to SAMPLE - 1 cycles, and wrong from SAMPLE on.
    On record, not fixed: the stall that let SWD's host sleep is a timing
    fault here."""
    bytes_ = header_bytes(IDENT)
    stalled = run(TX, bytes_[:1], cycles=200).stalls.index(True)  # the cycle the PULL first waits

    def host(cpu, received):
        if cpu.cycle == stalled + late:
            cpu.tx_fifo.append(bytes_[1])

    r = run(TX, bytes_[:1], host=host)
    sof = r.line.index(0)
    k = NAMES.index("id4")
    assert cells(r.line, sof, k) == header_bits(IDENT)[:k], "the bits before it on time"
    stretched = r.line[sof + k * BIT : sof + (k + 1) * BIT + late]
    assert stretched == [header_bits(IDENT)[k]] * (BIT + late), f"ID[4] held {len(stretched)} cycles"
    assert cells(r.line, sof + (k + 1) * BIT + late, HEADER - k - 1) == header_bits(IDENT)[k + 1 :], "the rest, late"
    assert r.stalls.count(True) == late
    assert r.received == [IDENT & 0xFF], "the transmitter samples its own bits where it drives them"
    assert (r.nodes[0].seen == [IDENT]) == (late < SAMPLE), f"the receiver's view {late} cycles late: {r.nodes[0].seen}"


def test_can_by_the_numbers():
    """Stage 1 measured: the program, the cycles, the host's part."""
    words = load_program(TX)
    r = run(TX, header_bytes(IDENT))
    assert len(words) == 13
    assert len(set(words)) == 8
    assert r.cpu.cycle == 100, "cycles, release to halt, the host prompt"
    assert r.line.index(0) == 3, "cycles from release to the SOF's edge"
    assert (r.tx_peak, r.rx_peak) == (2, 1)
    assert len(r.received) == 1, "one pop, two pushes"


# --- stage 2: arbitration ---------------------------------------------------------


LOWER, HIGHER = 0x1E3, 0x7A3  # 001 1110 0011 beats IDENT on ID[10] and lets go on ID[6], where IDENT is dominant; 111 1010 0011 loses to IDENT on ID[9]
LOSSES = [(IDENT & ~(1 << i), NAMES.index(f"id{i}")) for i in range(ID_BITS) if (IDENT >> i) & 1]  # IDENT loses to each, on that bit


def test_the_pad_on_the_bus_wins_for_free_and_cannot_lose(wave):
    """Stage 1's program, the pad on the bus, against a competitor. Where its
    identifier is lower it wins without a word of arbitration: the competitor
    lets go for its recessive ID[9], sees the dominant bit, withdraws, and
    the bus carries the frame whole. Where it is higher it should lose on
    ID[10], and drives on: it cannot know it sent recessive there, the sent
    bit sits on the pin register and nothing reads it. On record: the bus is
    the AND of both frames until the competitor, seeing dominant where it
    let go on ID[6], withdraws too, and the receiver reads an identifier
    nobody sent."""
    r = run(TX, header_bytes(IDENT), [Competitor(HIGHER), Node()])
    show(wave, r)
    competitor, receiver = r.nodes
    sof = r.line.index(0)
    assert cells(r.line, sof) == header_bits(IDENT), "the lower identifier, whole"
    assert competitor.lost == NAMES.index("id9") and competitor.seen == [IDENT]
    assert receiver.seen == [IDENT] and r.received == [IDENT & 0xFF]

    r = run(TX, header_bytes(IDENT), [Competitor(LOWER), Node()])
    competitor, receiver = r.nodes
    sof = r.line.index(0)
    assert r.txd[sof : sof + HEADER * BIT] == [bit for bit in header_bits(IDENT) for _ in range(BIT)], "drove every bit, the lost one and after"
    assert competitor.lost == NAMES.index("id6"), "the competitor, which should have won, withdrew on ID[6]"
    garbage = [a & b for a, b in zip(header_bits(IDENT), header_bits(LOWER))][: competitor.lost + 1] + header_bits(IDENT)[competitor.lost + 1 :]
    assert cells(r.line, sof) == garbage
    assert receiver.seen == [bits_to_int(garbage[1:])] and receiver.seen != [LOWER] and receiver.seen != [IDENT]


def test_arbitration_won(wave):
    """can_tx_arb.asm behind the transceiver against a competitor with a
    higher identifier: on ID[9] the node sends dominant, the competitor let
    go, sees dominant, withdraws; the node sends its identifier whole, 8
    cycles a bit as before, TXD its bits throughout, and reads the last four
    pairs back, each bit twice; the receiver and the competitor read the
    identifier; the same 100 cycles as stage 1."""
    r = arb(IDENT, [Competitor(HIGHER, ARB_SAMPLE), Node(ARB_SAMPLE)])
    show(wave, r)
    competitor, receiver = r.nodes
    sof = r.line.index(0)
    assert cells(r.line, sof) == header_bits(IDENT)
    assert r.txd[sof : sof + HEADER * BIT] == [bit for bit in header_bits(IDENT) for _ in range(BIT)]
    assert competitor.lost == NAMES.index("id9") and competitor.seen == [IDENT] and receiver.seen == [IDENT]
    assert r.received == [pairs(header_bits(IDENT))]
    assert r.cpu.cycle == 100 and r.cpu.halted and r.cpu.gpio[CAN_TX] == 1


@pytest.mark.parametrize("other, k", LOSSES, ids=lambda v: f"{v:03x}" if v > 11 else NAMES[v])
def test_arbitration_lost_on_each_recessive_bit(other, k, wave):
    """can_tx_arb.asm against a competitor whose identifier is IDENT with one
    of its recessive bits dominant: the node lets go on that bit, sees
    dominant, and sends nothing more, TXD recessive from the next bit to the
    halt, one cycle after that bit, two when the loss came before ID[4]'s
    PULL and the second byte, still queued, had to be PULLed away, so that
    the TX FIFO is empty at the halt either way; the competitor never sees a
    loss and its frame goes out whole; the receiver reads it; the host's byte
    ends in the pair (1, 0)."""
    r = arb(IDENT, [Competitor(other, ARB_SAMPLE), Node(ARB_SAMPLE)], cycles=200)
    show(wave, r)
    competitor, receiver = r.nodes
    sof = r.line.index(0)
    mine = header_bits(IDENT)
    early = k < NAMES.index("id4")
    assert mine[k] == 1 and header_bits(other)[k] == 0 and mine[:k] == header_bits(other)[:k]
    assert r.cpu.halted and r.cpu.cycle == sof + (k + 1) * BIT + 1 + early, "halted on the cycle after the lost bit, or the one after that"
    assert r.txd[sof : sof + (k + 1) * BIT] == [bit for bit in mine[: k + 1] for _ in range(BIT)], "its bits through the lost one"
    assert r.txd[sof + (k + 1) * BIT :] == [1] * (1 + early), "recessive after"
    assert r.received == [pairs(mine[: k + 1]) & ~1], "the pairs through the lost bit, (1, 0) last"
    assert r.cpu.tx_fifo == [], "the second byte PULLed away on an early loss, sent on a late one"
    assert competitor.lost is None
    # The bus goes on without the node: the competitor's frame whole, the receiver reading it.
    tail = Bus(ARB, [], [competitor, receiver], rxd=RXD)  # the halted node is off the bus; the nodes carry on from where they were
    tail.line = r.line[-1]
    for _ in range(HEADER * BIT - len(r.line) + sof + 2):
        drives = [node.update(tail.line) for node in tail.nodes]
        tail.line = 0 if 0 in drives else 1
        tail.lines.append(tail.line)
    line = r.line + tail.lines
    assert cells(line, sof) == header_bits(other)
    assert competitor.seen == [other] and receiver.seen == [other]


def test_the_arbitration_sample_point_is_the_fourth_clock_of_the_bit():
    """Where can_tx_arb.asm samples the bus, seen from outside, as for stage
    1: a glitch node pulls the bus dominant for one cycle of ID[7], a
    recessive bit, at each of its eight cycles in turn. The node loses on
    that bit, sent recessive and saw dominant, exactly when the glitch is on
    the fourth cycle, and goes through on every other."""
    sof = arb(IDENT, []).line.index(0)
    k = NAMES.index("id7")
    for p in range(BIT):
        r = arb(IDENT, [Node(ARB_SAMPLE), Glitch(sof + k * BIT + p)], cycles=200)
        hit = p == ARB_SAMPLE - 1
        assert (r.cpu.cycle == sof + (k + 1) * BIT + 2) == hit, f"glitch on cycle {p + 1} of the bit: halted at {r.cpu.cycle}"
        assert r.received == [pairs(header_bits(IDENT)[: k + 1]) & ~1 if hit else pairs(header_bits(IDENT))]


def test_arbitration_by_the_numbers():
    """Stage 2 measured against stage 1: the words, the cycles, the sample
    point, the host's part."""
    words, plain = load_program(ARB), load_program(TX)
    assert (len(words), len(set(words))) == (95, 34)
    assert (len(plain), len(set(plain))) == (13, 8)
    r = arb(IDENT, [Node(ARB_SAMPLE)])
    assert r.cpu.cycle == 100 and r.line.index(0) == 3
    assert (r.tx_peak, r.rx_peak, len(r.received)) == (2, 1, 1)
    assert (ARB_SAMPLE, SAMPLE) == (4, 6), "the decision's three cycles move the sample point two clocks earlier at 8 a bit"


# --- stage 3: the ACK slot ------------------------------------------------------------


def ack_byte(ident, acked):
    """What the host reads after the ACK slot: the last eight samples, ID[6:0] and the slot's."""
    return ((ident & 0x7F) << 1) | (0 if acked else 1)


def test_ack_slot_let_go_and_the_receivers_dominant_bit_sampled(ident, wave):
    """can_tx_ack.asm with a receiver that acks: after ID[0] the transmitter
    lets go for one bit and the receiver pulls it dominant, the pad off the
    bus for the whole slot; the delimiter is recessive, nobody driving; the
    host reads ID[6:0] and the ACK, 0; halted after the delimiter, the bus
    idle."""
    r = run(ACK, header_bytes(ident), [Node(ack=True)])
    show(wave, r)
    receiver = r.nodes[0]
    sof = r.line.index(0)
    assert cells(r.line, sof, ACK_FRAME) == header_bits(ident) + [0, 1]
    slot = slice(sof + HEADER * BIT, sof + (HEADER + 1) * BIT)
    assert r.owned[slot] == [False] * BIT and [d[0] for d in r.driven[slot]] == [0] * BIT, "the receiver's bit, the transmitter off the bus"
    assert r.owned[sof + HEADER * BIT :] == [False] * len(r.owned[sof + HEADER * BIT :])
    assert receiver.seen == [ident] and receiver.samples[HEADER:] == [0, 1]
    assert r.received == [ack_byte(ident, True)]
    assert r.cpu.halted and r.cpu.cycle == sof + ACK_FRAME * BIT, "halted as the delimiter ends"
    assert r.line[sof + ACK_FRAME * BIT :] == [], "nothing after: the bus idle is the halt's"


def no_ack_host(bytes_, late):
    """A host for can_tx_ack.asm: it queues `bytes_` again `late` cycles
    after it read a byte that says not acked, once."""
    state = {"at": None, "done": False}

    def host(cpu, received):
        if state["at"] is None and received and received[-1] & 1:
            state["at"] = cpu.cycle
        if state["at"] is not None and not state["done"] and cpu.cycle == state["at"] + late:
            cpu.tx_fifo.extend(bytes_)
            state["done"] = True

    return host


def test_not_acked_reports_waits_out_the_intermission_and_sends_the_frame_again(wave):
    """A receiver that does not ack the first frame and acks the second: the
    slot stays recessive, the host reads the ACK as 1, the transmitter holds
    the bus recessive for the delimiter, EOF and the intermission, ten bits,
    and sends the frame again from the two bytes the host queues again, the
    second SOF 82 cycles after the delimiter, JMP and PULL; the receiver
    reads the identifier twice and acks the second, the host reads the ACK
    as 0. On record: the host supplies the frame again, the core cannot."""
    r = run(ACK, header_bytes(IDENT), [Node(ack=[False, True])], host=no_ack_host(header_bytes(IDENT), 0))
    show(wave, r)
    receiver = r.nodes[0]
    sof = r.line.index(0)
    assert cells(r.line, sof, ACK_FRAME) == header_bits(IDENT) + [1, 1], "no ack"
    quiet = r.line[sof + HEADER * BIT : sof + (ACK_FRAME + GAP) * BIT + 2]
    assert quiet == [1] * len(quiet), "the slot, the delimiter, EOF and the intermission recessive"
    sof2 = sof + (ACK_FRAME + GAP) * BIT + 2
    assert r.line[sof2] == 0 and r.line[sof2 - 1] == 1, "the second SOF"
    assert cells(r.line, sof2, ACK_FRAME) == header_bits(IDENT) + [0, 1], "acked"
    assert receiver.seen == [IDENT, IDENT]
    assert r.received == [ack_byte(IDENT, False), ack_byte(IDENT, True)]
    assert r.stalls.count(True) == 0 and r.cpu.halted


@pytest.mark.parametrize("late", (50, 87, 88, 300))
def test_a_host_late_with_the_frame_again_stalls_the_core_on_an_idle_bus(late):
    """After a missing ACK the host has the delimiter's tail, EOF and the
    intermission to queue the frame again, 87 cycles from the byte it read;
    later than that the PULL stalls, the bus recessive, idle, and the second
    frame starts when the bytes land: a stall between frames is safe, the
    receiver reads the frame whole, unlike the stall inside one of stage 1.
    On record."""
    never = run(ACK, header_bytes(IDENT), [Node(ack=False)], cycles=400)
    at = next(i for i, byte in enumerate(never.received) if byte & 1)  # the byte is popped the cycle it is pushed
    popped = never.stalls.index(True) - 87  # the cycle the host read it, 87 before the PULL first waits
    assert never.stalls.index(True) == never.line.index(0) + (ACK_FRAME + GAP) * BIT + 1
    r = run(ACK, header_bytes(IDENT), [Node(ack=[False, True])], host=no_ack_host(header_bytes(IDENT), late), cycles=800)
    sof = r.line.index(0)
    assert r.stalls.count(True) == max(0, late - 87)
    sof2 = sof + (ACK_FRAME + GAP) * BIT + 2 + max(0, late - 87)
    assert r.line[sof + HEADER * BIT : sof2] == [1] * (sof2 - sof - HEADER * BIT), "recessive until the second SOF"
    assert cells(r.line, sof2, ACK_FRAME) == header_bits(IDENT) + [0, 1]
    assert r.nodes[0].seen == [IDENT, IDENT] and r.received == [ack_byte(IDENT, False), ack_byte(IDENT, True)]


def test_the_ack_slot_is_sampled_on_its_sixth_clock():
    """Where in the slot the transmitter samples, seen from outside, as for
    stage 1's bits: nobody on the bus but a probe that pulls the slot
    dominant for one cycle at each of its eight cycles in turn (a receiver
    that did not ack would take the pulse for a SOF); the host reads an ACK
    exactly when the pulse is on the slot's sixth cycle."""
    sof = run(ACK, header_bytes(IDENT), [], cycles=400).line.index(0)
    for p in range(BIT):
        r = run(ACK, header_bytes(IDENT), [Glitch(sof + HEADER * BIT + p)], cycles=400)
        assert r.line[sof + HEADER * BIT + p] == 0
        assert r.received[:1] == [ack_byte(IDENT, p == SAMPLE - 1)], f"glitch on cycle {p + 1} of the slot"


def test_ack_by_the_numbers():
    """Stage 3 measured: the words, the cycles, the host's part."""
    words = load_program(ACK)
    assert (len(words), len(set(words))) == (21, 16)
    r = run(ACK, header_bytes(IDENT), [Node(ack=True)])
    assert r.cpu.cycle == 3 + ACK_FRAME * BIT == 115
    assert (r.tx_peak, r.rx_peak, len(r.received)) == (2, 1, 1)


# --- stage 4: bit stuffing ------------------------------------------------------------


def stuffing_names(ident):
    """A name per bit on the bus, stuff bits marked."""
    names, level, count = [], None, 0
    for name, bit in zip(NAMES, header_bits(ident)):
        names.append(name)
        level, count = (level, count + 1) if bit == level else (bit, 1)
        if count == 5:
            names.append("stuff")
            level, count = 1 - bit, 1
    return names


def receiver():
    return Node(STUFF_SAMPLE, bit=STUFF_BIT, destuff=True)


@pytest.mark.parametrize("ident", STUFF_IDENTS, ids=lambda i: f"{i:03x}")
def test_a_stuff_bit_after_five_bits_of_one_level(ident, wave):
    """can_tx_stuff.asm on an idle bus with a receiver that drops stuff bits:
    from the SOF, the identifier's bits with one of the other level after
    every five of one, every bit held 16 cycles; the receiver reads the
    identifier with no stuff error; the bus recessive after; the host reads
    the last eight samples, stuff bits among them; halted a cycle after the
    last bit. 0x7FF and 0x000 take two stuff bits, 0x5A3 and 0x555 none."""
    r = run(STUFF, header_bytes(ident), [receiver()])
    show(wave, r, STUFF_BIT, STUFF_SAMPLE, stuffing_names(ident))
    sof = r.line.index(0)
    bits = stuffed(header_bits(ident))
    assert len(bits) - HEADER == {0x7FF: 2, 0x000: 2, 0x07C: 2, 0x7C0: 2, 0x5A3: 0, 0x555: 0}[ident]
    assert cells(r.line, sof, len(bits), STUFF_BIT) == bits
    assert r.nodes[0].seen == [ident] and r.nodes[0].errors == []
    assert r.owned == [level == 0 for level in r.line], "dominant driven, recessive let go, stuff bits too"
    end = sof + len(bits) * STUFF_BIT
    assert r.line[end:] == [1] * len(r.line[end:]) and r.cpu.halted and r.cpu.cycle == end + 1
    assert r.received == [bits_to_int(bits[-8:])]


def test_identifiers_across_the_range_are_stuffed():
    """The walking ones and zeros and every eleventh identifier: the bus is
    the reference's stuffing of the header, the receiver reads each back."""
    walking = [1 << i for i in range(ID_BITS)] + [(1 << ID_BITS) - 1 - (1 << i) for i in range(ID_BITS)]
    for ident in walking + list(range(0, 1 << ID_BITS, ID_BITS)):
        r = run(STUFF, header_bytes(ident), [receiver()])
        bits = stuffed(header_bits(ident))
        assert cells(r.line, r.line.index(0), len(bits), STUFF_BIT) == bits, f"identifier {ident:03x}"
        assert r.nodes[0].seen == [ident] and r.nodes[0].errors == [], f"identifier {ident:03x}"


def test_the_receiver_drops_stuff_bits_and_flags_six_of_one_level():
    """The bench's receiver on a bus the bench makes up: the stuffed header
    of 0x7FF reads as 0x7FF with no error; the same header unstuffed, eleven
    recessive bits in a row, is a stuff error on the sixth and, the count
    starting again there, on the eleventh, and the receiver still counts
    twelve data bits; a stuff bit that is one too early, after four, is read
    as data, so the identifier comes out wrong. The tests above can fail for
    the right reason."""
    node = receiver()
    node.feed(stuffed(header_bits(0x7FF)))
    assert node.seen == [0x7FF] and node.errors == []
    node = receiver()
    node.feed(header_bits(0x7FF))
    assert node.errors == [6, 11] and node.seen == [0x7FF]
    node = receiver()
    node.feed([0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1])
    assert node.seen != [0x7FF] and node.errors == []


def test_the_stuffing_sample_point_is_the_eighth_clock_of_the_bit():
    """Where can_tx_stuff.asm samples, seen from outside: a probe pulls the
    bus dominant for one cycle of ID[7], a recessive bit of 0x5A3, at each of
    its sixteen cycles in turn; the host's byte and the receiver's identifier
    lose that bit exactly when the pulse is on the eighth cycle (no stuff
    bit either way: 0x5A3 has no run of four for the pulse to complete)."""
    sof = run(STUFF, header_bytes(IDENT), []).line.index(0)
    k = NAMES.index("id7")
    for p in range(STUFF_BIT):
        r = run(STUFF, header_bytes(IDENT), [receiver(), Glitch(sof + k * STUFF_BIT + p)])
        hit = p == STUFF_SAMPLE - 1
        assert r.received == [IDENT & 0xFF & ~(hit << 7)], f"the transmitter's sample, pulse on cycle {p + 1} of the bit"
        assert r.nodes[0].seen == [IDENT & ~(hit << 7)], f"the receiver's sample, pulse on cycle {p + 1} of the bit"


def test_stuffing_by_the_numbers():
    """Stage 4 measured against stage 1: the words, the cycles, the bit time, the host's part."""
    words, plain = load_program(STUFF), load_program(TX)
    assert (len(words), len(set(words))) == (224, 71)
    assert (len(plain), len(set(plain))) == (13, 8)
    none, two = run(STUFF, header_bytes(0x5A3), [receiver()]), run(STUFF, header_bytes(0x7FF), [receiver()])
    assert none.cpu.cycle == 3 + HEADER * STUFF_BIT + 1 == 196
    assert two.cpu.cycle == 3 + (HEADER + 2) * STUFF_BIT + 1 == 228
    assert (none.tx_peak, none.rx_peak, len(none.received)) == (2, 1, 1)
    assert (STUFF_BIT, STUFF_SAMPLE, STUFF_BIT - STUFF_SAMPLE) == (16, 8, 8), "seven cycles of decision after the sample, and one over"
