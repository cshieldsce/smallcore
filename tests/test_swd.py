"""SWD host checks, staged the way SPI and I2C were: the smallest piece of the
protocol first, and the core is assumed able until a piece proves otherwise.
programs/swd_request.asm grows one stage at a time:

  1. the request: the host owns SWDIO and clocks the 8-bit request out, LSB
     first, the host having composed the byte, parity and all;
  2. the turnaround: after the park bit the host lets go of SWDIO for one
     clock, so the target can take the line;
  3. the ACK: the host samples the target's three ACK bits on the next three
     clocks and PUSHes them;
  4. the decision: a second turnaround gives the host the line back, then
     OK goes on (to where the data phase will be), WAIT sends the request
     again, when the host supplies it again, FAULT exits, the PUSH having
     reported it.

No data yet. The bench is the wire and the target. The wire is SWDIO resolved
every cycle from the pad (gpio and gpio_oe), the target and a pull-up. The
target samples SWDIO on every rising edge of SWCLK, reads the first eight as
a request packet, start, stop and park bits and the parity included, takes
the line on the ninth, the turnaround's, with ACK[0], moves to ACK[1] and
ACK[2] on the next two, lets go on the twelfth, and after the thirteenth, the
host's turnaround, listens for the next request."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
REQUEST = PROGRAMS / "swd_request.asm"
SWDIO, SWCLK = 0, 1  # the same pin numbers on gpio (the pad) and gpio_in (the wire): SWDIO is the shift pin
HIGH = 4  # cycles SWCLK is high per bit, and low
BIT = 2 * HIGH
CLOCKS = 8 + 1 + 3 + 1  # rises of SWCLK per transaction: the request, the turnaround, the ACK, the turnaround back
OK, WAIT, FAULT = 1, 2, 4  # the ACK, ACK[0] first on the wire
ACK_SHIFT = 5  # where three LSB-first samples land in an 8-bit register: bits 7:5, the ACK << 5


def request(apndp, rnw, a):
    """The 8-bit SWD request as the host writes it into the TX FIFO, bit 0 first
    on the wire: Start 1, APnDP, RnW, A2, A3, the parity of those four, Stop 0,
    Park 1. `a` is A[3:2], the register address the target sees, 0..3."""
    a2, a3 = a & 1, a >> 1
    parity = apndp ^ rnw ^ a2 ^ a3
    return 1 | apndp << 1 | rnw << 2 | a2 << 3 | a3 << 4 | parity << 5 | 0 << 6 | 1 << 7


def wire_bits(byte):
    """The order the bits of `byte` appear on the wire: LSB first."""
    return [(byte >> i) & 1 for i in range(8)]


class Packet(NamedTuple):
    apndp: int
    rnw: int
    a: int  # A[3:2]


FIELDS = ("start", "apndp", "rnw", "a2", "a3", "par", "stop", "park")
RISES = FIELDS + ("trn", "ack0", "ack1", "ack2", "trn")


def target_decode(bits):
    """What a target makes of eight bits sampled on eight rising edges of SWCLK:
    a request for a register, or a protocol error. Every fixed bit and the
    parity are checked, so a bit-order slip or a dropped bit fails here."""
    assert len(bits) == 8, f"{len(bits)} bits, not 8"
    start, apndp, rnw, a2, a3, parity, stop, park = bits
    assert start == 1, "no start bit"
    assert stop == 0, "no stop bit"
    assert park == 1, "no park bit"
    assert parity == apndp ^ rnw ^ a2 ^ a3, "parity error"
    return Packet(apndp, rnw, a2 | a3 << 1)


REQUESTS = [(apndp, rnw, a) for apndp in (0, 1) for rnw in (0, 1) for a in range(4)]  # every request there is


class Target:
    """A target on the wire. It follows the clock: on each rising edge of SWCLK
    it samples the line as it stood at the edge. A transaction is thirteen
    rises. The first eight samples are a request, decoded and appended to
    `seen` after the eighth. On the ninth rise, the turnaround's, the target
    takes the line with ACK[0] of the next answer in `acks` (the last one
    repeats), moves to ACK[1] and ACK[2] on the next two rises, lets go on
    the twelfth, and after the thirteenth, the host's turnaround, it is ready
    for the next request. `drive` is what it puts on the wire: 0, 1 or None."""

    def __init__(self, acks=(OK,)):
        self.acks = list(acks)
        self.swclk = 1  # the clock as last seen: every pin is high out of reset
        self.rises = 0  # in this transaction
        self.samples = []
        self.seen = []
        self.drive = None

    def update(self, swdio, swclk):
        """Take the wire as it stood at the end of the last cycle; return the level to drive, or None."""
        if swclk and not self.swclk:
            self.rises += 1
            n = self.rises
            if n <= 8:
                self.samples.append(swdio)
                if n == 8:
                    self.seen.append(target_decode(self.samples))
            elif n <= 11:
                ack = self.acks[min(len(self.seen) - 1, len(self.acks) - 1)]
                self.drive = (ack >> (n - 9)) & 1
            elif n == 12:
                self.drive = None
            else:  # 13, the host's turnaround: whatever comes next is a new request
                self.rises, self.samples = 0, []
        self.swclk = swclk
        return self.drive


class Run(NamedTuple):
    swdio: list  # the wire, one level per cycle: the pad while it drives, else the target, else the pull-up
    swclk: list  # one level per cycle, as the host drove it
    owned: list  # one per cycle: was the pad driving SWDIO
    driven: list  # one per cycle: what the target drove, 0, 1 or None
    target: Target
    cpu: CPU


def run(tx_data, target=None, cycles=2000):
    """Run the program with `tx_data` waiting in the TX FIFO until it halts or
    `cycles` pass, the wire resolved after every cycle from the pad, the
    target and the pull-up, and fed back to gpio_in for the next. A pad
    driving against the target is a fight, which no working host ever has:
    it fails here."""
    target = target or Target()
    tx_data = [tx_data] if isinstance(tx_data, int) else list(tx_data)
    cpu = CPU(load_program(REQUEST), gpio_in=1, tx_data=tx_data)
    swdio, owned, driven = [], [], []
    line = 1
    while not cpu.halted and cpu.cycle < cycles:
        cpu.step()
        drive = target.update(line, cpu.gpio[SWCLK])
        driving = cpu.gpio_oe[SWDIO] == 1
        pad = cpu.gpio[SWDIO] if driving else None
        assert not (pad is not None and drive is not None and pad != drive), f"cycle {cpu.cycle}: the pad drives {pad} against the target's {drive}"
        line = pad if pad is not None else drive if drive is not None else 1
        cpu.gpio_in[SWDIO] = line
        swdio.append(line)
        owned.append(driving)
        driven.append(drive)
    return Run(swdio, cpu.pin_trace(SWCLK), owned, driven, target, cpu)


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def sampled(swdio, swclk):
    """What is taken on every rising edge of SWCLK, in order: the wire as it
    stood at the edge, the cycle before the one that shows the clock high. The
    first eight are the request, then the turnaround's, then the ACK's."""
    return [swdio[e - 1] for e in rising_edges(swclk)]


def show(wave, r):
    wave.add("swclk", r.swclk, group="host drives")
    wave.add("swdio", r.swdio, group="wire")
    wave.add("host owns", [int(o) for o in r.owned], group="wire")
    wave.add("target drives", ["-" if d is None else str(d) for d in r.driven], group="wire")
    labels = ["-"] * len(r.swdio)
    for i, edge in enumerate(rising_edges(r.swclk)):
        labels[edge] = RISES[i % CLOCKS]
    wave.add("rise", labels)


@pytest.fixture(params=REQUESTS, ids=lambda r: f"{'ap' if r[0] else 'dp'}_{'read' if r[1] else 'write'}_a{r[2]:02b}")
def packet(request):
    return Packet(*request.param)


@pytest.fixture(params=(OK, WAIT, FAULT), ids=("ok", "wait", "fault"))
def ack(request):
    return request.param


# --- stage 1: the request ------------------------------------------------------


def test_target_samples_the_request_lsb_first(packet, wave):
    """Every request a host can make reaches the target field for field: the
    eight samples are the byte's bits from bit 0 up, and decode back to the
    APnDP, RnW and A[3:2] the host asked for. Most requests are not
    palindromes, so MSB first would fail the start, stop or parity check."""
    byte = request(*packet)
    r = run(byte)
    show(wave, r)
    bits = sampled(r.swdio, r.swclk)[:8]
    assert bits == wire_bits(byte)
    assert target_decode(bits) == packet
    assert r.target.seen == [packet], "the target's own view"


def test_dp_write_to_a01_is_0xa9_on_the_wire():
    """One request by hand. A DP write to A[3:2] = 01: Start 1, APnDP 0, RnW 0,
    A2 1, A3 0, parity 1, Stop 0, Park 1 is 1 0 0 1 0 1 0 1 on the wire, the
    byte 0xA9 = 1010_1001 read from bit 0. Backwards it is 1 0 1 0 1 0 0 1: a
    bit-order slip cannot pass."""
    assert request(0, 0, 0b01) == 0xA9
    assert sampled(*run(0xA9)[:2])[:8] == [1, 0, 0, 1, 0, 1, 0, 1]


def test_swclk_rises_once_per_bit_and_idles_low():
    """Thirteen rising edges, eight for the request, one for the turnaround,
    three for the ACK and one for the turnaround back, and no other: SWCLK is
    low before the first, low again after the last, and stays there."""
    r = run(0xA9)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    assert len(ups) == CLOCKS, f"SWCLK rose at {ups}"
    assert len(downs) == CLOCKS and all(u < d for u, d in zip(ups, downs)), "each rise has its fall"
    assert r.swclk[0] == 0, "SWCLK idle low before the request"
    assert set(r.swclk[downs[-1]:]) == {0}, "SWCLK idle low after the transaction"


@pytest.mark.parametrize("byte", (0xA9, request(1, 1, 0b11), request(0, 1, 0b00)), ids=lambda b: f"{b:#04x}")
def test_each_bit_is_on_swdio_through_the_low_half_and_the_rising_edge(byte):
    """The target samples on the rise, so the bit must be there before it and
    hold through it: on SWDIO for the 4 low cycles before its rising edge and
    the cycle of the edge. Bits are 8 cycles apart, 4 low, 4 high, and the
    turnaround and ACK clocks keep the beat."""
    r = run(byte)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    assert [b - a for a, b in zip(ups, ups[1:])] == [BIT] * (CLOCKS - 1)
    assert [d - u for u, d in zip(ups, downs)] == [HIGH] * CLOCKS, "high half"
    for i, (bit, up) in enumerate(zip(wire_bits(byte), ups)):
        assert r.swdio[up - HIGH:up + 1] == [bit] * (HIGH + 1), f"bit {i} ({FIELDS[i]}) on the wire"
        if i:
            assert (r.swclk[up - HIGH - 1], r.swclk[up - HIGH]) == (1, 0), f"bit {i}: the clock did not drop as the bit landed"


def test_swdio_is_stable_while_swclk_is_high_during_the_request():
    r = run(0xA9)
    park = rising_edges(r.swclk)[7]
    for i in range(1, park + HIGH):
        if r.swclk[i] == 1:
            assert r.swdio[i] == r.swdio[i - 1], f"SWDIO changed at cycle {i} with SWCLK high"


def test_program_waits_for_the_request_with_the_line_idle():
    """Nothing happens until the host writes a request: the program stalls on
    its PULL with SWCLK low and SWDIO high, then sends the byte that arrives."""
    cpu = CPU(load_program(REQUEST), gpio_in=1)
    cpu.run_cycles(20)
    assert cpu.stalled and cpu.gpio[SWCLK] == 0 and cpu.gpio[SWDIO] == 1 and cpu.gpio_oe[SWDIO] == 1
    cpu.tx_fifo.append(0xA9)
    cpu.run()
    assert [cpu.pin_trace(SWDIO)[e] for e in rising_edges(cpu.pin_trace(SWCLK))][:8] == wire_bits(0xA9)


# --- stage 2: the turnaround ---------------------------------------------------


def test_host_owns_swdio_through_the_park_bit_and_lets_go_as_that_clock_falls(wave):
    """The host drives SWDIO on every cycle of the request, through the park
    bit's rising edge and its high half, and lets go on the edge that drops
    SWCLK after it: from there the pad is not driving until the turnaround
    back. The line reads high meanwhile, from the pull-up, until the target
    takes it: a bench that only watched levels could not tell, `owned` is
    gpio_oe."""
    r = run(0xA9)
    show(wave, r)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    release, trn, retake = downs[7], ups[8], downs[12]  # the park bit's clock drops; the turnaround's rise; the turnaround back's clock drops
    assert release == ups[7] + HIGH
    assert all(r.owned[:release]), "the host let go before the park bit was clocked"
    assert not any(r.owned[release:retake]), "the host took the line back early"
    assert set(r.swdio[release:trn]) == {1}, "the pull-up holds the line high while nobody drives"


def test_turnaround_is_one_clock_with_nobody_driving():
    """The ninth rising edge of SWCLK is the turnaround's: neither side drives
    through its low half, and the target takes the line on the edge."""
    r = run(0xA9)
    trn = rising_edges(r.swclk)[8]
    assert not any(r.owned[trn - HIGH:trn]) and set(r.driven[trn - HIGH:trn]) == {None}, "somebody drove SWDIO through the turnaround"
    assert r.swdio[trn - 1] == 1, "the pull-up's 1 is what the turnaround's edge finds"
    assert r.driven[trn] is not None, "the target took the line on the turnaround's edge"


def test_letting_go_is_open_drain_with_a_one_the_park_bit_left():
    """How the host lets go: one CONFIG word makes SWDIO open-drain, and the 1
    the park bit left on gpio[0] is what an open-drain pin does not drive. The
    same word drops SWCLK. Nothing is written to the pin itself."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(REQUEST)]
    od01 = isa["config"]["open_drain01"]["field"]
    release, retake = [i for i, w in enumerate(words) if w.op == "CONFIG"]
    assert words[release].args == (od01, 1) and words[release].side == (SWCLK, 0)
    assert words[retake].args == (od01, 0) and words[retake].side == (SWCLK, 0), "taken back the same way"
    assert words[release - 1].op == "SET" and words[release - 1].args == (SWCLK, 1), "right after the park bit's clock"
    assert not any(w.op == "SET" and w.args[0] == SWDIO for w in words), "no SET on SWDIO: SHIFT_OUT and the pad mode do it all"


# --- stage 3: the ACK ----------------------------------------------------------


def test_ack_reaches_the_host_in_the_top_three_bits(ack, wave):
    """The target's OK, WAIT or FAULT arrives whole: three SHIFT_INs on the
    three rises after the turnaround, then one PUSH. LSB first, a sample
    enters at bit 7 and walks right, so three of them sit in bits 7:5 and the
    host reads the ACK as the byte >> 5: 0x20, 0x40, 0x80. OK and FAULT are
    mirror images, so ACK[0] first is proven, not assumed."""
    r = run(0xA9, Target([ack]))
    show(wave, r)
    assert r.target.seen == [Packet(0, 0, 0b01)], "the target answered the request it was asked"
    assert r.cpu.rx_fifo[0] == ack << ACK_SHIFT
    assert r.cpu.in_shift_reg == ack << ACK_SHIFT
    assert r.cpu.rx_fifo[0] >> ACK_SHIFT == ack


def test_ack_bits_are_sampled_on_the_three_rises_after_the_turnaround(ack):
    """Each ACK bit is on the wire from the rise before its own, where the
    target put it, and the host takes it on its own rise: the three samples
    after the turnaround's are ACK[0], ACK[1], ACK[2]."""
    r = run(0xA9, Target([ack]))
    taken = sampled(r.swdio, r.swclk)
    assert taken[9:12] == [(ack >> i) & 1 for i in range(3)]
    assert taken[8] == 1, "the turnaround's edge finds the pull-up"


def test_target_drives_from_the_turnaround_to_the_last_ack_clock_and_no_one_fights():
    """The target owns the line from the turnaround's rise to the third ACK
    rise, when it lets go; the host does not drive between its release and
    the turnaround back, so there is no cycle where both drive (run() would
    have failed on one)."""
    r = run(0xA9, Target([FAULT]))
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    trn, last, retake = ups[8], ups[11], downs[12]
    assert set(r.driven[:trn]) == {None}
    assert None not in r.driven[trn:last], "the target let go during the ACK"
    assert set(r.driven[last:]) == {None}, "the target kept the line after the ACK"
    assert not any(r.owned[trn:retake]), "the host drove while the target had the line"
    assert not any(a and (b is not None) for a, b in zip(r.owned, r.driven)), "both drove at once"


def test_ack_is_pushed_once_as_the_last_ack_clock_falls():
    """Nothing is in the RX FIFO until the third ACK bit is in; the PUSH lands
    on the edge that drops SWCLK after it, and nothing else is pushed for the
    rest of the transaction: the host reads one byte."""
    cpu = CPU(load_program(REQUEST), gpio_in=1, tx_data=[0xA9])
    target = Target([OK])
    line, seen = 1, []
    while not cpu.halted and cpu.cycle < 400:
        cpu.step()
        drive = target.update(line, cpu.gpio[SWCLK])
        line = cpu.gpio[SWDIO] if cpu.gpio_oe[SWDIO] else drive if drive is not None else 1
        cpu.gpio_in[SWDIO] = line
        seen.append((cpu.gpio[SWCLK], list(cpu.rx_fifo)))
    assert cpu.halted
    swclk = [c for c, _ in seen]
    push = falling_edges(swclk)[11]  # the third ACK clock drops
    assert all(fifo == [] for _, fifo in seen[:push]), "pushed early"
    assert seen[push] == (0, [OK << ACK_SHIFT])
    assert all(fifo == [OK << ACK_SHIFT] for _, fifo in seen[push:]), "pushed again"


# --- stage 4: the decision -------------------------------------------------------


def test_turnaround_back_gives_the_host_the_line_before_it_decides(ack):
    """After the ACK one more clock with nobody driving, the thirteenth rise,
    and on the edge that drops it the host takes SWDIO back: push-pull again,
    driving the 1 that was on the pin all along. Whatever the ACK, the host
    owns an idle line, SWDIO high and SWCLK low, when it acts on it."""
    r = run(0xA9, Target([ack]), cycles=300)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    trn, retake = ups[12], downs[12]
    assert retake == trn + HIGH
    assert not any(r.owned[trn - HIGH:trn]) and set(r.driven[trn - HIGH:trn + HIGH]) == {None}, "somebody drove through the turnaround back"
    assert r.swdio[trn - 1] == 1, "the pull-up's 1 is what the turnaround back's edge finds"
    assert all(r.owned[retake:retake + BIT]), "the host did not take the line back"
    assert set(r.swdio[retake:retake + BIT]) == {1} and set(r.swclk[retake:retake + HIGH]) == {0}


def test_ok_ends_the_transaction_with_the_host_owning_the_line(wave):
    """OK: the program goes on to where the data phase will be, which for now
    is the end. Thirteen clocks, one ACK byte, halted with SWDIO driven high
    and SWCLK low, ready for the next request."""
    r = run(0xA9, Target([OK]))
    show(wave, r)
    assert r.cpu.halted
    assert r.target.seen == [Packet(0, 0, 0b01)]
    assert r.cpu.rx_fifo == [OK << ACK_SHIFT]
    assert len(rising_edges(r.swclk)) == CLOCKS
    assert r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio[SWDIO] == 1 and r.cpu.gpio[SWCLK] == 0


def test_wait_sends_the_request_again_when_the_host_supplies_it_again(wave):
    """WAIT: the target was not ready, the host asks again. The core cannot
    keep a copy of the request (SHIFT_OUT empties shift_reg and nothing
    reloads it but PULL), so the retry is a JMP back to the PULL and the host
    pushes the request again; here it queued it twice up front. The target
    sees the same request twice and answers WAIT then OK; the host reads
    0x40 then 0x28: OK in bits 7:5 with the WAIT's bit walked down to bit 3,
    since in_shift_reg keeps shifting. Two transactions, 26 clocks."""
    r = run([0xA9, 0xA9], Target([WAIT, OK]))
    show(wave, r)
    assert r.cpu.halted
    assert r.target.seen == [Packet(0, 0, 0b01)] * 2
    assert r.cpu.rx_fifo == [WAIT << ACK_SHIFT, OK << ACK_SHIFT | WAIT << (ACK_SHIFT - 3)]
    assert [b >> ACK_SHIFT for b in r.cpu.rx_fifo] == [WAIT, OK], "the host reads the ACK as the byte >> 5 either way"
    assert len(rising_edges(r.swclk)) == 2 * CLOCKS
    assert r.cpu.tx_fifo == [], "both requests were consumed"


def test_wait_with_no_second_request_holds_the_line_idle_on_the_pull():
    """WAIT with nothing more from the host: the program is back on its PULL,
    not halted, SWDIO driven high and SWCLK low, and stays there. A host that
    wants to give up simply does not push again; the WAIT it read says why."""
    r = run(0xA9, Target([WAIT]), cycles=400)
    assert not r.cpu.halted and r.cpu.stalled
    assert decode(r.cpu.program[r.cpu.pc], r.cpu.isa).op == "PULL"
    assert r.cpu.rx_fifo == [WAIT << ACK_SHIFT]
    assert len(rising_edges(r.swclk)) == CLOCKS, "no clock without a request"
    assert r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio[SWDIO] == 1 and r.cpu.gpio[SWCLK] == 0
    assert set(r.swdio[-100:]) == {1} and set(r.swclk[-100:]) == {0} and all(r.owned[-100:])


def test_fault_exits_after_the_push_reported_it():
    """FAULT: the transaction is over and no retry would help; the host must
    clear the error itself. The program halts after the turnaround back with
    the FAULT in the RX FIFO, the request sent once, thirteen clocks."""
    r = run([0xA9, 0xA9], Target([FAULT]))
    assert r.cpu.halted
    assert r.cpu.rx_fifo == [FAULT << ACK_SHIFT]
    assert r.target.seen == [Packet(0, 0, 0b01)]
    assert len(rising_edges(r.swclk)) == CLOCKS
    assert r.cpu.tx_fifo == [0xA9], "the second request was not sent"


def issued(program, tx_data, target):
    """The addresses of the words a run issued, in order."""
    cpu = CPU(program, gpio_in=1, tx_data=tx_data)
    line, pcs = 1, []
    while not cpu.halted and cpu.cycle < 400:
        if cpu.counter == 0 and not cpu.stalled:
            pcs.append(cpu.pc)
        cpu.step()
        drive = target.update(line, cpu.gpio[SWCLK])
        line = cpu.gpio[SWDIO] if cpu.gpio_oe[SWDIO] else drive if drive is not None else 1
        cpu.gpio_in[SWDIO] = line
    return pcs


def test_the_three_answers_take_three_paths():
    """OK, WAIT and FAULT leave the branch by different words. The branch is
    five words after the turnaround back: SKIP 5, 0 over a JMP to the data
    label for OK (bit 5 set), SKIP 6, 0 over a JMP to the request for WAIT
    (bit 6), and a JMP to the end for FAULT, or for no ACK bit at all. The
    data label and the end coincide until there is a data phase. SKIP sees
    one bit at a time, so a three-way decision is two SKIPs and three JMPs:
    the cost of branching on a 3-bit field with this ISA, on record."""
    isa = load_isa()
    program = load_program(REQUEST)
    words = [decode(w, isa) for w in program]
    (pull,) = [i for i, w in enumerate(words) if w.op == "PULL"]
    _, retake = [i for i, w in enumerate(words) if w.op == "CONFIG"]
    skip_ok, jmp_data, skip_wait, jmp_retry, jmp_done = range(retake + 1, retake + 6)
    assert words[skip_ok] == decode(program[skip_ok], isa) and words[skip_ok].op == "SKIP" and words[skip_ok].args == (ACK_SHIFT, 0)
    assert words[jmp_data].op == "JMP" and words[jmp_data].args == (len(words),), "OK: on to the data phase, the end for now"
    assert words[skip_wait].op == "SKIP" and words[skip_wait].args == (ACK_SHIFT + 1, 0)
    assert words[jmp_retry].op == "JMP" and words[jmp_retry].args == (pull,), "WAIT: the request again"
    assert words[jmp_done].op == "JMP" and words[jmp_done].args == (len(words),), "FAULT: the end"
    assert jmp_done == len(words) - 1

    ok = issued(program, [0xA9], Target([OK]))
    wait = issued(program, [0xA9, 0xA9], Target([WAIT, OK]))
    fault = issued(program, [0xA9], Target([FAULT]))
    assert jmp_data in ok and skip_wait not in ok and jmp_done not in ok
    assert jmp_retry in wait and wait.count(pull) == 2 and jmp_data in wait, "WAIT went round once, then OK went on"
    assert jmp_done in fault and jmp_data not in fault and jmp_retry not in fault


def test_program_is_two_words_per_bit_plus_the_turnarounds_the_push_and_the_branch():
    """Two words per bit, out or in, SPI's and I2C's shape: SHIFT_OUT with the
    clock low and SET with it high for the request, SET with the clock low
    and SHIFT_IN raising it for the ACK. No CONFIG shift_dir, because the
    reset configuration, LSB first, is SWD's. Each turnaround is two words,
    let go or take back and a clock; the PUSH drops the last ACK clock; the
    branch is five."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(REQUEST)]
    assert len(words) == 2 + 8 * 2 + 2 + 3 * 2 + 1 + 2 + 5
    shift_dir = isa["config"]["shift_dir"]["field"]
    assert not any(w.op == "CONFIG" and w.args[0] == shift_dir for w in words)
    outs = [w for w in words if w.op == "SHIFT_OUT"]
    ins = [w for w in words if w.op == "SHIFT_IN"]
    (push,) = [w for w in words if w.op == "PUSH"]
    assert len(outs) == 8 and all(w.side == (SWCLK, 0) for w in outs)
    assert len(ins) == 3 and all(w.args == (SWDIO,) and w.side == (SWCLK, 1) for w in ins)
    assert push.side == (SWCLK, 0) and push.delay == 3, "the PUSH is the turnaround back's low half"
