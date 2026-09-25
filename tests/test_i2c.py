"""I2C master checks. The bench is the bus, two open-drain lines with
pull-ups, the master's pins on one end and a slave model on the other,
resolved every cycle from what each side drove on the cycle before. The
master drives a line while gpio_oe says so and lets go otherwise: with SDA
and SCL open-drain (open_drain 0b11) a 1 lets go, with them push-pull (the
reset) a 1 is driven, and the bus shows the difference. programs/i2c_write.asm
sends one byte: START, eight bits, the ACK clock, STOP. i2c_write_stretch.asm
is the same with a WAIT on SCL before every high phase, for a slave that
stretches the clock. i2c_write_addr_data.asm sends an address byte and a data
byte, and STOPs after a NACK on the address: a SKIP on the sampled bit."""

import random
from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, assemble, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
WRITE = PROGRAMS / "i2c_write.asm"
STRETCH = PROGRAMS / "i2c_write_stretch.asm"
ADDR_DATA = PROGRAMS / "i2c_write_addr_data.asm"
SDA, SCL = 0, 1  # the same pin numbers on gpio (what the master drives) and gpio_in (the bus)
PUSH_PULL, OPEN_DRAIN = 0, 1 << SDA | 1 << SCL  # open_drain masks: the reset, and both lines open-drain
PINS = ((PUSH_PULL, "push_pull"), (OPEN_DRAIN, "open_drain"))
BYTES = (0x00, 0x01, 0x55, 0x80, 0xA3, 0xFF)
ADDRESS = 0x50  # the slave's 7-bit address; a write to it starts with the byte ADDRESS << 1
DATA = 0x3C
HIGH = 4  # cycles SCL is high per clock
CLOCKS = 10  # rises of SCL in one byte's transaction: eight bits, the ACK clock and the STOP's


# --- the bus ------------------------------------------------------------------


def resolve(drives):
    """One line: 0 if anyone pulls it low, else 1, from a driver or the
    pull-up. A 0 against a 1 is a fight: the level is what the push-pull
    driver forces (the master is the only one there is), and the fight is
    reported."""
    fight = 0 in drives and 1 in drives
    return (1 if fight else 0 if 0 in drives else 1), fight


class Slave:
    """An I2C slave, open-drain like the master: it only ever pulls a line
    low or lets go. It follows the bus one cycle behind. START and STOP are
    SDA moving while SCL is high, a bit is SDA on a rising edge of SCL.
    After eight bits it holds SDA low through the ninth clock (ACK) if the
    byte is for it, and after every falling edge of SCL it may hold SCL low
    for `stretch` cycles, an int or a function of the edge count."""

    def __init__(self, address=None, stretch=0):
        self.address = address  # None: ACK every byte. Else ACK an address byte that names it for a write, and data after one
        self.stretch = stretch
        self.events = []  # "START", (byte, acked), "STOP", in bus order
        self.sda = self.scl = 1  # the bus as last seen
        self.bits = []
        self.active = self.first = self.selected = self.acking = False
        self.falls = self.hold = 0
        self.sda_drive = None

    def update(self, sda, scl):
        """Take the bus as it stood at the end of the last cycle; return (sda, scl): 0 to pull low, None to let go."""
        if scl and self.scl and sda != self.sda:
            if sda == 0:  # START, or a repeated START
                self.active, self.first, self.acking = True, True, False
                self.bits, self.sda_drive = [], None
                self.selected = self.address is None
                self.events.append("START")
            else:  # STOP
                self.active = False
                self.events.append("STOP")
        elif self.active and scl and not self.scl and not self.acking and len(self.bits) < 8:  # SCL rose
            self.bits.append(sda)
        elif self.active and not scl and self.scl:  # SCL fell
            self.falls += 1
            if self.acking:  # the ACK clock is over
                self.acking, self.sda_drive, self.bits = False, None, []
            elif len(self.bits) == 8:
                byte = int("".join(map(str, self.bits)), 2)
                if self.address is None:
                    ack = True
                elif self.first:
                    ack = self.selected = byte == self.address << 1
                else:
                    ack = self.selected
                self.first = False
                self.events.append((byte, ack))
                self.acking, self.sda_drive = True, 0 if ack else None
            if self.selected:
                self.hold = self.stretch(self.falls) if callable(self.stretch) else self.stretch
        self.sda, self.scl = sda, scl
        scl_drive = 0 if self.hold else None
        self.hold = max(self.hold - 1, 0)
        return self.sda_drive, scl_drive


class Run(NamedTuple):
    sda: list  # the bus, one level per cycle, None on a fight
    scl: list
    fights: list  # (cycle, line) where a 0 was driven against a 1
    samples: list  # cycles the master sampled SDA (a SHIFT_IN issued)
    waits: int  # cycles the master spent stalled on a WAIT
    slave: Slave
    cpu: CPU


def run(program, tx_data, slave=None, open_drain=OPEN_DRAIN, before=None, cycles=2000):
    """Run a program on the bus until it halts or `cycles` pass, the master's
    pins configured by the `open_drain` mask, `before(cpu)` acting on the CPU
    before each cycle. The pad is gpio and gpio_oe: gpio[line] on the bus
    while gpio_oe[line] is 1, nothing while it is 0."""
    slave = slave or Slave()
    cpu = CPU(program if isinstance(program, list) else load_program(program), gpio_in=1, open_drain=open_drain,
              tx_data=tx_data)
    bus = [1, 1]
    sda, scl, fights, samples, waits = [], [], [], [], 0
    while not cpu.halted and cpu.cycle < cycles:
        drives = slave.update(*bus)
        for line in (SDA, SCL):
            bus[line], fight = resolve((cpu.gpio[line] if cpu.gpio_oe[line] else None, drives[line]))
            cpu.gpio_in[line] = bus[line]
            if fight:
                fights.append((cpu.cycle, line))
            (sda, scl)[line].append(None if fight else bus[line])
        instr = decode(cpu.program[cpu.pc], cpu.isa)
        if cpu.counter == 0 and instr.op == "SHIFT_IN":
            samples.append(cpu.cycle)
        if before:
            before(cpu)
        cpu.step()
        waits += cpu.stalled and instr.op == "WAIT"
    return Run(sda, scl, fights, samples, waits, slave, cpu)


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def moves(trace):
    return [i for i in range(1, len(trace)) if trace[i] != trace[i - 1]]


def start_and_stop(sda, scl):
    """The cycles SDA falls and rises while SCL is high."""
    (start,) = [c for c in falling_edges(sda) if scl[c] and scl[c - 1]]
    (stop,) = [c for c in rising_edges(sda) if scl[c] and scl[c - 1]]
    return start, stop


def wire_bits(byte):
    return [(byte >> i) & 1 for i in range(7, -1, -1)]


def other(address):
    """A 7-bit address that is not `address`."""
    return (address + 1) & 0x7F


def show(wave, r):
    """The bus, both sides' drives and the master's samples, for the SVG."""
    wave.add("sda", r.sda, group="bus")
    wave.add("scl", r.scl, group="bus")
    wave.add("sda out", r.cpu.pin_trace(SDA), group="master drives")
    wave.add("scl out", r.cpu.pin_trace(SCL), group="master drives")
    wave.add("sample", ["ack" if c in r.samples else "-" for c in range(len(r.sda))])


# --- programs/i2c_write.asm: what the master drives ---------------------------


@pytest.mark.parametrize("byte", BYTES, ids=lambda b: f"{b:#04x}")
def test_master_drives_start_the_byte_msb_first_a_ninth_clock_and_stop(byte, wave):
    """Seen from the master's own pins: SDA falls while SCL is high, eight
    bits on the rising edges of SCL, a ninth clock with SDA let go (as far as
    a driven 1 is letting go), SDA rises while SCL is high, and SDA moves at
    no other time while SCL is high."""
    r = run(WRITE, [byte])
    sda, scl = r.cpu.pin_trace(SDA), r.cpu.pin_trace(SCL)
    show(wave, r)
    ups, downs = rising_edges(scl), falling_edges(scl)
    start, stop = start_and_stop(sda, scl)
    assert len(ups) == len(downs) == CLOCKS
    assert start < downs[0] and ups[-1] < stop
    assert [sda[c] for c in ups[:8]] == wire_bits(byte)
    assert sda[ups[8]] == 1, "the ninth clock is the slave's"
    assert all(scl[c] == 0 and scl[c - 1] == 0 for c in moves(sda) if c not in (start, stop))
    assert (sda[-1], scl[-1], r.cpu.halted) == (1, 1, True)
    assert len(r.cpu.program) == 2 + 8 * 3 + 4 + 3


def test_bit_period_is_8_cycles_sda_moves_2_after_scl_falls_and_2_before_it_rises():
    """Hold and setup: SDA never moves on an edge of SCL. 0xAA moves SDA on
    every bit, then for the ACK (let go) and for the STOP's setup."""
    r = run(WRITE, [0xAA])
    sda, scl = r.cpu.pin_trace(SDA), r.cpu.pin_trace(SCL)
    ups, downs = rising_edges(scl), falling_edges(scl)
    assert [u - d for d, u in zip(downs, ups)] == [HIGH] * CLOCKS, "low phases"
    assert [d - u for u, d in zip(ups, downs[1:])] == [HIGH] * (CLOCKS - 1), "high phases"
    assert [c for c in moves(sda) if scl[c] == 0] == [d + 2 for d in downs]
    assert r.cpu.cycle == 5 + 8 * 8 + 10 + 8  # config and PULL, the bits, the ACK clock, the STOP


# --- on the bus: the pins must be open-drain for the slave's ACK -------------


@pytest.mark.parametrize("open_drain", [p for p, _ in PINS], ids=[n for _, n in PINS])
@pytest.mark.parametrize("byte", BYTES, ids=lambda b: f"{b:#04x}")
def test_slave_receives_the_byte_from_push_pull_or_open_drain_pins(open_drain, byte):
    """Master to slave needs no third state: the slave sees START, eight bits
    it samples while SCL is high, STOP, whichever way the pins are set."""
    r = run(WRITE, [byte], Slave(), open_drain)
    assert r.slave.events == ["START", (byte, True), "STOP"]


def test_push_pull_pins_fight_the_slave_through_the_ack_clock_and_cannot_see_the_ack(wave):
    """Why the pins have a mode. Push-pull, the reset, drives a 0 or a 1 every
    cycle, so 'let go of SDA' is `SET 0, 1`, a driven 1. The slave answers
    the byte by pulling SDA low through the ninth clock, against that 1: a
    fight for every cycle the slave holds, in which the master reads its own
    driver. Its sample says NACK, and a slave that does not answer at all
    looks exactly the same."""
    acked = run(WRITE, [0xA3], Slave(), PUSH_PULL)
    show(wave, acked)
    (sample,) = acked.samples
    cycles = [c for c, _ in acked.fights]
    assert acked.slave.events == ["START", (0xA3, True), "STOP"], "the slave took the byte and acked"
    assert all(line == SDA for _, line in acked.fights)
    assert cycles == list(range(cycles[0], cycles[-1] + 1)) and len(cycles) >= 7, "one fight, the slave's whole ACK"
    assert cycles[0] < sample < cycles[-1], "sampled mid-fight"
    assert acked.cpu.rx_fifo == [1], "read as NACK"

    silent = run(WRITE, [0xA3], Slave(address=other(0xA3 >> 1)), PUSH_PULL)  # not its address: no ACK
    assert silent.slave.events == ["START", (0xA3, False), "STOP"] and silent.fights == []
    assert silent.cpu.rx_fifo == [1]
    assert [1 if l is None else l for l in acked.sda] == silent.sda, "the master saw the same SDA either way"


@pytest.mark.parametrize("byte", BYTES, ids=lambda b: f"{b:#04x}")
def test_open_drain_pins_let_go_on_a_1_and_the_master_sees_the_ack(byte, wave):
    """The same words with SDA and SCL open-drain: gpio_oe drops on every 1,
    so there is no fight, the slave's ACK is on the wire when the master
    samples, and a NACK is a 1 the pull-up holds. The master never wants to
    drive a line high, so the mode is set once for the whole protocol."""
    acked = run(WRITE, [byte], Slave(), OPEN_DRAIN)
    if byte == 0xA3:
        show(wave, acked)
    ups, downs = rising_edges(acked.cpu.pin_trace(SCL)), falling_edges(acked.cpu.pin_trace(SCL))
    (sample,) = acked.samples
    assert acked.fights == [] and acked.slave.events == ["START", (byte, True), "STOP"]
    assert ups[8] <= sample < downs[9], "sampled in the ACK clock"
    assert acked.sda[sample] == 0 and acked.cpu.rx_fifo == [0], "ACK"
    assert acked.cpu.gpio_oe[SDA] == 0 and acked.cpu.gpio[SDA] == 1, "let go at the end, not driven high"
    nacked = run(WRITE, [byte], Slave(address=other(byte >> 1)), OPEN_DRAIN)
    assert nacked.fights == [] and nacked.slave.events == ["START", (byte, False), "STOP"]
    assert nacked.cpu.rx_fifo == [1], "NACK"


def test_open_drain_pins_drive_their_zeros_and_release_their_ones():
    """Every cycle of the transfer: a 0 in gpio is on the bus with gpio_oe 1,
    a 1 is gpio_oe 0 and the bus is the pull-up's or the slave's. The other
    two pins, push-pull, keep driving."""
    r = run(STRETCH, [0xA3], Slave(stretch=5), OPEN_DRAIN)
    assert r.cpu.open_drain == [1, 1, 0, 0] and r.cpu.gpio_oe == [0, 0, 1, 1]
    for cycle, (levels, sda, scl) in enumerate(zip(r.cpu.trace, r.sda[1:], r.scl[1:]), start=1):  # the bus follows one cycle behind
        for line, bus in ((SDA, sda), (SCL, scl)):
            if levels[line] == 0:
                assert bus == 0, f"cycle {cycle}: a driven 0 is on the bus"
    assert any(l == 1 and b == 0 for l, b in zip(r.cpu.pin_trace(SCL), r.scl[1:])), "the slave held SCL through a release"


# --- programs/i2c_write_stretch.asm: WAIT on SCL before every high phase ------


def test_stretch_program_is_the_plain_one_with_a_wait_before_every_high_phase():
    """One word per clock: `SET 1, 1 [3]` becomes `SET 1, 1` then `WAIT 1, 1
    [2]`, and one more for the ACK clock, whose sample can no longer ride on
    the rise. With a slave that never stretches, the bus is the same, cycle
    for cycle, and so is what both sides took from it."""
    isa = load_isa()
    plain, stretch = load_program(WRITE, isa), load_program(STRETCH, isa)
    waits = [decode(w, isa) for w in stretch if decode(w, isa).op == "WAIT"]
    assert len(stretch) == len(plain) + CLOCKS + 1 and len(waits) == CLOCKS
    assert all(w.args == (SCL, 1) and w.side is None for w in waits)
    for byte in BYTES:
        a, b = run(WRITE, [byte]), run(STRETCH, [byte])
        assert (b.sda, b.scl) == (a.sda, a.scl)
        assert (b.slave.events, b.cpu.rx_fifo, b.waits) == (a.slave.events, [0], 0)


@pytest.mark.parametrize("stretch", (1, 3, 4, 5, 8, 20))
def test_master_waits_for_a_slave_that_stretches_the_clock(stretch, wave):
    """The slave holds SCL low for `stretch` cycles after each falling edge.
    The master's low phase already covers three of them (its release reaches
    the bus on the fourth), so the WAIT stalls for the rest, every high phase
    is still HIGH cycles from the rise the bus shows, and the byte, the ACK
    and the STOP are all right. The same WAIT that found a start bit."""
    r = run(STRETCH, [0xA3], Slave(stretch=stretch))
    if stretch == 8:
        show(wave, r)
    over = max(stretch - 3, 0)
    ups, downs = rising_edges(r.scl), falling_edges(r.scl)
    assert r.fights == [] and r.slave.events == ["START", (0xA3, True), "STOP"] and r.cpu.rx_fifo == [0]
    assert [d - u for u, d in zip(ups, downs[1:])] == [HIGH] * (CLOCKS - 1), "high phases, from the real rise"
    assert [u - d for d, u in zip(downs, ups)] == [HIGH + over] * CLOCKS, "low phases, as long as the slave says"
    assert r.waits == CLOCKS * over
    assert r.cpu.cycle == run(WRITE, [0xA3]).cpu.cycle + CLOCKS * over


def test_master_follows_a_slave_that_stretches_a_different_amount_each_time():
    rng = random.Random(5)
    holds = [rng.choice((0, 0, 2, 5, 9, 17)) for _ in range(CLOCKS)]
    r = run(STRETCH, [0x5C], Slave(stretch=lambda fall: holds[fall - 1]))
    ups, downs = rising_edges(r.scl), falling_edges(r.scl)
    assert r.fights == [] and r.slave.events == ["START", (0x5C, True), "STOP"] and r.cpu.rx_fifo == [0]
    assert [d - u for u, d in zip(ups, downs[1:])] == [HIGH] * (CLOCKS - 1)
    assert [u - d for d, u in zip(downs, ups)] == [HIGH + max(h - 3, 0) for h in holds]
    assert r.waits == sum(max(h - 3, 0) for h in holds) > 0


def test_push_pull_pins_drive_scl_high_through_the_slaves_stretch():
    """The same fight on the other line. Push-pull, the master lets go of SCL
    with a driven 1 while the slave holds it low: a slave that holds for 8
    cycles after each fall is still holding through every high phase, so
    every cycle the master drives SCL high from the first fall on is a
    fight. The WAIT reads the master's own 1 and never stalls, the transfer
    takes exactly as long as with no stretch, and the ACK is unseen as
    before. The WAIT works, the mode is wrong."""
    r = run(STRETCH, [0xA3], Slave(stretch=8), PUSH_PULL)
    out = r.cpu.pin_trace(SCL)
    first = falling_edges(out)[0]
    assert [c for c, line in r.fights if line == SCL] == [c for c in range(first + 2, r.cpu.cycle) if out[c - 1] == 1]
    assert r.waits == 0
    assert r.cpu.cycle == run(WRITE, [0xA3]).cpu.cycle
    assert r.slave.events == ["START", (0xA3, True), "STOP"] and r.cpu.rx_fifo == [1]


def test_the_release_cannot_be_the_waits_own_side_effect():
    """`WAIT 1, 1, 1, 1`, let go of SCL and wait for it to rise in one word,
    never issues: the side effect lands on the edge the WAIT issues, and the
    WAIT issues once SCL is high, which the side effect was to make it. Two
    words per clock, then."""
    r = run(assemble("SET 1, 0\nWAIT 1, 1, 1, 1\nSET 0, 0"), [], Slave(), OPEN_DRAIN, cycles=50)
    assert r.cpu.stalled and decode(r.cpu.program[r.cpu.pc], r.cpu.isa).op == "WAIT"
    assert r.cpu.pin_trace(SCL)[-1] == 0 and r.scl[-1] == 0 and not r.cpu.halted


# --- programs/i2c_write_addr_data.asm: ACK, then data; NACK, then STOP -------


def test_write_to_the_addressed_slave_is_start_address_ack_data_ack_stop(wave):
    """The ACK path: `SKIP 0, 0` after the address byte's ACK clock steps
    over the `JMP stop` and the data byte follows, its low phase as long as
    without the two words (the PUSH gave up its delay to them)."""
    r = run(ADDR_DATA, [ADDRESS << 1, DATA], Slave(ADDRESS))
    show(wave, r)
    assert r.slave.events == ["START", (ADDRESS << 1, True), (DATA, True), "STOP"]
    assert r.cpu.rx_fifo == [0, 0] and r.fights == []
    ups, downs = rising_edges(r.scl), falling_edges(r.scl)
    assert len(ups) == 2 * (CLOCKS - 1) + 1
    assert [u - d for d, u in zip(downs, ups)] == [HIGH] * 9 + [HIGH + 2] + [HIGH] * 9, "the data byte's PULL adds two"
    isa = load_isa()
    program = load_program(ADDR_DATA, isa)
    assert len(program) == 2 * len(load_program(WRITE)) - 3
    ack = next(i for i, w in enumerate(program) if decode(w, isa).op == "PUSH")
    stop = len(program) - 3  # the STOP's three words end the program
    assert [decode(w, isa) for w in program[ack + 1:ack + 3]] == [decode(w, isa) for w in assemble(f"SKIP 0, 0\nJMP {stop}", isa)]
    assert decode(program[stop], isa) == decode(assemble("SET 0, 0 [1]")[0], isa), "the JMP's target is the STOP"


def test_after_a_nack_the_master_stops_and_keeps_the_data_byte(wave):
    """No slave at the address: the address byte is not acked, the sample is
    a 1, the SKIP falls into the JMP and the STOP follows one clock after
    the NACK: SDA low while SCL is low, SCL let go, SDA let go while SCL is
    high. Nothing is clocked to nobody and the data byte is still in the TX
    FIFO for the host to see, next to the NACK in the RX FIFO."""
    r = run(ADDR_DATA, [ADDRESS << 1, DATA], Slave(other(ADDRESS)))
    show(wave, r)
    assert r.slave.events == ["START", (ADDRESS << 1, False), "STOP"]
    assert r.cpu.rx_fifo == [1] and r.cpu.tx_fifo == [DATA] and r.fights == []
    ups, downs = rising_edges(r.scl), falling_edges(r.scl)
    assert len(ups) == CLOCKS, "the STOP's rise is the next after the ACK clock"
    start, stop = start_and_stop(r.sda, r.scl)
    assert ups[9] - downs[9] == 5 and stop == ups[9] + 2, "PUSH, SKIP, JMP, then the STOP's two words"
    assert r.cpu.halted and (r.sda[-1], r.scl[-1]) == (1, 1), "bus free"
    assert r.cpu.cycle == run(WRITE, [ADDRESS << 1], Slave(other(ADDRESS))).cpu.cycle + 1, "one byte's transfer and a cycle"


def test_the_host_may_hold_the_data_byte_until_the_ack_and_a_nack_never_asks_for_it():
    """A host that feeds the data byte only once it has seen the address
    acked: the master waits on PULL with SCL low, which the slave takes as
    the master's own time, and goes on when the byte comes. After a NACK
    the master never reaches the PULL: no hang, and the STOP goes out with
    the FIFO empty."""
    isa = load_isa()
    program = load_program(ADDR_DATA, isa)
    data_pull = [i for i, w in enumerate(program) if decode(w, isa).op == "PULL"][1]
    visited, stalls = set(), []

    def late_host(cpu):
        visited.add(cpu.pc)
        if cpu.rx_fifo == [0] and cpu.stalled:
            stalls.append(cpu.cycle)
            if len(stalls) == 7:
                cpu.tx_fifo.append(DATA)

    prompt = run(ADDR_DATA, [ADDRESS << 1, DATA], Slave(ADDRESS))
    late = run(ADDR_DATA, [ADDRESS << 1], Slave(ADDRESS), before=late_host)
    assert late.slave.events == prompt.slave.events == ["START", (ADDRESS << 1, True), (DATA, True), "STOP"]
    assert late.cpu.rx_fifo == [0, 0] and late.fights == [] and data_pull in visited
    assert late.cpu.cycle == prompt.cpu.cycle + 7 and late.scl[stalls[0]:stalls[-1] + 1] == [0] * 7
    visited.clear()
    stalls.clear()
    nacked = run(ADDR_DATA, [ADDRESS << 1], Slave(other(ADDRESS)), before=late_host)
    assert nacked.slave.events == ["START", (ADDRESS << 1, False), "STOP"] and nacked.cpu.halted
    assert data_pull not in visited and stalls == [] and nacked.cpu.tx_fifo == []
