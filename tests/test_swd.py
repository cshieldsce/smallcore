"""SWD host checks, staged the way SPI and I2C were: the smallest piece of the
protocol first, and the core is assumed able until a piece proves otherwise.
The programs grew one stage at a time:

  1. the request: the host owns SWDIO and clocks the 8-bit request out, LSB
     first, the host having composed the byte, parity and all;
  2. the turnaround: after the park bit the host lets go of SWDIO for one
     clock, so the target can take the line;
  3. the ACK: the host samples the target's three ACK bits on the next three
     clocks and PUSHes them;
  4. the decision: WAIT sends the request again, when the host supplies it
     again, FAULT exits, the PUSH having reported it, OK goes on; WAIT and
     FAULT take a turnaround back first, so the host owns the line again;
  5. the read data: on OK the target keeps the line and drives 32 data bits
     and a parity bit, the host samples them and PUSHes a byte per eight, then
     the parity in a fifth byte, then takes the line back;
  6. the write data: on OK, after the turnaround back, the host clocks out
     32 data bits and the parity from five more TX FIFO bytes, the parity
     the host's to compute.

programs/swd_read.asm is stages 1 to 5, programs/swd_write.asm 1 to 4 and 6:
the core cannot tell a read request from a write one, so they are two
programs, word for word the same through the third ACK sample.

The bench is the wire and the target. The wire is SWDIO resolved every cycle
from the pad (gpio and gpio_oe), the target and a pull-up. The target samples
SWDIO on every rising edge of SWCLK, reads the first eight as a request
packet, start, stop and park bits and the parity included, takes the line on
the ninth, the turnaround's, with ACK[0], moves to ACK[1] and ACK[2] on the
next two, and then either lets go on the twelfth and listens again after the
thirteenth, the host's turnaround, or, for a read it said OK to, drives the
data bits from the twelfth, the parity from the forty-fourth, lets go on the
forty-fifth and listens again after the forty-sixth. For a write it said OK
to it lets go on the twelfth and samples the host's data bits on rises
fourteen to forty-five and the parity on the forty-sixth."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
WRITE = PROGRAMS / "swd_write.asm"
READ = PROGRAMS / "swd_read.asm"
SWDIO, SWCLK = 0, 1  # the same pin numbers on gpio (the pad) and gpio_in (the wire): SWDIO is the shift pin
HIGH = 4  # cycles SWCLK is high per bit, and low
BIT = 2 * HIGH
CLOCKS = 8 + 1 + 3 + 1  # rises of SWCLK in a transaction without data: the request, the turnaround, the ACK, the turnaround back
READ_CLOCKS = 8 + 1 + 3 + 32 + 1 + 1  # in a read the target says OK to: no turnaround before the data, one after the parity
OK, WAIT, FAULT = 1, 2, 4  # the ACK, ACK[0] first on the wire
ACK_SHIFT = 5  # where three LSB-first samples land in an 8-bit register: bits 7:5, the ACK << 5
DP_WRITE = 0xA9  # request(0, 0, 0b01): a DP write to A[3:2] = 01
DP_READ = 0x8D  # request(0, 1, 0b01): a DP read of A[3:2] = 01
DATA = 0xE31D5396  # bytes 0x96, 0x53, 0x1D, 0xE3 from bit 0 up, none a palindrome, 17 ones: parity 1
WRITE_CLOCKS = 8 + 1 + 3 + 1 + 32 + 1  # in a write the target says OK to: the turnaround back, then the data and the parity from the host
REQ = {WRITE: DP_WRITE, READ: DP_READ}  # the request each program is for: a write with the read program would clock data the target never sends


def request(apndp, rnw, a):
    """The 8-bit SWD request as the host writes it into the TX FIFO, bit 0 first
    on the wire: Start 1, APnDP, RnW, A2, A3, the parity of those four, Stop 0,
    Park 1. `a` is A[3:2], the register address the target sees, 0..3."""
    a2, a3 = a & 1, a >> 1
    parity = apndp ^ rnw ^ a2 ^ a3
    return 1 | apndp << 1 | rnw << 2 | a2 << 3 | a3 << 4 | parity << 5 | 0 << 6 | 1 << 7


def wire_bits(value, bits=8):
    """The order the bits of `value` appear on the wire: LSB first."""
    return [(value >> i) & 1 for i in range(bits)]


def parity_of(value):
    return bin(value).count("1") & 1


def read_bytes(ack, data, parity=None):
    """What the host reads back from a read the target said OK to: the ACK in
    bits 7:5, the four data bytes from bit 0 up, and the parity as bit 7 of
    a fifth byte over data[31:25], in_shift_reg having shifted once more."""
    parity = parity_of(data) if parity is None else parity
    return [ack << ACK_SHIFT] + [(data >> (8 * i)) & 0xFF for i in range(4)] + [parity << 7 | data >> 25]


def write_bytes(data, parity=None):
    """What the host queues after the request for a write: the four data bytes
    from bit 0 up and a fifth byte whose bit 0 is the parity, computed by the
    host because the core cannot."""
    parity = parity_of(data) if parity is None else parity
    return [(data >> (8 * i)) & 0xFF for i in range(4)] + [parity]


class Packet(NamedTuple):
    apndp: int
    rnw: int
    a: int  # A[3:2]


FIELDS = ("start", "apndp", "rnw", "a2", "a3", "par", "stop", "park")


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
    it samples the line as it stood at the edge. The first eight samples of a
    transaction are a request, decoded and appended to `seen` after the
    eighth. On the ninth rise, the turnaround's, the target takes the line
    with ACK[0] of the next answer in `acks` (the last one repeats), moves to
    ACK[1] and ACK[2] on the next two rises. Then, for a read it said OK to,
    it drives `data` bit 0 up from the twelfth rise, one bit per rise, the
    parity (or `parity`, to inject a wrong one) from the forty-fourth, lets go
    on the forty-fifth and is ready for the next request after the
    forty-sixth, the host's turnaround. For a write it said OK to it lets go
    on the twelfth, the thirteenth is the host's turnaround, and it samples
    the host's data bits on the next 32 rises and the parity on the
    forty-sixth, appending (word, parity ok) to `written`. Otherwise it lets
    go on the twelfth and is ready after the thirteenth. `drive` is what it
    puts on the wire: 0, 1 or None."""

    def __init__(self, acks=(OK,), data=0, parity=None):
        self.acks = list(acks)
        self.data = data
        self.parity = parity_of(data) if parity is None else parity
        self.swclk = 1  # the clock as last seen: every pin is high out of reset
        self.rises = 0  # in this transaction
        self.samples = []
        self.seen = []
        self.written = []
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
            else:
                ack = self.acks[min(len(self.seen) - 1, len(self.acks) - 1)]
                reading = self.seen[-1].rnw == 1 and ack == OK
                writing = self.seen[-1].rnw == 0 and ack == OK
                if n <= 11:
                    self.drive = (ack >> (n - 9)) & 1
                elif reading and n <= 43:
                    self.drive = (self.data >> (n - 12)) & 1
                elif reading and n == 44:
                    self.drive = self.parity
                elif n == (45 if reading else 12):
                    self.drive = None
                elif writing and n == 13:
                    pass  # the host's turnaround back: it takes the line as this clock falls
                elif writing and n <= 46:
                    self.samples.append(swdio)  # data bits 0..31 on rises 14..45, the parity on 46
                    if n == 46:
                        bits = self.samples[8:]
                        word = sum(bit << i for i, bit in enumerate(bits[:32]))
                        self.written.append((word, bits[32] == parity_of(word)))
                        self.rises, self.samples = 0, []
                else:  # the host's turnaround: whatever comes next is a new request
                    self.rises, self.samples = 0, []
        self.swclk = swclk
        return self.drive


class Run(NamedTuple):
    swdio: list  # the wire, one level per cycle: the pad while it drives, else the target, else the pull-up
    swclk: list  # one level per cycle, as the host drove it
    owned: list  # one per cycle: was the pad driving SWDIO
    driven: list  # one per cycle: what the target drove, 0, 1 or None
    received: list  # the bytes the host popped, in order
    target: Target
    cpu: CPU


def run(program, tx_data, target=None, cycles=2000, drain=True, host=None):
    """Run `program` with `tx_data` waiting in the TX FIFO until it halts or
    `cycles` pass, the wire resolved after every cycle from the pad, the
    target and the pull-up, and fed back to gpio_in for the next. The host
    pops the RX FIFO as soon as a byte is there (`drain`), as a host reading
    a word must, and `host(cpu, received)`, if given, runs every cycle to
    push what it decides to. A pad driving against the target is a fight,
    which no working host ever has: it fails here."""
    target = target or Target()
    tx_data = [tx_data] if isinstance(tx_data, int) else list(tx_data)
    cpu = CPU(load_program(program), gpio_in=1, tx_data=tx_data)
    swdio, owned, driven, received = [], [], [], []
    line = 1
    while not cpu.halted and cpu.cycle < cycles:
        if host:
            host(cpu, received)
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
        if drain and cpu.rx_fifo:
            received.append(cpu.rx_fifo.pop(0))
    return Run(swdio, cpu.pin_trace(SWCLK), owned, driven, received, target, cpu)


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
    names = FIELDS + ("trn", "ack0", "ack1", "ack2")
    for i, edge in enumerate(rising_edges(r.swclk)):
        labels[edge] = names[i] if i < len(names) else f"d{i - 12}" if i < 44 else "par" if i == 44 else "trn"
    wave.add("rise", labels)


@pytest.fixture(params=(WRITE, READ), ids=lambda p: p.stem.removeprefix("swd_"))
def program(request):
    return request.param


@pytest.fixture(params=REQUESTS, ids=lambda r: f"{'ap' if r[0] else 'dp'}_{'read' if r[1] else 'write'}_a{r[2]:02b}")
def packet(request):
    return Packet(*request.param)


@pytest.fixture(params=(OK, WAIT, FAULT), ids=("ok", "wait", "fault"))
def ack(request):
    return request.param


# --- stage 1: the request, both programs ------------------------------------------


def test_target_samples_the_request_lsb_first(program, packet, wave):
    """Every request a host can make reaches the target field for field: the
    eight samples are the byte's bits from bit 0 up, and decode back to the
    APnDP, RnW and A[3:2] the host asked for. Most requests are not
    palindromes, so MSB first would fail the start, stop or parity check.
    The target answers FAULT so no data phase follows a read."""
    byte = request(*packet)
    r = run(program, byte, Target([FAULT]))
    show(wave, r)
    bits = sampled(r.swdio, r.swclk)[:8]
    assert bits == wire_bits(byte)
    assert target_decode(bits) == packet
    assert r.target.seen == [packet], "the target's own view"


def test_dp_write_to_a01_is_0xa9_and_dp_read_of_a01_0x8d_on_the_wire():
    """Two requests by hand. A DP write to A[3:2] = 01: Start 1, APnDP 0, RnW
    0, A2 1, A3 0, parity 1, Stop 0, Park 1 is 1 0 0 1 0 1 0 1 on the wire,
    the byte 0xA9 = 1010_1001 read from bit 0; backwards it is 1 0 1 0 1 0 0 1,
    so a bit-order slip cannot pass. The read of the same register flips RnW
    and the parity: 1 0 1 1 0 0 0 1, 0x8D."""
    assert request(0, 0, 0b01) == DP_WRITE
    assert request(0, 1, 0b01) == DP_READ
    assert sampled(*run(WRITE, DP_WRITE)[:2])[:8] == [1, 0, 0, 1, 0, 1, 0, 1]
    assert sampled(*run(READ, DP_READ)[:2])[:8] == [1, 0, 1, 1, 0, 0, 0, 1]


@pytest.mark.parametrize("byte", (DP_WRITE, request(1, 0, 0b11), request(0, 0, 0b00)), ids=lambda b: f"{b:#04x}")
def test_each_request_bit_is_on_swdio_through_the_low_half_and_the_rising_edge(program, byte):
    """The target samples on the rise, so the bit must be there before it and
    hold through it: on SWDIO for the 4 low cycles before its rising edge and
    the cycle of the edge. Request bits are 8 cycles apart, 4 low, 4 high, as
    are the turnaround and the ACK clocks that follow."""
    r = run(program, byte, Target([FAULT]))
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    assert [b - a for a, b in zip(ups, ups[1:])][:11] == [BIT] * 11
    assert [d - u for u, d in zip(ups, downs)][:11] == [HIGH] * 11, "high half"
    for i, (bit, up) in enumerate(zip(wire_bits(byte), ups)):
        assert r.swdio[up - HIGH:up + 1] == [bit] * (HIGH + 1), f"bit {i} ({FIELDS[i]}) on the wire"
        if i:
            assert (r.swclk[up - HIGH - 1], r.swclk[up - HIGH]) == (1, 0), f"bit {i}: the clock did not drop as the bit landed"


def test_swdio_is_stable_while_swclk_is_high_during_the_request(program):
    r = run(program, REQ[program])
    park = rising_edges(r.swclk)[7]
    for i in range(1, park + HIGH):
        if r.swclk[i] == 1:
            assert r.swdio[i] == r.swdio[i - 1], f"SWDIO changed at cycle {i} with SWCLK high"


def test_program_waits_for_the_request_with_the_line_idle(program):
    """Nothing happens until the host writes a request: the program stalls on
    its PULL with SWCLK low and SWDIO high, then sends the byte that arrives."""
    cpu = CPU(load_program(program), gpio_in=1)
    cpu.run_cycles(20)
    assert cpu.stalled and cpu.gpio[SWCLK] == 0 and cpu.gpio[SWDIO] == 1 and cpu.gpio_oe[SWDIO] == 1
    cpu.tx_fifo.append(REQ[program])
    cpu.run_cycles(200)
    assert [cpu.pin_trace(SWDIO)[e] for e in rising_edges(cpu.pin_trace(SWCLK))][:8] == wire_bits(REQ[program])


# --- stage 2: the turnaround, both programs -----------------------------------------


def test_host_owns_swdio_through_the_park_bit_and_lets_go_as_that_clock_falls(program, wave):
    """The host drives SWDIO on every cycle of the request, through the park
    bit's rising edge and its high half, and lets go on the edge that drops
    SWCLK after it: from there the pad is not driving until the turnaround
    back. The line reads high meanwhile, from the pull-up, until the target
    takes it: a bench that only watched levels could not tell, `owned` is
    gpio_oe. A FAULT, so neither program has a data phase."""
    r = run(program, REQ[program], Target([FAULT]))
    show(wave, r)
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    release, trn, retake = downs[7], ups[8], downs[12]  # the park bit's clock drops; the turnaround's rise; the turnaround back's clock drops
    assert release == ups[7] + HIGH
    assert all(r.owned[:release]), "the host let go before the park bit was clocked"
    assert not any(r.owned[release:retake]), "the host took the line back early"
    assert set(r.swdio[release:trn]) == {1}, "the pull-up holds the line high while nobody drives"


def test_turnaround_is_one_clock_with_nobody_driving(program):
    """The ninth rising edge of SWCLK is the turnaround's: neither side drives
    through its low half, and the target takes the line on the edge."""
    r = run(program, REQ[program], Target([FAULT]))
    trn = rising_edges(r.swclk)[8]
    assert not any(r.owned[trn - HIGH:trn]) and set(r.driven[trn - HIGH:trn]) == {None}, "somebody drove SWDIO through the turnaround"
    assert r.swdio[trn - 1] == 1, "the pull-up's 1 is what the turnaround's edge finds"
    assert r.driven[trn] is not None, "the target took the line on the turnaround's edge"


def test_letting_go_is_open_drain_with_a_one_the_park_bit_left(program):
    """How the host lets go: one CONFIG word makes SWDIO open-drain, and the 1
    the park bit left on gpio[0] is what an open-drain pin does not drive. The
    same word drops SWCLK. Taking the line back is the same word with a 0.
    Nothing is written to the pin itself."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(program)]
    od01 = isa["config"]["open_drain01"]["field"]
    release, *retakes = [i for i, w in enumerate(words) if w.op == "CONFIG"]
    assert words[release].args == (od01, 1) and words[release].side == (SWCLK, 0)
    assert words[release - 1].op == "SET" and words[release - 1].args == (SWCLK, 1), "right after the park bit's clock"
    assert retakes and all(words[i].args == (od01, 0) and words[i].side == (SWCLK, 0) for i in retakes), "taken back the same way"
    assert not any(w.op == "SET" and w.args[0] == SWDIO for w in words), "no SET on SWDIO: SHIFT_OUT and the pad mode do it all"


# --- stage 3: the ACK, both programs ------------------------------------------------


def test_ack_reaches_the_host_in_the_top_three_bits(program, ack, wave):
    """The target's OK, WAIT or FAULT arrives whole: three SHIFT_INs on the
    three rises after the turnaround, then one PUSH. LSB first, a sample
    enters at bit 7 and walks right, so three of them sit in bits 7:5 and the
    host reads the ACK as the byte >> 5: 0x20, 0x40, 0x80. OK and FAULT are
    mirror images, so ACK[0] first is proven, not assumed."""
    r = run(program, REQ[program], Target([ack]))
    show(wave, r)
    assert r.target.seen == [Packet(0, REQ[program] >> 2 & 1, 0b01)], "the target answered the request it was asked"
    assert r.received[0] == ack << ACK_SHIFT
    assert r.received[0] >> ACK_SHIFT == ack


def test_ack_bits_are_sampled_on_the_three_rises_after_the_turnaround(program, ack):
    """Each ACK bit is on the wire from the rise before its own, where the
    target put it, and the host takes it on its own rise: the three samples
    after the turnaround's are ACK[0], ACK[1], ACK[2]."""
    r = run(program, REQ[program], Target([ack]))
    taken = sampled(r.swdio, r.swclk)
    assert taken[9:12] == wire_bits(ack, 3)
    assert taken[8] == 1, "the turnaround's edge finds the pull-up"


def test_target_drives_from_the_turnaround_to_the_last_ack_clock_and_no_one_fights(program):
    """Without data the target owns the line from the turnaround's rise to the
    third ACK rise, when it lets go; the host does not drive between its
    release and the turnaround back, so there is no cycle where both drive
    (run() would have failed on one)."""
    r = run(program, REQ[program], Target([FAULT]))
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    trn, last, retake = ups[8], ups[11], downs[12]
    assert set(r.driven[:trn]) == {None}
    assert None not in r.driven[trn:last], "the target let go during the ACK"
    assert set(r.driven[last:]) == {None}, "the target kept the line after the ACK"
    assert not any(r.owned[trn:retake]), "the host drove while the target had the line"
    assert not any(a and (b is not None) for a, b in zip(r.owned, r.driven)), "both drove at once"


def test_ack_is_pushed_once_as_the_last_ack_clock_falls(program):
    """Nothing is in the RX FIFO until the third ACK bit is in; the PUSH lands
    on the edge that drops SWCLK after it, and nothing else is pushed for the
    rest of a transaction without data (a FAULT here): the host reads one byte."""
    cpu = CPU(load_program(program), gpio_in=1, tx_data=[REQ[program]])
    target = Target([FAULT])
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
    assert seen[push] == (0, [FAULT << ACK_SHIFT])
    assert all(fifo == [FAULT << ACK_SHIFT] for _, fifo in seen[push:]), "pushed again"


# --- stage 4: the decision, both programs -------------------------------------------


def test_turnaround_back_gives_the_host_the_line_after_wait_or_fault(program):
    """After a WAIT or FAULT one more clock with nobody driving, the
    thirteenth rise, and on the edge that drops it the host takes SWDIO back:
    push-pull again, driving the 1 that was on the pin all along. The host
    owns an idle line, SWDIO high and SWCLK low, when it acts on the answer."""
    for ack in (WAIT, FAULT):
        r = run(program, REQ[program], Target([ack]), cycles=300)
        ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
        trn, retake = ups[12], downs[12]
        assert retake == trn + HIGH
        assert not any(r.owned[trn - HIGH:trn]) and set(r.driven[trn - HIGH:trn + HIGH]) == {None}, "somebody drove through the turnaround back"
        assert r.swdio[trn - 1] == 1, "the pull-up's 1 is what the turnaround back's edge finds"
        assert all(r.owned[retake:retake + BIT]), "the host did not take the line back"
        assert set(r.swdio[retake:retake + BIT]) == {1} and set(r.swclk[retake:retake + HIGH]) == {0}


def test_wait_with_no_second_request_holds_the_line_idle_on_the_pull(program):
    """WAIT with nothing more from the host: the program is back on its PULL,
    not halted, SWDIO driven high and SWCLK low, and stays there. A host that
    wants to give up simply does not push again; the WAIT it read says why."""
    r = run(program, REQ[program], Target([WAIT]), cycles=400)
    assert not r.cpu.halted and r.cpu.stalled
    assert decode(r.cpu.program[r.cpu.pc], r.cpu.isa).op == "PULL"
    assert r.received == [WAIT << ACK_SHIFT]
    assert len(rising_edges(r.swclk)) == CLOCKS, "no clock without a request"
    assert r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio[SWDIO] == 1 and r.cpu.gpio[SWCLK] == 0
    assert set(r.swdio[-100:]) == {1} and set(r.swclk[-100:]) == {0} and all(r.owned[-100:])


def test_fault_exits_after_the_push_reported_it(program):
    """FAULT: the transaction is over and no retry would help; the host must
    clear the error itself. The program halts after the turnaround back with
    the FAULT in the RX FIFO, the request sent once, thirteen clocks."""
    r = run(program, [REQ[program]] * 2, Target([FAULT]))
    assert r.cpu.halted
    assert r.received == [FAULT << ACK_SHIFT]
    assert r.target.seen == [Packet(0, REQ[program] >> 2 & 1, 0b01)]
    assert len(rising_edges(r.swclk)) == CLOCKS
    assert r.cpu.tx_fifo == [REQ[program]], "the second request was not sent"


def issued(program, tx_data, target):
    """The addresses of the words a run issued, in order."""
    cpu = CPU(load_program(program), gpio_in=1, tx_data=tx_data)
    line, pcs = 1, []
    while not cpu.halted and cpu.cycle < 1000:
        if cpu.counter == 0 and not cpu.stalled:
            pcs.append(cpu.pc)
        cpu.step()
        drive = target.update(line, cpu.gpio[SWCLK])
        line = cpu.gpio[SWDIO] if cpu.gpio_oe[SWDIO] else drive if drive is not None else 1
        cpu.gpio_in[SWDIO] = line
        if cpu.rx_fifo:
            cpu.rx_fifo.pop(0)
    return pcs


def test_the_three_answers_take_three_paths(program):
    """OK, WAIT and FAULT leave the branch by different words. SKIP sees one
    bit at a time, so a three-way decision is two SKIPs and three JMPs: SKIP
    5, 0 over a JMP to the data label for OK (bit 5 set), SKIP 6, 0 over a
    JMP to the request for WAIT (bit 6), and a JMP to the end for FAULT, or
    for no ACK bit at all. The cost of branching on a 3-bit field with this
    ISA, on record."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(program)]
    pull = [i for i, w in enumerate(words) if w.op == "PULL"][0]  # the request's; the write program has five more
    skips = [i for i, w in enumerate(words) if w.op == "SKIP"]
    jmps = [i for i, w in enumerate(words) if w.op == "JMP"]
    assert len(skips) == 2 and len(jmps) == 3
    skip_ok, skip_wait = skips
    assert words[skip_ok].args == (ACK_SHIFT, 0) and words[skip_wait].args == (ACK_SHIFT + 1, 0)
    jmp_data, jmp_retry, jmp_done = jmps
    assert jmp_data == skip_ok + 1 and jmp_retry == skip_wait + 1 and jmp_done == skip_wait + 2
    assert words[jmp_retry].args == (pull,), "WAIT: the request again"
    assert words[jmp_done].args == (len(words),), "FAULT: the end"
    data = words[jmp_data].args[0]
    assert jmp_done < data <= len(words), "OK: on to the data phase, or the end"

    ok = issued(program, [REQ[program]], Target([OK], DATA))
    wait = issued(program, [REQ[program]] * 2, Target([WAIT, OK], DATA))
    fault = issued(program, [REQ[program]], Target([FAULT]))
    assert jmp_data in ok and skip_wait not in ok and jmp_done not in ok
    assert jmp_retry in wait and wait.count(pull) == 2 and jmp_data in wait, "WAIT went round once, then OK went on"
    assert jmp_done in fault and jmp_data not in fault and jmp_retry not in fault


def test_the_two_programs_agree_through_the_third_ack_sample():
    """swd_write.asm and swd_read.asm are word for word the same up to and
    including the third SHIFT_IN. From there the write program takes the
    turnaround back before it decides, the read program decides first,
    because on OK the target keeps the line for the data."""
    isa = load_isa()
    a, b = load_program(WRITE), load_program(READ)
    third = [i for i, w in enumerate(a) if decode(w, isa).op == "SHIFT_IN"][2]
    assert a[:third + 1] == b[:third + 1]
    assert decode(a[third + 1], isa).op == "PUSH" and decode(b[third + 1], isa).op == "SKIP"


# --- stage 6: the write data, swd_write.asm ----------------------------------------------


def test_write_ok_clocks_the_hosts_word_and_parity_out_after_the_turnaround_back(wave):
    """A DP write the target says OK to, with 0xE31D5396 to send. The host
    queues the request, then the four data bytes from bit 0 up and a fifth
    whose bit 0 is the parity it computed: the core has no XOR. After the ACK
    and the turnaround back the host owns the line and clocks the 33 bits
    out, each PULL in the last high cycle of the byte before so the beat
    holds. The target sees the request, then the word with a good parity.
    One ACK byte to the host, 46 clocks, halted owning the line."""
    r = run(WRITE, [DP_WRITE] + write_bytes(DATA), Target([OK]))
    show(wave, r)
    assert r.cpu.halted
    assert r.target.seen == [Packet(0, 0, 0b01)]
    assert r.target.written == [(DATA, True)]
    assert r.received == [OK << ACK_SHIFT]
    assert len(rising_edges(r.swclk)) == WRITE_CLOCKS
    assert r.cpu.tx_fifo == [], "all six bytes consumed"
    assert r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio[SWCLK] == 0


@pytest.mark.parametrize("data", (0, 0xFFFFFFFF, 0x80000001, 0x00000001, 0x80000000, 0x5A3C9670, 0x0F0F0F0F), ids=lambda d: f"{d:#010x}")
def test_write_data_arrives_whole_whatever_it_is(data):
    """Every bit of the word lands where it belongs at the target, for words
    with ones at the ends, in the middle and nowhere, with the parity the
    host sent judged good."""
    r = run(WRITE, [DP_WRITE] + write_bytes(data), Target([OK]))
    assert r.target.written == [(data, True)]


def test_write_data_and_parity_are_on_the_rises_after_the_turnaround_back():
    """The thirteenth rise is the turnaround back; data bit 0 is taken on the
    fourteenth, bit i on the one after that, the parity on the forty-sixth.
    Each data bit is on the line through the low half before its rise."""
    r = run(WRITE, [DP_WRITE] + write_bytes(DATA), Target([OK]))
    ups = rising_edges(r.swclk)
    taken = sampled(r.swdio, r.swclk)
    assert len(taken) == WRITE_CLOCKS
    assert taken[12] == 1, "the turnaround back's edge finds the pull-up"
    assert taken[13:45] == wire_bits(DATA, 32)
    assert taken[45] == parity_of(DATA)
    for i, up in enumerate(ups[13:46]):
        assert r.swdio[up - HIGH:up + 1] == [taken[13 + i]] * (HIGH + 1), f"write bit {i} on the wire"


def test_write_keeps_the_beat_with_a_prompt_host():
    """With every byte already queued, a PULL in a clock's last high cycle
    costs nothing: all 33 data clocks are 8 cycles apart, 4 low and 4 high,
    after the two-word stretch of the branch and the first PULL."""
    r = run(WRITE, [DP_WRITE] + write_bytes(DATA), Target([OK]))
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    gaps = [b - a for a, b in zip(ups, ups[1:])]
    assert gaps[:12] == [BIT] * 12
    assert gaps[12] == BIT + 4 + 3, "the turnaround back's rise to data bit 0's: the take-back word's low half, two SKIPs, the JMP and the PULL"
    assert gaps[13:] == [BIT] * 32
    assert [d - u for u, d in zip(ups, downs)] == [HIGH] * WRITE_CLOCKS
    assert set(r.swclk[downs[-1]:]) == {0}, "SWCLK idle low after the transaction"


def test_host_owns_swdio_from_the_turnaround_back_to_the_end_of_the_write():
    r = run(WRITE, [DP_WRITE] + write_bytes(DATA), Target([OK]))
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    retake = downs[12]
    assert not any(r.owned[ups[7] + HIGH:retake]) and all(r.owned[retake:])
    assert set(r.driven[ups[11]:]) == {None}, "the target drove after ACK[2]"


def test_write_without_data_from_the_host_stops_the_clock_low_on_the_pull():
    """The host queued only the request: the ACK is OK, the turnaround back
    done, and the first data PULL stalls with SWCLK low and the host owning
    the line. The transaction goes on when the bytes arrive: SWD allows a
    stopped clock. On record: request, four data bytes and the parity are
    six bytes through a 4-deep TX FIFO, so the host feeds the write."""
    r = run(WRITE, DP_WRITE, Target([OK]), cycles=400)
    assert not r.cpu.halted and r.cpu.stalled
    assert decode(r.cpu.program[r.cpu.pc], r.cpu.isa).op == "PULL"
    assert len(rising_edges(r.swclk)) == CLOCKS
    assert r.cpu.gpio[SWCLK] == 0 and r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio[SWDIO] == 1
    assert r.received == [OK << ACK_SHIFT]
    r.cpu.tx_fifo.extend(write_bytes(DATA))
    line = r.swdio[-1]
    while not r.cpu.halted and r.cpu.cycle < 1000:
        r.cpu.step()
        drive = r.target.update(line, r.cpu.gpio[SWCLK])
        line = r.cpu.gpio[SWDIO] if r.cpu.gpio_oe[SWDIO] else drive if drive is not None else 1
        r.cpu.gpio_in[SWDIO] = line
    assert r.cpu.halted and r.target.written == [(DATA, True)]


class WriteHost:
    """A host doing one write the way the FIFOs ask: the request first and
    nothing else, because a WAIT would make the retry PULL a data byte as
    the request; on WAIT the request again; on OK the data and the parity."""

    def __init__(self, request, data, parity=None):
        self.request = request
        self.bytes = write_bytes(data, parity)
        self.acks = 0

    def __call__(self, cpu, received):
        if len(received) > self.acks:
            self.acks = len(received)
            ack = received[-1] >> ACK_SHIFT
            if ack == WAIT:
                cpu.tx_fifo.append(self.request)
            elif ack == OK:
                cpu.tx_fifo.extend(self.bytes)


def test_write_wait_then_ok_writes_the_word_on_the_second_try():
    """WAIT on a write: the host must not have queued the data, or the retry
    PULL would send data byte 0 as the request (no way to discard a queued
    byte but PULLing it, on record). It pushes the request again on the
    WAIT, and the data on the OK; the target gets the word once, with a good
    parity. 13 + 46 clocks, two ACK bytes."""
    r = run(WRITE, DP_WRITE, Target([WAIT, OK]), host=WriteHost(DP_WRITE, DATA))
    assert r.cpu.halted
    assert r.target.seen == [Packet(0, 0, 0b01)] * 2
    assert r.target.written == [(DATA, True)]
    assert [b >> ACK_SHIFT for b in r.received] == [WAIT, OK]
    assert len(rising_edges(r.swclk)) == CLOCKS + WRITE_CLOCKS


def test_write_fault_sends_no_data():
    """FAULT on a write: the turnaround back and the exit; a host that had
    queued data finds it still in the FIFO, unsent."""
    r = run(WRITE, [DP_WRITE] + write_bytes(DATA), Target([FAULT]))
    assert r.cpu.halted
    assert r.received == [FAULT << ACK_SHIFT]
    assert r.target.written == []
    assert r.cpu.tx_fifo == write_bytes(DATA), "the data stayed queued"
    assert len(rising_edges(r.swclk)) == CLOCKS


def test_a_wrong_parity_from_the_host_goes_out_unjudged():
    """The core sends bit 0 of the fifth byte as the parity, whatever it is:
    the target judges it, the core cannot."""
    r = run(WRITE, [DP_WRITE] + write_bytes(DATA, parity=1 - parity_of(DATA)), Target([OK]))
    assert r.cpu.halted
    assert r.target.written == [(DATA, False)]


def test_write_program_is_the_read_programs_shape_with_the_data_going_out():
    """Two words per bit, out or in, SPI's and I2C's shape: SHIFT_OUT with
    the clock low and SET with it high for the request and the data, SET with
    the clock low and SHIFT_IN raising it for the ACK. No CONFIG shift_dir,
    because the reset configuration, LSB first, is SWD's. Each turnaround is
    two words; the PUSH drops the last ACK clock; the branch is five; a PULL
    per data byte and one for the parity, each in a clock's last high cycle
    but the first, which follows the branch; 106 words."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(WRITE)]
    shift_dir = isa["config"]["shift_dir"]["field"]
    assert not any(w.op == "CONFIG" and w.args[0] == shift_dir for w in words)
    outs = [w for w in words if w.op == "SHIFT_OUT"]
    ins = [w for w in words if w.op == "SHIFT_IN"]
    pulls = [i for i, w in enumerate(words) if w.op == "PULL"]
    (push,) = [w for w in words if w.op == "PUSH"]
    assert len(outs) == 8 + 32 + 1 and all(w.side == (SWCLK, 0) for w in outs)
    assert len(ins) == 3 and all(w.args == (SWDIO,) and w.side == (SWCLK, 1) for w in ins)
    assert push.side == (SWCLK, 0) and push.delay == 3, "the PUSH is the turnaround back's low half"
    assert len(pulls) == 1 + 5
    for i in pulls[2:]:
        assert words[i - 1] == decode(load_program(WRITE)[i - 1], isa) and words[i - 1].op == "SET" and words[i - 1].args == (SWCLK, 1) and words[i - 1].delay == 2, "a PULL in a clock's last high cycle"
        assert words[i].delay == 0 and words[i].side is None
    assert len(words) == 2 + 16 + 2 + 6 + 1 + 2 + 5 + 1 + 4 * 17 + 3 == 106


# --- stage 5: the read data, swd_read.asm -----------------------------------------------


def test_read_ok_hands_the_host_the_ack_four_data_bytes_and_the_parity(wave):
    """A DP read the target says OK to, with 0xE31D5396 to give. The host
    reads six bytes: 0x20, the ACK; 0x96, 0x53, 0x1D, 0xE3, the data from bit
    0 up, each byte whole because eight LSB-first samples fill the register
    end to end; and 0xF1, the parity bit as bit 7 over data[31:25], the
    register having shifted once more. The host checks the parity itself:
    the core has no XOR. 46 clocks, one transaction, halted owning the line."""
    r = run(READ, DP_READ, Target([OK], DATA))
    show(wave, r)
    assert r.cpu.halted
    assert r.target.seen == [Packet(0, 1, 0b01)]
    assert r.received == read_bytes(OK, DATA) == [0x20, 0x96, 0x53, 0x1D, 0xE3, 0xF1]
    assert len(rising_edges(r.swclk)) == READ_CLOCKS
    assert r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio[SWDIO] == 1 and r.cpu.gpio[SWCLK] == 0


@pytest.mark.parametrize("data", (0, 0xFFFFFFFF, 0x80000001, 0x00000001, 0x80000000, 0x5A3C9670, 0x0F0F0F0F), ids=lambda d: f"{d:#010x}")
def test_read_data_arrives_whole_whatever_it_is(data):
    """Every bit of the word comes back where it belongs, and the parity the
    target sent with it, for words with ones at the ends, in the middle and
    nowhere."""
    r = run(READ, DP_READ, Target([OK], data))
    assert r.received == read_bytes(OK, data)
    word = sum(b << (8 * i) for i, b in enumerate(r.received[1:5]))
    assert word == data
    assert r.received[5] >> 7 == parity_of(data)
    assert r.received[5] & 0x7F == data >> 25, "the seven data bits under the parity"


def test_read_data_and_parity_are_sampled_on_the_rises_after_the_ack():
    """No turnaround between the ACK and the data: the target puts data bit 0
    on the line on the third ACK rise and the host takes it on the very next
    rise, bit i on the rise after that, the parity on the forty-fifth. The
    forty-sixth is the turnaround back, nobody driving."""
    r = run(READ, DP_READ, Target([OK], DATA))
    taken = sampled(r.swdio, r.swclk)
    assert len(taken) == READ_CLOCKS
    assert taken[9:12] == wire_bits(OK, 3)
    assert taken[12:44] == wire_bits(DATA, 32)
    assert taken[44] == parity_of(DATA)
    assert taken[45] == 1, "the turnaround back's edge finds the pull-up"


def test_target_owns_the_line_from_the_turnaround_to_the_parity_and_the_host_takes_it_back_after():
    """For a read the target drives from the turnaround's rise through the
    parity's, letting go on the rise the host samples the parity; the host
    does not drive in between, gives one clock with nobody driving and takes
    the line back as that clock drops."""
    r = run(READ, DP_READ, Target([OK], DATA))
    ups, downs = rising_edges(r.swclk), falling_edges(r.swclk)
    trn, last, back, retake = ups[8], ups[44], ups[45], downs[45]
    assert set(r.driven[:trn]) == {None}
    assert None not in r.driven[trn:last], "the target let go before the parity was taken"
    assert set(r.driven[last:]) == {None}, "the target kept the line after the parity"
    assert not any(r.owned[trn:retake]), "the host drove while the target had the line"
    assert set(r.swdio[last:back + 1]) == {1}, "the pull-up through the turnaround back"
    assert all(r.owned[retake:]) and set(r.swdio[retake:]) == {1} and set(r.swclk[retake + 1:]) == {0}
    assert not any(a and (b is not None) for a, b in zip(r.owned, r.driven)), "both drove at once"


def test_read_pushes_a_byte_as_every_eighth_data_clock_falls():
    """The ACK byte on the fall after the third ACK rise, data byte k on the
    fall after data bit 8k + 7, the parity byte on the fall after the parity
    bit: six PUSHes, each on the edge that drops the clock it completes, and
    a host that pops as they land never sees two in the FIFO."""
    cpu = CPU(load_program(READ), gpio_in=1, tx_data=[DP_READ])
    target = Target([OK], DATA)
    line, pushes, depth = 1, [], 0
    swclk = []
    while not cpu.halted and cpu.cycle < 1000:
        cpu.step()
        drive = target.update(line, cpu.gpio[SWCLK])
        line = cpu.gpio[SWDIO] if cpu.gpio_oe[SWDIO] else drive if drive is not None else 1
        cpu.gpio_in[SWDIO] = line
        swclk.append(cpu.gpio[SWCLK])
        depth = max(depth, len(cpu.rx_fifo))
        if cpu.rx_fifo:
            pushes.append((cpu.cycle - 1, cpu.rx_fifo.pop(0)))
    assert cpu.halted and depth == 1
    downs = falling_edges(swclk)
    assert [c for c, _ in pushes] == [downs[i] for i in (11, 19, 27, 35, 43, 44)]
    assert [b for _, b in pushes] == read_bytes(OK, DATA)


def test_read_without_a_draining_host_stops_the_clock_at_the_fifth_push():
    """The RX FIFO holds four bytes and a read is six: a host that does not
    pop during the transaction has the fifth PUSH, data byte 3's, stall with
    the FIFO full and SWCLK stopped high after the thirty-second data bit,
    the target holding that bit. SWD allows a stopped clock; the transaction
    goes on when the host pops. On record: a 32-bit read needs the host at
    the FIFO mid-transaction, or a deeper FIFO."""
    r = run(READ, DP_READ, Target([OK], DATA), cycles=600, drain=False)
    assert not r.cpu.halted and r.cpu.stalled
    assert decode(r.cpu.program[r.cpu.pc], r.cpu.isa).op == "PUSH"
    assert r.cpu.rx_fifo == read_bytes(OK, DATA)[:4]
    assert len(rising_edges(r.swclk)) == 12 + 32, "stopped after the last data bit"
    assert r.cpu.gpio[SWCLK] == 1 and set(r.swclk[-100:]) == {1}, "SWCLK stopped high"
    assert set(r.driven[-100:]) == {(DATA >> 31) & 1}, "the target holds data bit 31"

    def go_on(cycles):
        """Keep the wire alive while the host acts, as run() did."""
        line = r.swdio[-1]
        for _ in range(cycles):
            if r.cpu.halted:
                break
            r.cpu.step()
            drive = r.target.update(line, r.cpu.gpio[SWCLK])
            line = r.cpu.gpio[SWDIO] if r.cpu.gpio_oe[SWDIO] else drive if drive is not None else 1
            r.cpu.gpio_in[SWDIO] = line
            r.swdio.append(line)

    r.received.append(r.cpu.rx_fifo.pop(0))  # the host pops one: the fifth PUSH goes through, the parity is clocked, the sixth PUSH stalls
    go_on(200)
    assert r.cpu.stalled and decode(r.cpu.program[r.cpu.pc], r.cpu.isa).op == "PUSH"
    assert r.cpu.rx_fifo == read_bytes(OK, DATA)[1:5]
    assert len(rising_edges(r.cpu.pin_trace(SWCLK))) == 12 + 33, "the parity clock, then stopped again"
    r.received.append(r.cpu.rx_fifo.pop(0))  # and one more: the read completes
    go_on(200)
    assert r.cpu.halted
    assert r.received + r.cpu.rx_fifo == read_bytes(OK, DATA)


def test_read_wait_then_ok_reads_the_word_on_the_second_try():
    """WAIT on a read: the turnaround back, the request again from the host's
    second copy, and this time OK and the data. Seven bytes: 0x40, then 0x28
    (OK over the WAIT's bit), then the four data bytes, whole because eight
    more samples pushed every older bit out, then the parity byte."""
    r = run(READ, [DP_READ, DP_READ], Target([WAIT, OK], DATA))
    assert r.cpu.halted
    assert r.target.seen == [Packet(0, 1, 0b01)] * 2
    assert r.received == [WAIT << ACK_SHIFT, OK << ACK_SHIFT | WAIT << (ACK_SHIFT - 3)] + read_bytes(OK, DATA)[1:]
    assert len(rising_edges(r.swclk)) == CLOCKS + READ_CLOCKS


def test_read_fault_takes_the_turnaround_back_and_exits():
    """FAULT on a read: no data phase, the turnaround back, the exit; the
    target never drove after ACK[2] and the host owns the line at the end."""
    r = run(READ, DP_READ, Target([FAULT], DATA))
    assert r.cpu.halted
    assert r.received == [FAULT << ACK_SHIFT]
    assert len(rising_edges(r.swclk)) == CLOCKS
    assert set(r.driven[rising_edges(r.swclk)[11]:]) == {None}
    assert r.cpu.gpio_oe[SWDIO] == 1 and r.cpu.gpio[SWDIO] == 1 and r.cpu.gpio[SWCLK] == 0


def test_a_wrong_parity_from_the_target_reaches_the_host_unjudged():
    """The core does not check parity: a target sending the wrong bit gets it
    delivered as bit 7 of the fifth byte like any other, and the host, which
    has the four data bytes too, is the one to notice."""
    r = run(READ, DP_READ, Target([OK], DATA, parity=1 - parity_of(DATA)))
    assert r.cpu.halted
    assert r.received == read_bytes(OK, DATA, parity=1 - parity_of(DATA))
    assert r.received[5] >> 7 != parity_of(DATA)


def test_read_program_is_the_request_program_plus_two_words_per_data_bit():
    """The read program's cost: 2 words per data bit and per ACK bit, a PUSH
    in place of every eighth clock drop, one more sample and PUSH for the
    parity, and the turnaround back after the data instead of before the
    decision. 103 words for a 32-bit read, the ISA's repetition pressure at
    its widest."""
    isa = load_isa()
    words = [decode(w, isa) for w in load_program(READ)]
    ins = [w for w in words if w.op == "SHIFT_IN"]
    outs = [w for w in words if w.op == "SHIFT_OUT"]
    pushes = [w for w in words if w.op == "PUSH"]
    configs = [w for w in words if w.op == "CONFIG"]
    assert len(outs) == 8 and len(ins) == 3 + 32 + 1 and len(pushes) == 1 + 1 + 4 + 1
    assert all(w.args == (SWDIO,) and w.side == (SWCLK, 1) for w in ins)
    assert all(w.side == (SWCLK, 0) and w.delay == 3 for w in pushes)
    assert len(configs) == 3, "let go once, take back on either path"
    assert len(words) == 2 + 16 + 2 + 6 + 2 + 3 + 3 + 1 + 4 * 16 + 1 + 1 + 2 == 103
