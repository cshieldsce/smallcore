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
     a stuff error;
  5. a data frame, stage 5A: the SOF, the identifier, RTR, IDE, r0, the DLC,
     the data, the 15-bit CRC the host computed, stuffed throughout; then
     the fixed form, the CRC delimiter, the ACK slot let go and sampled, the
     ACK delimiter, EOF and the intermission, every bit the same length; a
     receiver that drops the stuff bits, checks the CRC and acks.

programs/can/can_tx.asm is stage 1; can_tx_arb.asm is stage 2, and sees the bus
the way a controller behind a transceiver does, because with the pad on the
bus the core cannot tell a lost bit from its own dominant one; can_tx_ack.asm
is stage 3, stage 1's frame with the ACK slot after it; can_tx_stuff.asm is
stage 4, stage 1's frame stuffed, at 16 cycles a bit because the decision
takes seven after the sample; can_tx_frame.asm is stage 5A, the whole frame
at stage 4's bit, unopposed. Stages 1 to 4 stay as they are, the baselines.

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

from cpu import CPU, Instruction, decode, encode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent.parent / "programs"
ACC_OPS = ("ACC_IN", "ACC_CRC", "ACC_OUT", "ACC_PUSH", "ACC_LOAD")


def before_the_accumulator():
    """programs/*.asm with no accumulator word, by the words themselves: the ones an ISA from before it can say."""
    isa = load_isa()
    return [path for path in sorted(PROGRAMS.rglob("*.asm")) if not any(decode(word, isa).op in ACC_OPS for word in load_program(path, isa))]
TX = PROGRAMS / "can" / "can_tx.asm"
ARB = PROGRAMS / "can" / "can_tx_arb.asm"
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
ACK = PROGRAMS / "can" / "can_tx_ack.asm"
ACK_FRAME = HEADER + 2  # the header, the ACK slot, the ACK delimiter: the bits stage 3 sends
GAP = 10  # EOF and the intermission: recessive bits before the next frame may start
STUFF = PROGRAMS / "can" / "can_tx_stuff.asm"
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
    issues: list  # one per cycle: the op that issued that cycle, or None while one holds or stalls


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
    let go. With `cpu` a CPU already built, on any model, it runs in the
    model's place: the candidates' bench."""

    def __init__(self, program, tx_data, nodes=(), drain=True, host=None, rxd=None, cpu=None):
        self.cpu = cpu or CPU(load_program(program), gpio_in=1, tx_data=list(tx_data))
        self.nodes = list(nodes)
        self.drain, self.host, self.rxd = drain, host, rxd
        self.line = 1
        self.lines, self.owned, self.txds, self.driven, self.received, self.stalls = [], [], [], [], [], []
        self.issues = []
        self.rx_peak = self.tx_peak = 0

    def go(self, cycles):
        cpu = self.cpu
        end = cpu.cycle + cycles
        while not cpu.halted and cpu.cycle < end:
            if self.host:
                self.host(cpu, self.received)
            self.tx_peak = max(self.tx_peak, len(cpu.tx_fifo))
            op = decode(cpu.program[cpu.pc], cpu.isa).op if cpu.counter == 0 else None
            cpu.step()
            self.issues.append(None if cpu.stalled else op)
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
        return Run(self.lines, self.owned, self.txds, self.driven, self.received, self.nodes, self.cpu, self.stalls, self.rx_peak, self.tx_peak, self.issues)


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


# --- stage 5A: a data frame -----------------------------------------------------------


FRAME = PROGRAMS / "can" / "can_tx_frame.asm"
FRAME_BIT = 16  # cycles per bit in can_tx_frame.asm: stage 4's, the stuffing decision unchanged
FRAME_SAMPLE = 7  # the clock of a bit whose level can_tx_frame.asm takes: the seventh, read by the SHIFT_IN on the eighth (43.75%)
CONTROL = 3  # RTR, IDE, r0, all dominant in a base-format data frame
DLC_BITS = 4
CRC_BITS = 15
CRC_POLY = 0x4599  # x^15 + x^14 + x^10 + x^8 + x^7 + x^4 + x^3 + 1
FRAME_DLC = 1  # the program's payload: the REPEAT count is 4 + DLC, so one program sends one length
FIFO = 4  # the TX FIFO's depth on the chip: the host at it never queues more
BODY = 8  # the bits one run of the program's stuffed cell body sends: a host byte, its PULL in the first
LEAD = 3  # the stream bits before the body: the SOF, ID[10], ID[9], the first host byte's top three
FRAME_VECTORS = ((0x5A3, 0x5A), (0x7FF, 0xFF), (0x000, 0x00), (0x07C, 0x00), (0x555, 0xAA), (0x123, 0x01))


def crc15(bits):
    """CAN's CRC over `bits`, the spec's register: shift, and XOR in the
    polynomial when the bit in and the bit out differ."""
    crc = 0
    for bit in bits:
        crc = (crc << 1) & 0x7FFF if bit == crc >> 14 else ((crc << 1) & 0x7FFF) ^ CRC_POLY
    return crc


def int_bits(value, n):
    return [(value >> i) & 1 for i in range(n - 1, -1, -1)]


def frame_bits(ident, data, crc=None):
    """The stuffed region of a base-format data frame, before stuffing: the
    SOF, ID[10:0], RTR, IDE, r0, the DLC, the data bytes MSB first, and the
    CRC over everything before it, or `crc` as given, wrong or not."""
    assert 0 <= ident < 1 << ID_BITS and len(data) <= 8
    bits = header_bits(ident) + [0] * CONTROL + int_bits(len(data), DLC_BITS)
    for byte in data:
        bits += int_bits(byte, 8)
    return bits + int_bits(crc15(bits) if crc is None else crc, CRC_BITS)


def frame_bytes(ident, data, crc=None):
    """The bytes the host writes for a frame, the stream cut where the
    program's PULLs fall: {SOF, ID[10], ID[9], 00000}, then eight bits a
    byte, the last one padded with zeros: 5 + DLC bytes."""
    bits = frame_bits(ident, data, crc)
    padded = bits[:LEAD] + [0] * (8 - LEAD) + bits[LEAD:]
    padded += [0] * (-len(padded) % 8)
    return [bits_to_int(padded[i : i + 8]) for i in range(0, len(padded), 8)]


def frame_names(ident, data):
    """A name per bit on the bus for a frame, stuff bits marked."""
    names = list(NAMES) + ["rtr", "ide", "r0"] + [f"dlc{i}" for i in range(DLC_BITS - 1, -1, -1)]
    for k in range(len(data)):
        names += [f"d{k}.{i}" for i in range(7, -1, -1)]
    names += [f"crc{i}" for i in range(CRC_BITS - 1, -1, -1)]
    out, level, count = [], None, 0
    for name, bit in zip(names, frame_bits(ident, data)):
        out.append(name)
        level, count = (level, count + 1) if bit == level else (bit, 1)
        if count == 5:
            out.append("stuff")
            level, count = 1 - bit, 1
    return out + ["crcdel", "ack", "ackdel"] + [f"eof{i}" for i in range(7)] + [f"ifs{i}" for i in range(3)]


def frame_end(ident, data, acked=True):
    """The bus from the SOF for a frame: the stuffed stream, then the fixed
    form, the CRC delimiter, the ACK slot, the ACK delimiter, EOF and the
    intermission."""
    return stuffed(frame_bits(ident, data)) + [1, 0 if acked else 1, 1] + [1] * GAP


def host_byte(ident, data, acked=True):
    """What the host reads after a frame: the last eight samples, the stuffed
    stream's last seven and the ACK slot's."""
    return bits_to_int(stuffed(frame_bits(ident, data))[-7:] + [0 if acked else 1])


class Received(NamedTuple):
    ident: int
    rtr: int
    ide: int
    r0: int
    dlc: int
    data: tuple
    crc: int
    crc_ok: bool
    acked: bool  # did this receiver pull the ACK slot dominant


class Frame:
    """A receiver for data frames on the bus, `update(line)` and `drive()`
    as a Node's: idle, it waits for the bus to fall, the SOF, and counts
    clocks from that edge, `bit` to a bit, taking the level on the
    `sample`th clock of every bit. From the SOF through the CRC it drops
    stuff bits, after five of one level the next, and a sixth of the same
    level is a stuff error, its index in `samples` in `errors`; the bits
    that remain are the identifier, RTR, IDE, r0, the DLC, DLC data bytes
    and the CRC, checked over the bits before it. Then the fixed form, not
    stuffed: the CRC delimiter; the ACK slot, which it pulls dominant when
    it `ack`s (a bool, or one per frame, the last repeating) and the CRC
    matched; the ACK delimiter; EOF and the intermission, ten bits. A
    dominant bit where the form says recessive goes to `form_errors` as
    (phase, bit). Every frame goes to `received` as a Received and its
    identifier to `seen`."""

    def __init__(self, sample=FRAME_SAMPLE, ack=True, bit=FRAME_BIT):
        self.sample, self.bit = sample, bit
        self.acks = list(ack) if isinstance(ack, (list, tuple)) else [ack]
        self.line = 1
        self.clock = None
        self.phase = "idle"
        self.samples, self.stream, self.fixed, self.errors, self.form_errors = [], [], [], [], []
        self.level, self.count = None, 0
        self.seen, self.received = [], []
        self.frames, self.gap = 0, 0
        self.driving = False

    @property
    def acking(self):
        return self.acks[min(self.frames, len(self.acks) - 1)]

    def length(self):
        """How long the stuffed region is once the DLC is in, else None."""
        head = HEADER + CONTROL + DLC_BITS
        if len(self.stream) < head:
            return None
        return head + 8 * min(bits_to_int(self.stream[HEADER + CONTROL : head]), 8) + CRC_BITS

    def update(self, line):
        if self.clock is None and line == 0 and self.line == 1:
            self.clock, self.phase = 0, "stuffed"
            self.samples, self.stream, self.fixed = [], [], []
            self.level, self.count, self.driving = None, 0, False
        if self.clock is not None:
            self.clock += 1
            if self.clock % self.bit == self.sample:
                self.samples.append(line)
                if self.phase == "stuffed":
                    if self.count == 5:
                        if line == self.level:
                            self.errors.append(len(self.samples) - 1)
                        self.level, self.count = line, 1
                    else:
                        self.stream.append(line)
                        self.level, self.count = (self.level, self.count + 1) if line == self.level else (line, 1)
                else:
                    self.fixed.append(line)
                    if line == 0 and self.phase != "ack":
                        self.form_errors.append((self.phase, len(self.fixed) - 1))
            if self.clock % self.bit == 0:
                if self.phase == "stuffed":
                    if len(self.stream) == self.length() and self.count != 5:
                        self.end_of_stream()
                        self.phase = "crc delimiter"
                elif self.phase == "crc delimiter":
                    self.phase = "ack"
                elif self.phase == "ack":
                    self.phase, self.driving = "ack delimiter", False
                elif self.phase == "ack delimiter":
                    self.phase, self.gap = "gap", 0
                elif self.phase == "gap":
                    self.gap += 1
                    if self.gap == GAP:
                        self.phase, self.clock, self.frames = "idle", None, self.frames + 1
        self.line = line
        return self.drive()

    def end_of_stream(self):
        bits = self.stream
        head = HEADER + CONTROL + DLC_BITS
        dlc = bits_to_int(bits[HEADER + CONTROL : head])
        data = tuple(bits_to_int(bits[head + 8 * k : head + 8 * k + 8]) for k in range(min(dlc, 8)))
        crc = bits_to_int(bits[-CRC_BITS:])
        ok = crc15(bits[:-CRC_BITS]) == crc
        self.driving = self.acking and ok
        self.received.append(Received(bits_to_int(bits[1:HEADER]), *bits[HEADER : HEADER + CONTROL], dlc, data, crc, ok, self.driving))
        self.seen.append(self.received[-1].ident)

    def feed(self, bits):
        """Drive this receiver from a bus the bench makes up: `bits`, each
        held for a bit time, then idle."""
        for level in [1] + bits + [1] * 2:
            for _ in range(self.bit):
                self.update(level)

    def drive(self):
        return 0 if self.phase == "ack" and self.driving else None


def frame_host(bytes_, late=(), depth=FIFO):
    """A host at the TX FIFO, `depth` deep: it queues `bytes_` in order, each
    on the first cycle the FIFO has room for it, or, for the bytes in
    `late`, {k: n}, n cycles after that. `queued` records the cycle each
    byte went in."""
    late, queue, state, queued = dict(late), list(bytes_), {"room": None}, []

    def host(cpu, received):
        if not queue or len(cpu.tx_fifo) >= depth:
            state["room"] = None
            return
        if state["room"] is None:
            state["room"] = cpu.cycle
        if cpu.cycle >= state["room"] + late.get(len(queued), 0):
            cpu.tx_fifo.append(queue.pop(0))
            queued.append(cpu.cycle)
            state["room"] = None

    host.queued = queued
    return host


def stalled_host(bytes_, k, late, depth=FIFO):
    """A host that queues `bytes_` promptly but byte `k`, which it pushes
    `late` cycles (1 or more) after the core first stalled for it: the stall
    lasts exactly `late` cycles."""
    queue, state = list(bytes_), {"stall": None}

    def host(cpu, received):
        if not queue or len(cpu.tx_fifo) >= depth:
            return
        if len(bytes_) - len(queue) != k:
            cpu.tx_fifo.append(queue.pop(0))
            return
        if cpu.stalled and state["stall"] is None:
            state["stall"] = cpu.cycle - 1
        if state["stall"] is not None and cpu.cycle == state["stall"] + late:
            cpu.tx_fifo.append(queue.pop(0))

    return host


def retry_host(bytes_):
    """A host for can_tx_frame.asm that queues `bytes_` promptly and, when it
    reads a byte that says not acked and has nothing left to queue, queues
    them again, once."""
    prompt = frame_host(list(bytes_) * 2)
    state = {"held": len(bytes_), "again": False}

    def host(cpu, received):
        if not state["again"] and received and received[-1] & 1 and len(prompt.queued) == state["held"]:
            state["again"] = True
        if len(prompt.queued) < state["held"] or state["again"]:
            prompt(cpu, received)

    host.queued = prompt.queued
    return host


def run_frame(ident, data, nodes=None, host=None, cycles=1500, **kw):
    """can_tx_frame.asm on the bus with a receiver that acks unless told
    otherwise, the host at a 4-deep FIFO, `data` the payload bytes."""
    return run(FRAME, [], [Frame()] if nodes is None else nodes, host=host or frame_host(frame_bytes(ident, data)), cycles=cycles, **kw)


def pulls(r):
    """(cycle, clock of the bus bit from the SOF, bit index) for every PULL and PUSH that issued, from the SOF's edge; bit and clock None before it."""
    sof = r.line.index(0)
    out = []
    for cycle, op in enumerate(r.issues):
        if op in ("PULL", "PUSH"):
            at = cycle - sof
            out.append((op, cycle, at // FRAME_BIT if at >= 0 else None, at % FRAME_BIT + 1 if at >= 0 else None))
    return out


@pytest.fixture(params=FRAME_VECTORS, ids=lambda v: f"{v[0]:03x}-{v[1]:02x}")
def vector(request):
    return request.param


def test_crc15_is_cans():
    """The bench's CRC against the catalogue's check value for CRC-15/CAN,
    "123456789" MSB first, 0x059e; and a frame with one bit flipped fails
    the check while the frame passes."""
    assert crc15([b for byte in b"123456789" for b in int_bits(byte, 8)]) == 0x059E
    bits = frame_bits(IDENT, [0x5A])
    assert crc15(bits[:-CRC_BITS]) == bits_to_int(bits[-CRC_BITS:])
    flipped = bits[:20] + [1 - bits[20]] + bits[21:]
    assert crc15(flipped[:-CRC_BITS]) != bits_to_int(flipped[-CRC_BITS:])


def test_the_frame_receiver_reads_a_made_up_frame_and_flags_what_is_wrong():
    """The bench's receiver on a bus the bench makes up: a whole frame reads
    back whole, CRC matched, acked; the same with a data bit flipped reads
    with the CRC unmatched and no ACK; six of one level are a stuff error; a
    dominant bit in EOF is a form error; a frame with DLC 2 reads two bytes."""
    node = Frame()
    node.feed(frame_end(IDENT, [0x5A]))
    assert node.received == [Received(IDENT, 0, 0, 0, 1, (0x5A,), crc15(frame_bits(IDENT, [0x5A])[:-CRC_BITS]), True, True)]
    assert node.errors == [] and node.form_errors == [] and node.seen == [IDENT] and node.frames == 1
    bits = frame_bits(IDENT, [0x5A])
    node = Frame()
    node.feed(stuffed(bits[:24] + [1 - bits[24]] + bits[25:]) + [1, 1, 1] + [1] * GAP)
    assert node.received[0].ident == IDENT and node.received[0].data == (0x5A ^ 0x04,)
    assert not node.received[0].crc_ok and not node.received[0].acked and node.form_errors == []
    node = Frame()
    node.feed(frame_bits(0x7FF, [0xFF]) + [1, 0, 1] + [1] * GAP)
    assert node.errors[:3] == [6, 11, 17], "unstuffed: the sixth of each run is an error, the identifier's two and the control field's zeros"
    node = Frame()
    node.feed(frame_end(IDENT, [0x5A])[:-5] + [0] + [1] * 4)
    assert node.form_errors == [("gap", 8)] and node.received[0].crc_ok
    node = Frame()
    node.feed(frame_end(0x123, [0x01, 0x02]))
    assert node.received[0].dlc == 2 and node.received[0].data == (0x01, 0x02) and node.received[0].acked


def test_the_host_bytes_cut_the_stream_where_the_pulls_fall():
    """The first byte carries the SOF, ID[10] and ID[9] in its top three bits,
    every byte after it eight stream bits, the last padded: 5 + DLC bytes,
    and back to back, the top three of the first and the rest, they are the
    stream."""
    for ident, data in FRAME_VECTORS:
        bytes_ = frame_bytes(ident, [data])
        assert len(bytes_) == 5 + 1 and bytes_[0] & 0x1F == 0
        bits = int_bits(bytes_[0], 8)[:LEAD] + [b for byte in bytes_[1:] for b in int_bits(byte, 8)]
        assert bits[: len(frame_bits(ident, [data]))] == frame_bits(ident, [data])
    assert len(frame_bytes(IDENT, [1, 2, 3, 4, 5, 6, 7, 8])) == 13


def test_the_data_frame_reaches_the_receiver(vector, wave):
    """can_tx_frame.asm with the host's 5 + DLC bytes and a receiver that
    acks: on the bus, from the SOF's edge, the stuffed stream, a recessive
    CRC delimiter, the ACK slot pulled dominant by the receiver with the pad
    off it, the ACK delimiter, EOF and the intermission, every bit 16
    cycles; the receiver reads the identifier, DLC 1, the byte and a CRC
    that matches, no stuff or form error; the pad drives dominant bits and
    lets go for recessive ones; the bus recessive before and after; the host
    reads the last eight samples, the ACK 0 last; halted a cycle after the
    intermission, no stall anywhere."""
    ident, data = vector
    r = run_frame(ident, [data])
    show(wave, r, FRAME_BIT, FRAME_SAMPLE, frame_names(ident, [data]))
    sof = r.line.index(0)
    bits = frame_end(ident, [data])
    assert cells(r.line, sof, len(bits), FRAME_BIT) == bits
    rx = r.nodes[0]
    assert rx.received == [Received(ident, 0, 0, 0, 1, (data,), crc15(frame_bits(ident, [data])[:-CRC_BITS]), True, True)]
    assert rx.errors == [] and rx.form_errors == []
    slot = slice(sof + (len(bits) - GAP - 2) * FRAME_BIT, sof + (len(bits) - GAP - 1) * FRAME_BIT)
    assert r.owned[slot] == [False] * FRAME_BIT and [d[0] for d in r.driven[slot]] == [0] * FRAME_BIT, "the receiver's bit, the pad off the bus"
    outside = [i for i in range(len(r.line)) if not slot.start <= i < slot.stop]
    assert [r.owned[i] for i in outside] == [r.line[i] == 0 for i in outside], "dominant driven, recessive let go"
    end = sof + len(bits) * FRAME_BIT
    assert r.line[:sof] == [1] * sof and r.line[end:] == [1] * len(r.line[end:])
    assert r.received == [host_byte(ident, [data])]
    assert r.cpu.halted and r.cpu.cycle == end + 1 and r.stalls.count(True) == 0


def test_frames_across_the_range_reach_the_receiver():
    """The walking ones and zeros of the identifier with three payloads, and
    every 97th identifier with its low byte as the payload: the bus is the
    reference's frame, the receiver reads it whole and acks."""
    walking = [1 << i for i in range(ID_BITS)] + [(1 << ID_BITS) - 1 - (1 << i) for i in range(ID_BITS)]
    frames = [(ident, data) for ident in walking for data in (0x00, 0xFF, 0x55)] + [(i, i & 0xFF) for i in range(0, 1 << ID_BITS, 97)]
    for ident, data in frames:
        r = run_frame(ident, [data])
        bits = frame_end(ident, [data])
        assert cells(r.line, r.line.index(0), len(bits), FRAME_BIT) == bits, f"frame {ident:03x} {data:02x}"
        rx = r.nodes[0].received
        assert rx and rx[0][:6] == (ident, 0, 0, 0, 1, (data,)) and rx[0].crc_ok and rx[0].acked, f"frame {ident:03x} {data:02x}"
        assert r.nodes[0].errors == [] and r.received == [host_byte(ident, [data])], f"frame {ident:03x} {data:02x}"


def probe_bit(ident, data):
    """A bit to glitch: the last recessive bit of the stuffed stream whose
    four samples before it are neither all dominant nor all recessive, so
    that one dominant sample in it changes no stuffing decision on either
    side, only the bit itself, which lands in the host's byte."""
    bits = stuffed(frame_bits(ident, data))
    for k in range(len(bits) - 1, len(bits) - 8, -1):
        if bits[k] == 1 and len(set(bits[k - 4 : k])) == 2:
            return k, bits
    raise AssertionError("no such bit in the last seven")


def test_the_frame_sample_point_is_the_seventh_clock_of_the_bit():
    """Where can_tx_frame.asm samples, seen from outside: a probe pulls the
    bus dominant for one cycle of a recessive CRC bit at each of its sixteen
    cycles in turn. The host's byte loses that bit exactly when the pulse is
    on the seventh cycle, and the receiver, sampling at the same point, sees
    a CRC that does not match then and only then, so it does not ack: the
    byte's ACK bit says so too."""
    sof = run_frame(IDENT, [0x5A], nodes=[]).line.index(0)
    k, bits = probe_bit(IDENT, [0x5A])
    for p in range(FRAME_BIT):
        r = run_frame(IDENT, [0x5A], nodes=[Frame(), Glitch(sof + k * FRAME_BIT + p)])
        hit = p == FRAME_SAMPLE - 1
        byte = host_byte(IDENT, [0x5A], acked=not hit) & ~(hit << (len(bits) - k))
        assert r.received == [byte], f"pulse on cycle {p + 1} of the bit"
        rx = r.nodes[0].received[0]
        assert rx.ident == IDENT and rx.crc_ok == (not hit) and rx.acked == (not hit), f"pulse on cycle {p + 1} of the bit"


@pytest.mark.parametrize("k", range(1, 6))
@pytest.mark.parametrize("late", (1, 6, 7, 40))
def test_a_host_late_with_a_frame_byte_stretches_the_bit_under_its_pull(k, late):
    """The PULL for byte k issues on the seventh clock of the first bit of
    the k-th body run, stream bit 3 + 8 (k - 1) counting the SOF as 0, stuff
    bits before it not counted; a host `late` cycles after it first waits
    stretches that bit by exactly `late`, the bus holding its level, and
    every later bit is late by as much. The transmitter's samples move with
    its bits; a receiver counting from the SOF reads the frame right while
    its sample still falls inside the moved bit, up to 6 cycles, and from 7
    reads a CRC that does not match and does not ack. On record: a PULL
    inside a frame is a timing fault, and there are five of them."""
    ident, data = IDENT, [0x5A]
    bits = frame_end(ident, data)
    stream = frame_bits(ident, data)
    j = LEAD + BODY * (k - 1) - 1  # the stream bit whose cell holds the PULL
    on_bus = len(stuffed(stream[:j]))  # the bus bit that carries stream bit j: the stuff bits before it counted
    r = run_frame(ident, data, host=stalled_host(frame_bytes(ident, data), k, late), cycles=2000)
    sof = r.line.index(0)
    assert cells(r.line, sof, on_bus, FRAME_BIT) == bits[:on_bus], "the bits before it on time"
    held = r.line[sof + on_bus * FRAME_BIT : sof + (on_bus + 1) * FRAME_BIT + late]
    assert held == [bits[on_bus]] * (FRAME_BIT + late), f"the bit under the PULL held {len(held)} cycles"
    stuffed_stream = stuffed(stream)
    late_bits = cells(r.line, sof + (on_bus + 1) * FRAME_BIT + late, len(stuffed_stream) - on_bus - 1, FRAME_BIT)
    assert late_bits == stuffed_stream[on_bus + 1 :], "the rest of the stream, late"
    first = r.stalls.index(True)
    assert first == sof + on_bus * FRAME_BIT + FRAME_SAMPLE - 1, "the PULL waited on the seventh clock of that bit"
    assert r.stalls[first : first + late + 1] == [True] * late + [False], f"for {late} cycles"
    acked = late < FRAME_SAMPLE
    rx = r.nodes[0].received[0]
    assert (rx.crc_ok, rx.acked) == (acked, acked), f"the receiver's view {late} cycles late"
    slot = sof + (len(stuffed_stream) + 1) * FRAME_BIT  # the receiver's ACK slot, on its clock from the SOF, not the transmitter's
    assert [d[0] for d in r.driven[slot : slot + FRAME_BIT]] == [0 if acked else None] * FRAME_BIT
    assert r.received == [host_byte(ident, data, acked)], "the transmitter samples its own bits where it drives them, the slot included"


def test_every_point_where_a_stall_would_corrupt_the_frame():
    """The census: with a prompt host, what issues against a FIFO inside the
    frame. Five PULLs, one on the seventh clock of the first bit of every
    body run, the bit carrying stream bit 2, 10, 18, 26 and 34 (bus bits
    later by the stuff bits before them); one PUSH, on the first clock of
    the ACK delimiter; and the PULL before the SOF, on an idle bus. A PULL
    late by one cycle at any of the five stretches the frame by one from
    that bit on, the receiver still reading it; the PUSH stalled, the RX
    FIFO full because the host never reads, holds the ACK delimiter, which
    is recessive as EOF and the intermission are: the one stall point in the
    frame that corrupts nothing but the node's own intermission."""
    ident, data = 0x7FF, [0xFF]
    r = run_frame(ident, data)
    sof = r.line.index(0)
    stream = frame_bits(ident, data)
    census = pulls(r)
    on_bus = [len(stuffed(stream[: LEAD + BODY * k - 1])) for k in range(5)]
    assert census[0] == ("PULL", sof - 1, None, None), "the first byte, before the frame"
    assert census[1:6] == [("PULL", sof + b * FRAME_BIT + FRAME_SAMPLE - 1, b, FRAME_SAMPLE) for b in on_bus]
    ack_delimiter = len(frame_end(ident, data)) - GAP - 1
    assert census[6] == ("PUSH", sof + ack_delimiter * FRAME_BIT, ack_delimiter, 1)
    assert len(census) == 7
    end = sof + len(stuffed(stream)) * FRAME_BIT  # the stream's end, the transmitter's alone; the ACK after it is on the receiver's clock
    for k, b in enumerate(on_bus, start=1):
        late = run_frame(ident, data, host=stalled_host(frame_bytes(ident, data), k, 1), cycles=2000)
        assert late.cpu.cycle == r.cpu.cycle + 1 and late.stalls.index(True) == sof + b * FRAME_BIT + FRAME_SAMPLE - 1
        assert late.line[: sof + b * FRAME_BIT] == r.line[: sof + b * FRAME_BIT] and late.line[sof + b * FRAME_BIT + 1 : end + 1] == r.line[sof + b * FRAME_BIT : end]
        assert late.nodes[0].received[0].acked and late.received == r.received, "one cycle late: read whole"
    bus = Bus(FRAME, [], [Frame(ack=False)], drain=False, host=frame_host(frame_bytes(ident, data) * 2))
    bus.cpu.rx_depth = 1
    full = bus.go(3000).result()
    assert full.nodes[0].frames == 2 and full.issues.count("PUSH") == 1, "the second frame's PUSH never issues"
    stall = full.stalls.index(True)
    second = full.line.index(0, sof + (len(frame_end(ident, data)) - 1) * FRAME_BIT)
    assert stall == second + ack_delimiter * FRAME_BIT, "stalled on the ACK delimiter's first clock"
    assert full.stalls[stall:] == [True] * len(full.stalls[stall:]) and full.line[stall:] == [1] * len(full.line[stall:]), "recessive throughout: harmless"
    assert full.nodes[0].received[1].ident == ident and full.nodes[0].form_errors == []


def test_not_acked_the_host_queues_the_frame_again_after_the_intermission():
    """A receiver that does not ack the first frame and acks the second: the
    slot stays recessive, the host reads the ACK as 1 and queues the six
    bytes again; the transmitter holds EOF and the intermission, ten
    recessive bits, and the second SOF falls four cycles after them, SKIP,
    JMP, the idle sample and the PULL; the receiver reads the frame twice
    and acks the second, the host reads the ACK as 0; halted after the
    second intermission."""
    ident, data = IDENT, [0x5A]
    r = run_frame(ident, data, nodes=[Frame(ack=[False, True])], host=retry_host(frame_bytes(ident, data)), cycles=3000)
    sof = r.line.index(0)
    first, second = frame_end(ident, data, acked=False), frame_end(ident, data)
    assert cells(r.line, sof, len(first), FRAME_BIT) == first
    sof2 = sof + len(first) * FRAME_BIT + 4
    assert r.line[sof + len(first) * FRAME_BIT : sof2] == [1] * 4 and r.line[sof2] == 0
    assert cells(r.line, sof2, len(second), FRAME_BIT) == second
    assert [f.acked for f in r.nodes[0].received] == [False, True] and r.nodes[0].seen == [ident, ident]
    assert r.received == [host_byte(ident, data, False), host_byte(ident, data, True)]
    assert r.stalls.count(True) == 0 and r.cpu.halted and r.cpu.cycle == sof2 + len(second) * FRAME_BIT + 1


def body_repeat(words):
    """The address of the REPEAT that runs the stuffed cell body, the one with count 4 + DLC."""
    return next(i for i, w in enumerate(words) if decode(w, load_isa()).op == "REPEAT" and decode(w, load_isa()).delay == 4 + FRAME_DLC - 1)


def test_the_same_words_send_eight_bytes_with_the_repeat_count_changed():
    """One program per payload length: the body runs 4 + DLC times, so the
    same words with the body's REPEAT count 12 send a DLC 8 frame, 98
    stream bits, 13 host bytes, of which the host queues nine inside the
    frame as the PULLs make room; the receiver reads the eight bytes."""
    words = load_program(FRAME)
    words[body_repeat(words)] = encode(Instruction("REPEAT", (decode(words[body_repeat(words)], load_isa()).args[0],), 11), load_isa())
    ident, data = 0x5A3, [0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF]
    bits = frame_end(ident, data)
    assert len(frame_bits(ident, data)) == 98 and len(frame_bytes(ident, data)) == 13
    host = frame_host(frame_bytes(ident, data))
    bus = Bus(FRAME, [], [Frame()], host=host, cpu=CPU(words, gpio_in=1))
    r = bus.go(3000).result()
    sof = r.line.index(0)
    assert cells(r.line, sof, len(bits), FRAME_BIT) == bits
    assert r.nodes[0].received[0][:6] == (ident, 0, 0, 0, 8, tuple(data)) and r.nodes[0].received[0].acked
    assert r.tx_peak == FIFO and sum(1 for c in host.queued if c >= sof) == 9 and r.stalls.count(True) == 0
    assert r.received == [host_byte(ident, data)]


def test_frame_by_the_numbers():
    """Stage 5A measured: the words, the cycles, the bit, the host's part,
    and the cycles in hand at every PULL for a host that fills the FIFO as
    room appears: bytes 1 to 3 have everything from the release, byte 4
    from the first PULL, before the SOF, and byte 5, as every byte after it
    would, the time from the PULL four bytes before it to its own: 32 stream
    bits and the stuff bits among them, less a cycle, 511 at the least."""
    words = load_program(FRAME)
    assert len(words) == 233
    assert len(set(words)) == 86
    r = run_frame(IDENT, [0x5A])
    sof = r.line.index(0)
    assert sof == 4, "cycles from release to the SOF's edge"
    assert len(frame_end(IDENT, [0x5A])) == 57, "42 stream bits, two stuff bits, the delimiter, the slot, the delimiter, ten"
    assert r.cpu.cycle == sof + 57 * FRAME_BIT + 1 == 917
    assert (r.tx_peak, r.rx_peak, len(r.received)) == (FIFO, 1, 1), "6 pushes through a 4-deep FIFO, 1 pop"
    census = [p for p in pulls(r) if p[0] == "PULL"]
    room = [0] * FIFO + [census[k - FIFO][1] + 1 for k in range(FIFO, 6)]
    in_hand = [census[k][1] - room[k] for k in range(6)]
    assert in_hand == [3, 42, 170, 314, 438, 543]
    for ident, data in FRAME_VECTORS:
        stream = frame_bits(ident, [data])
        census = [p for p in pulls(run_frame(ident, [data])) if p[0] == "PULL"]
        between = len(stuffed(stream[: LEAD + 4 * BODY - 1])) - len(stuffed(stream[: LEAD - 1]))  # bus bits from byte 1's PULL to byte 5's
        assert census[5][1] - census[1][1] - 1 == between * FRAME_BIT - 1 >= 4 * BODY * FRAME_BIT - 1 == 511, f"frame {ident:03x} {data:02x}"
    assert (FRAME_BIT, FRAME_SAMPLE) == (16, 7), "stage 4's bit and the loop form's sample point"
