"""SPI mode 0 master checks, run against both bit orders and against the
transmit-only and the full-duplex programs. The `run` helper is the only place
that knows which pin is which; every check watches the pins like a slave
would: CS frames the transfer, MOSI is sampled on each rising edge of SCLK,
and a slave model drives MISO for the master to sample on that same edge."""

from pathlib import Path
from typing import NamedTuple

import pytest

from cpu import CPU, Instruction, decode, load_isa, load_program

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
TX = (PROGRAMS / "spi_tx_lsb.asm", PROGRAMS / "spi_tx_msb.asm")
DUPLEX = (PROGRAMS / "spi_duplex_lsb.asm", PROGRAMS / "spi_duplex_msb.asm")
MOSI, SCLK, CS = 0, 1, 2  # gpio pins the programs drive
MISO = 3  # gpio_in pin the duplex programs sample
BYTES = (0x00, 0x01, 0x55, 0x80, 0xA3, 0xFF)


def is_msb(program):
    return program.stem.endswith("_msb")


class Run(NamedTuple):
    mosi: list  # one level per cycle, as the master drove it
    sclk: list
    cs: list
    miso: list  # one level per cycle, as the slave drove it
    cpu: CPU


def run(program, tx_data, slave=None):
    """Run a program to its end with `slave(cpu)` driving MISO every cycle
    from what the master's pins held at the end of the cycle before."""
    cpu = CPU(load_program(program), tx_data=tx_data)
    miso = []
    while not cpu.halted:
        if slave:
            cpu.gpio_in[MISO] = slave(cpu)
        miso.append(cpu.gpio_in[MISO])
        cpu.step()
    return Run(cpu.pin_trace(MOSI), cpu.pin_trace(SCLK), cpu.pin_trace(CS), miso, cpu)


def mode0_slave(byte, msb_first):
    """A mode 0 slave sending `byte`: MISO shows the first bit as soon as CS
    is low and moves on at every falling edge of SCLK, so each bit is stable
    across the rising edge where the master samples. Idle high otherwise."""
    bits = wire_bits(byte, msb_first)
    state = {"sclk": 1, "i": 0}

    def miso(cpu):
        sclk, cs = cpu.gpio[SCLK], cpu.gpio[CS]
        if cs:
            state["i"] = 0
        elif state["sclk"] == 1 and sclk == 0:
            state["i"] += 1
        state["sclk"] = sclk
        return bits[state["i"]] if not cs and state["i"] < 8 else 1

    return miso


def edge_only_slave(byte, msb_first, edges):
    """An adversarial slave: the right bit is on MISO only during the cycle
    SCLK rises (`edges`, from a dry run), the wrong one every other cycle."""
    bits = wire_bits(byte, msb_first)

    def miso(cpu):
        i = min(range(len(edges)), key=lambda i: abs(edges[i] - cpu.cycle))  # nearest edge
        return bits[i] if edges[i] == cpu.cycle else 1 - bits[i]

    return miso


def rising_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def falling_edges(trace):
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def sampled(mosi, sclk):
    """What a mode 0 slave shifts in: MOSI on every rising edge of SCLK, in order."""
    return [mosi[e] for e in rising_edges(sclk)]


def wire_bits(byte, msb_first):
    """The order the bits of `byte` should appear on the wire."""
    bits = [(byte >> i) & 1 for i in range(8)]
    return bits[::-1] if msb_first else bits


class Frame(NamedTuple):
    byte: int
    msb_first: bool
    mosi: list
    sclk: list
    cs: list
    start: int  # cycle CS falls
    end: int  # cycle CS rises again


@pytest.fixture(params=TX + DUPLEX, ids=lambda p: p.stem.removeprefix("spi_"))
def program(request):
    return request.param


@pytest.fixture(params=DUPLEX, ids=lambda p: p.stem.removeprefix("spi_"))
def duplex(request):
    return request.param


@pytest.fixture(params=BYTES, ids=lambda b: f"{b:#04x}")
def frame(request, program):
    byte = request.param
    r = run(program, [byte])
    (start,), (end,) = falling_edges(r.cs), rising_edges(r.cs)
    return Frame(byte, is_msb(program), r.mosi, r.sclk, r.cs, start, end)


def test_cs_frames_exactly_eight_clocks(frame, wave):
    wave.add("cs", frame.cs, group="spi")
    wave.add("sclk", frame.sclk, group="spi")
    wave.add("mosi", frame.mosi, group="spi")
    edges = rising_edges(frame.sclk)
    labels = ["-"] * len(frame.mosi)
    for i, edge in enumerate(edges):
        labels[edge] = f"d{7 - i if frame.msb_first else i}"
    wave.add("sample", labels)

    assert frame.start < frame.end
    assert frame.cs[frame.start:frame.end] == [0] * (frame.end - frame.start), "CS stays low through the frame"
    assert frame.cs[frame.end:] == [1] * (len(frame.cs) - frame.end), "CS stays high after the frame"
    assert len(edges) == 8 and all(frame.start < e < frame.end for e in edges)


def test_clock_idles_low_outside_the_frame(frame):
    sclk, start, end = frame.sclk, frame.start, frame.end
    assert sclk[start] == 0 and sclk[end - 1] == 0, "clock low when CS moves"
    assert set(sclk[end:]) == {0}, "clock idle low after the frame"
    assert not any(e >= end for e in rising_edges(sclk) + falling_edges(sclk))


def test_mosi_is_stable_while_the_clock_is_high(frame):
    for i in range(frame.start + 1, frame.end):
        if frame.sclk[i] == 1:
            assert frame.mosi[i] == frame.mosi[i - 1], f"MOSI changed at cycle {i} with SCLK high"


def test_mosi_settles_before_each_rising_edge(frame):
    for edge in rising_edges(frame.sclk):
        assert frame.mosi[edge - 1] == frame.mosi[edge], f"MOSI still moving on the sampling edge at cycle {edge}"


def test_slave_samples_the_supplied_byte_in_the_programs_bit_order(frame):
    assert sampled(frame.mosi, frame.sclk) == wire_bits(frame.byte, frame.msb_first)


def test_0xa3_on_the_wire_lsb_first_then_msb_first():
    """0xA3 = 1010 0011. Sampled on the rising edges, the LSB-first program
    clocks out 1 1 0 0 0 1 0 1 and the MSB-first program 1 0 1 0 0 0 1 1."""
    lsb, msb = TX
    assert sampled(*run(lsb, [0xA3])[:2]) == [1, 1, 0, 0, 0, 1, 0, 1]
    assert sampled(*run(msb, [0xA3])[:2]) == [1, 0, 1, 0, 0, 0, 1, 1]


@pytest.mark.parametrize("pair", (TX, DUPLEX), ids=("tx", "duplex"))
@pytest.mark.parametrize("byte", BYTES, ids=lambda b: f"{b:#04x}")
def test_msb_program_puts_the_lsb_programs_bits_on_the_wire_backwards(pair, byte):
    lsb, msb = (sampled(*run(p, [byte])[:2]) for p in pair)
    assert msb == lsb[::-1]
    assert (msb == lsb) == (wire_bits(byte, False) == wire_bits(byte, True)), "only palindromes look the same"


@pytest.mark.parametrize("pair", (TX, DUPLEX), ids=("tx", "duplex"))
def test_programs_differ_only_in_the_config_shift_dir_value(pair):
    """Bit order is configuration: the transfer itself is word for word the same."""
    isa = load_isa()
    lsb, msb = (load_program(p) for p in pair)
    assert len(lsb) == len(msb)
    (i,) = [i for i, (a, b) in enumerate(zip(lsb, msb)) if a != b]
    assert decode(lsb[i], isa).op == decode(msb[i], isa).op == "CONFIG"
    assert (decode(lsb[i], isa).args, decode(msb[i], isa).args) == ((0, 0), (0, 1))


def test_program_is_two_instructions_per_bit(program):
    words = load_program(program)
    assert len(words) == 3 + 8 * 2 + 2  # config, clock low, pull + CS low; 8 x (shift + clock low, clock high); teardown


@pytest.mark.parametrize("tx, duplex", tuple(zip(TX, DUPLEX)), ids=("lsb", "msb"))
def test_duplex_program_is_the_tx_program_with_shift_in_raising_the_clock(tx, duplex):
    """Receiving costs no instructions: the eight `SET 1, 1 [3]` become
    `SHIFT_IN 3, 1, 1 [3]`, sampling MISO on the edge that already existed,
    and the closing `SET 2, 1` becomes `PUSH 2, 1`, handing the byte to the
    RX FIFO on the edge that raises CS."""
    isa = load_isa()
    tx, duplex = load_program(tx), load_program(duplex)
    assert len(tx) == len(duplex)
    changed = [(decode(a, isa), decode(b, isa)) for a, b in zip(tx, duplex) if a != b]
    assert len(changed) == 9
    for was, now in changed[:8]:
        assert was == Instruction("SET", (SCLK, 1), 3)
        assert now == Instruction("SHIFT_IN", (MISO,), 3, side=(SCLK, 1))
    assert changed[8] == (Instruction("SET", (CS, 1), 0), Instruction("PUSH", (), 0, side=(CS, 1)))


def test_bit_period_is_8_cycles_split_4_low_4_high(program):
    """SHIFT_OUT 1, 0 [3] holds the clock low for 4 cycles with the new bit on
    MOSI, SET 1, 1 [3] holds it high for 4."""
    _, sclk, cs, _, _ = run(program, [0xA5])
    (start,), (end,) = falling_edges(cs), rising_edges(cs)
    ups = rising_edges(sclk)
    downs = [d for d in falling_edges(sclk) if start < d < end]  # the setup drop is before CS
    assert [b - a for a, b in zip(ups, ups[1:])] == [8] * 7
    assert [d - u for u, d in zip(ups, downs)] == [4] * 8, "high half"
    assert [u - d for d, u in zip(downs, ups[1:])] == [4] * 7, "low half"
    assert end - start == 4 + 8 * 8 + 4


def test_each_bit_lands_on_mosi_as_the_clock_drops(frame):
    """Every bit is on MOSI 4 cycles before its rising edge and stays through
    it. From the second bit on, that landing cycle is the cycle the clock
    drops: one edge does both. The first bit finds the clock already low."""
    bits = wire_bits(frame.byte, frame.msb_first)
    for i, up in enumerate(rising_edges(frame.sclk)):
        land = up - 4
        assert frame.mosi[land:up + 1] == [bits[i]] * 5, f"bit {i} on the wire"
        if i:
            assert (frame.sclk[land - 1], frame.sclk[land]) == (1, 0), f"bit {i}: clock did not drop on the landing cycle"


def test_program_waits_for_a_byte_with_cs_high(program):
    cpu = CPU(load_program(program))
    cpu.run_cycles(20)
    assert cpu.stalled and cpu.gpio[CS] == 1 and cpu.gpio[SCLK] == 0
    assert cpu.shift_dir == is_msb(program), "configured before the wait"
    cpu.tx_fifo.append(0x3C)
    cpu.run()
    assert sampled(cpu.pin_trace(MOSI), cpu.pin_trace(SCLK)) == wire_bits(0x3C, is_msb(program))


# Full duplex: the slave answers on MISO while the master sends on MOSI.

PAIRS = ((0xA3, 0x5C), (0x00, 0xFF), (0xFF, 0x00), (0x55, 0xAA), (0x80, 0x01), (0x3C, 0x3C))


@pytest.mark.parametrize("tx, rx", PAIRS, ids=lambda b: f"{b:#04x}")
def test_master_reads_the_slaves_byte_while_sending_its_own(duplex, tx, rx, wave):
    """Eight SHIFT_INs on the eight rising edges rebuild the slave's byte in
    normal order, in whichever bit order the transfer uses, and the transmit
    side is untouched: the slave still samples the master's byte."""
    msb_first = is_msb(duplex)
    r = run(duplex, [tx], mode0_slave(rx, msb_first))
    wave.add("cs", r.cs, group="master")
    wave.add("sclk", r.sclk, group="master")
    wave.add("mosi", r.mosi, group="master")
    wave.add("miso", r.miso, group="slave")
    labels = ["-"] * len(r.miso)
    for i, edge in enumerate(rising_edges(r.sclk)):
        labels[edge] = f"d{7 - i if msb_first else i}"
    wave.add("sample", labels)

    assert r.cpu.rx_fifo == [rx], "the slave's byte, pushed as CS rose"
    assert r.cpu.in_shift_reg == rx, "master's input shift register"
    assert [r.miso[e] for e in rising_edges(r.sclk)] == wire_bits(rx, msb_first), "what was on MISO at each edge"
    assert sampled(r.mosi, r.sclk) == wire_bits(tx, msb_first), "transmit still works"
    assert r.cpu.shift_reg == 0, "the byte sent has fully left the output register"


@pytest.mark.parametrize("rx", BYTES, ids=lambda b: f"{b:#04x}")
def test_miso_is_sampled_exactly_on_the_rising_edge_cycle(duplex, rx):
    """The simulator contract SHIFT_IN's side effect leans on: the sample is the
    level MISO holds as the cycle that raises SCLK executes, not the cycle
    before and not the one after. A slave that is right only on that cycle
    and wrong on every other still gets its byte through."""
    edges = rising_edges(run(duplex, [0]).sclk)  # transmit does not depend on MISO
    assert len(edges) == 8
    r = run(duplex, [0], edge_only_slave(rx, is_msb(duplex), edges))
    assert r.cpu.rx_fifo == [rx]
    for e in edges:
        assert r.miso[e - 1] != r.miso[e] != r.miso[e + 1], "the slave really was wrong around the edge"


def test_duplex_timing_is_the_tx_timing(duplex):
    """SHIFT_IN raising the clock costs no cycles: the pin traces of a duplex
    program are those of its transmit-only twin, cycle for cycle."""
    twin = TX[DUPLEX.index(duplex)]
    for byte in BYTES:
        assert run(duplex, [byte], mode0_slave(0x96, is_msb(duplex)))[:3] == run(twin, [byte])[:3]


def test_only_shift_in_fills_the_input_register_and_only_push_the_rx_fifo(program):
    r = run(program, [0xA3], mode0_slave(0x5C, is_msb(program)))
    duplex = program in DUPLEX
    assert r.cpu.in_shift_reg == (0x5C if duplex else 0)
    assert r.cpu.rx_fifo == ([0x5C] if duplex else [])


def test_byte_is_pushed_on_the_edge_cs_rises(duplex):
    """Nothing is in the RX FIFO while CS is low; the byte lands on the cycle
    CS goes high, which is the frame's last instruction."""
    cpu = CPU(load_program(duplex), tx_data=[0xA3])
    slave = mode0_slave(0x5C, is_msb(duplex))
    seen = []
    while not cpu.halted:
        cpu.gpio_in[MISO] = slave(cpu)
        cpu.step()
        seen.append((cpu.gpio[CS], list(cpu.rx_fifo)))
    (rise,) = rising_edges(cpu.pin_trace(CS))
    assert all(fifo == [] for _, fifo in seen[:rise])
    assert seen[rise] == (1, [0x5C]) and seen[-1] == (1, [0x5C])
