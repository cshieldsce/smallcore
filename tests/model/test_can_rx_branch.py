"""A, the branch, on the FIFO receiver: the one measurement A was short of
after RX (docs/can-candidates.md, "Decided"). can_rx_bits.asm needs nine
clocks a bit because the dominant tree's longest path, SKIP, JMP, four
SKIPs, is one cycle too long for the PUSH at eight; with BRANCH the JMP
goes. The splice, experiments/can/can_rx_bits_A.asm, on candidate A's model
against tests/model/test_can_rx.py's bench transmitter at eight clocks a bit."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("can_candidates", ROOT / "experiments" / "can" / "candidates.py")
candidates = sys.modules.get("can_candidates") or importlib.util.module_from_spec(_spec)
if "can_candidates" not in sys.modules:
    sys.modules["can_candidates"] = candidates
    _spec.loader.exec_module(candidates)
CANDIDATES, load_candidate = candidates.CANDIDATES, candidates.load_program

from cpu import load_program  # noqa: E402
from test_can import BIT, IDENT, Glitch, frame_bits  # noqa: E402
from test_can_rx import AT, BITS, BITS_BIT, RX_SAMPLE, frame_on_the_bus, run_rx, stuff_positions  # noqa: E402
RX_VECTORS = ((0x5A3, 0x5A), (0x7FF, 0xFF), (0x000, 0x00), (0x07C, 0x00), (0x555, 0xAA), (0x123, 0x01))


def rx_bits_a(ident, data, bit=BIT, host=None, drain=True, glitch=None):
    """can_rx_bits_A.asm on candidate A against the bench transmitter at `bit` clocks a bit."""
    cls = CANDIDATES["A"]
    cpu = cls(load_candidate("can_rx_bits_A", cls), gpio_in=1)
    return run_rx(None, ident, [data], bit=bit, host=host, drain=drain, glitch=glitch, cpu=cpu)


@pytest.mark.parametrize("ident, data", RX_VECTORS, ids=lambda v: f"{v:03x}" if v > 0xFF else f"{v:02x}")
def test_a_makes_the_fifo_receiver_an_eight_clock_one(ident, data):
    """can_rx_bits.asm needs nine clocks a bit because the dominant tree's
    longest path, SKIP, JMP, four SKIPs, is one cycle too long for the PUSH
    at eight. With BRANCH the JMP goes: five branches on either side, the
    exits into a ladder of NOPs, and the cell is one SHIFT_IN, the PUSH,
    five of decision and the REPEAT, eight. Against the transmitter at
    eight clocks a bit: bit 0 of the 42 bytes is the destuffed stream, the
    ACK lands, the FIFO holds one with a prompt host, no stall."""
    r, tx = rx_bits_a(ident, data, bit=BIT)
    assert [byte & 1 for byte in r.received] == frame_bits(ident, [data])
    assert tx.acked is True and r.rx_peak == 1 and not any(r.stalls[AT + 1 :])
    assert len(r.received) == 42


def test_a_fifo_receiver_samples_the_sixth_clock_and_holds_the_host_to_four_bit_times():
    """The same sample point as the baseline's, the sixth clock: a probe on
    a recessive bit at each clock flips that bit in the stream exactly on
    the sixth. And the same FIFO contract, now at 32 cycles: a host that
    reads nothing for four bit times is fine, five stalls the receiver."""
    ident, data = IDENT, 0x5A
    bits, slot = frame_on_the_bus(ident, [data])
    k = next(k for k in range(8, 30) if bits[k] == 1 and len(set(bits[k - 4 : k])) == 2 and k not in stuff_positions(ident, [data]))
    j = k - sum(1 for s in stuff_positions(ident, [data]) if s < k)
    stream = frame_bits(ident, [data])
    for p in range(BIT):
        r, _ = rx_bits_a(ident, data, bit=BIT, glitch=Glitch(AT + k * BIT + p))
        hit = p == RX_SAMPLE - 1
        assert [byte & 1 for byte in r.received] == stream[:j] + [0 if hit else 1] + stream[j + 1 :], f"pulse on clock {p + 1}"
    first = AT + RX_SAMPLE + 1
    for sleep, fine in ((4, True), (5, False)):
        def host(cpu, received, sleep=sleep):
            if cpu.cycle >= first + sleep * BIT and cpu.rx_fifo:
                received.append(cpu.rx_fifo.pop(0))
        r, tx = rx_bits_a(ident, data, bit=BIT, drain=False, host=host)
        got = [byte & 1 for byte in r.received]
        assert (not any(r.stalls[AT + 1 :]) and got == stream) == fine, f"asleep for {sleep} bit times"


def test_a_fifo_receiver_by_the_numbers():
    """The splice measured against the baseline: 8 clocks a bit for 9, the
    decision five cycles on both sides for five and six, 19 words a cell for
    24, 47 words for 57; the same bytes to the host, the same ACK; and the
    BRANCH count of the whole program, the shape RX keeps producing: SKIP,
    JMP, pad, the next sample, as one word each."""
    cls = CANDIDATES["A"]
    words = load_candidate("can_rx_bits_A", cls)
    base = load_program(BITS)
    assert (len(words), len(set(words)), len(base)) == (47, 27, 57)
    assert sum(1 for w in words if cls.decode(w).op == "BRANCH") == 18
    r, tx = rx_bits_a(IDENT, 0x5A, bit=BIT)
    samples = [i for i, op in enumerate(r.issues) if op == "SHIFT_IN"]
    assert [b - a for a, b in zip(samples[1:], samples[2:])] == [BIT] * (len(samples) - 2), "every bus bit sampled eight clocks apart"
    base_r, base_tx = run_rx(BITS, IDENT, [0x5A], bit=BITS_BIT)
    assert r.received == base_r.received and tx.acked == base_tx.acked
