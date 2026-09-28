"""CAN transmitter checks, staged the way SWD was: the smallest piece of the
protocol first, and the core is assumed able until a piece proves otherwise.
Classical CAN, standard 11-bit identifiers, one bus pin, no clock line: a bit
is BIT cycles long and every node samples it at the same point.

  1. the SOF and the identifier: the host composes the 12 bits as two bytes,
     the node drives each for a bit time, dominant 0 driven, recessive 1 let
     go, samples the bus on every bit, and lets go after ID[0]; an ideal
     receiver on the bus, synchronized on the SOF's edge, reads the identifier
     back.

programs/can_tx.asm is stage 1.

The bench is the bus and the other nodes. The bus is a wired AND resolved
every cycle from the pad (gpio and gpio_oe) and every node: 0, dominant, if
anyone drives it, else 1, recessive. A node drives 0 or lets go, never 1: a
push-pull 1 from the pad against a dominant bit is a fight, and fails here.
A receiver syncs on the recessive-to-dominant edge of the SOF and samples on
the sixth clock of every bit after it, the level the bus held as that clock
began, the way the transmitter's SHIFT_IN on the seventh clock does; it never
resynchronizes and knows no stuffing, later stages' business."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
TX = PROGRAMS / "can_tx.asm"
CAN_TX = 0  # the same pin number on gpio (the pad) and gpio_in (the bus): the shift pin
BIT = 8  # cycles per bit
SAMPLE = 6  # the clock of a bit whose level a node takes, 1..BIT: the sixth, read by the instruction on the seventh
ID_BITS = 11
HEADER = 1 + ID_BITS  # the SOF and the identifier, the bits stage 1 sends
IDENT = 0x5A3  # 101 1010 0011: no run longer than three, not a palindrome (0x62D backwards)
IDENTS = (IDENT, 0x62D, 0x000, 0x7FF, 0x400, 0x001)
NAMES = ("sof",) + tuple(f"id{i}" for i in range(ID_BITS - 1, -1, -1))


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
    node drives this cycle: 0 or None, and this one never drives. Idle, it
    waits for the bus to fall, the SOF, and counts clocks from that edge: on
    the SAMPLEth clock of every bit it takes the level it was handed, the one
    the bus held as that clock began. After HEADER samples it appends the
    identifier to `seen` and is idle again, ready for the next SOF."""

    def __init__(self):
        self.line = 1  # the bus as last seen
        self.clock = None  # clocks since the SOF's edge, None between frames
        self.samples = []
        self.seen = []

    def update(self, line):
        if self.clock is None and line == 0 and self.line == 1:
            self.clock = 0
        if self.clock is not None:
            self.clock += 1
            if self.clock % BIT == SAMPLE:
                self.samples.append(line)
                if len(self.samples) == HEADER:
                    assert self.samples[0] == 0, "the SOF: the edge it synced on"
                    self.seen.append(bits_to_int(self.samples[1:]))
                    self.samples, self.clock = [], None
        self.line = line
        return None


class Glitch(Node):
    """A node that pulls the bus dominant for exactly one cycle, the one whose
    index is `at` (the cycle the run's `line` list indexes it by), and reads
    like a Node the rest of the time: a probe for where a bit is sampled."""

    def __init__(self, at):
        super().__init__()
        self.at = at
        self.i = -1

    def update(self, line):
        super().update(line)
        self.i += 1
        return 0 if self.i == self.at else None


class Run(NamedTuple):
    line: list  # the bus, one level per cycle: 0 if the pad or any node drove it, else 1
    owned: list  # one per cycle: was the pad driving the bus
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
    halt, the bus resolved after every cycle from the pad and the nodes and
    fed back to gpio_in for the next. The pad driving a 1 against a node's 0
    is a fight, which no CAN node ever has: it fails here."""

    def __init__(self, program, tx_data, nodes=(), drain=True, host=None):
        self.cpu = CPU(load_program(program), gpio_in=1, tx_data=list(tx_data))
        self.nodes = list(nodes)
        self.drain, self.host = drain, host
        self.line = 1
        self.lines, self.owned, self.driven, self.received, self.stalls = [], [], [], [], []
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
            assert not (pad == 1 and 0 in drives), f"cycle {cpu.cycle}: the pad drives a 1 against a node's dominant 0"
            self.line = 0 if pad == 0 or 0 in drives else 1
            cpu.gpio_in[CAN_TX] = self.line
            self.lines.append(self.line)
            self.owned.append(driving)
            self.driven.append(drives)
            self.stalls.append(cpu.stalled)
            if self.drain and cpu.rx_fifo:
                self.received.append(cpu.rx_fifo.pop(0))
        return self

    def result(self):
        return Run(self.lines, self.owned, self.driven, self.received, self.nodes, self.cpu, self.stalls, self.rx_peak, self.tx_peak)


def run(program, tx_data, nodes=None, cycles=2000, drain=True, host=None):
    """A Bus run for `cycles` or to the halt, as a Run, with one receiver on the bus unless told otherwise."""
    return Bus(program, tx_data, [Node()] if nodes is None else nodes, drain, host).go(cycles).result()


def cells(line, start, count=HEADER):
    """The bus from `start`, the SOF's edge, cut into `count` bits of BIT
    cycles: what a receiver with a perfect clock sees. Every cycle of a bit
    must hold the same level, so a bit that stretches or glitches fails here
    rather than decoding by luck."""
    bits = []
    for k in range(count):
        cell = line[start + k * BIT : start + (k + 1) * BIT]
        assert len(cell) == BIT, f"the bus ends inside bit {k}"
        assert len(set(cell)) == 1, f"bit {k} ({NAMES[k]}) not held for {BIT} cycles: {cell}"
        bits.append(cell[0])
    return bits


def show(wave, r):
    wave.add("bus", r.line, group="bus")
    wave.add("pad drives", [int(o) for o in r.owned], group="bus")
    for i in range(len(r.nodes)):
        wave.add(f"node {i} drives", ["-" if d[i] is None else str(d[i]) for d in r.driven], group="bus")
    labels = ["-"] * len(r.line)
    sof = r.line.index(0)
    for k, name in enumerate(NAMES):
        at = sof + k * BIT + SAMPLE - 1
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
        r = run(TX, header_bytes(IDENT), [Glitch(at)])
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
