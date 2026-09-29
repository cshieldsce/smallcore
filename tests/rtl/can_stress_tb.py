"""cocotb tests for rtl/top.v on two CAN stress programs, run through
test_can_stress.py. The two that lean on something the model claims about
the hardware and no other pin test covers:

  can_rx_dlc.asm      a receiver whose length follows the DLC it sampled: a
                      tree of SKIP cells into a chain of loops, 237 words
  can_rx_check.asm    a stuff error answered with an error flag through a JMP
                      out of a REPEAT body, which the assembler refuses and
                      is patched in; rc drained by a two-word loop, then the
                      next frame received whole

Each runs on top.v and on the model against the same bench, a bench
transmitter or two on the bus, and the bus and the host's bytes must match
clock for clock from the first SOF."""

import importlib.util
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "model"), str(ROOT / "tests" / "model")]

from cpu import CPU  # noqa: E402
from tb import Imem, drive_host, reset, start_clock  # noqa: E402
from test_can import GAP, frame_bits, frame_names, stuffed  # noqa: E402

_spec = importlib.util.spec_from_file_location("can_stress_gen", ROOT / "experiments" / "can_stress" / "gen.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

BIT = 8
POLY = [0x32, 0x8B]
SAMPLE = 6


class Sender:
    """A bench transmitter: from update call `at`, `bits` a bit every BIT clocks, a 0 driven, a 1 let go;
    the ACK slot `slot` let go and its level kept as `acked`; with `abort`, it stops at a recessive bit
    it sees dominant outside the slot, as CAN's transmitter does on an error flag."""

    def __init__(self, bits, at, slot, abort=False):
        self.bits, self.at, self.slot, self.abort = list(bits), at, slot, abort
        self.i, self.acked = -1, None

    def update(self, line):
        self.i += 1
        k, phase = divmod(self.i - self.at, BIT)
        if 0 <= k < len(self.bits) and phase == SAMPLE:
            if k == self.slot:
                self.acked = line == 0
            elif self.abort and self.bits[k] == 1 and line == 0:
                self.bits = self.bits[:k]
        return 0 if 0 <= k < len(self.bits) and self.bits[k] == 0 and k != self.slot else None


def model_run(words, nodes, clocks):
    """The model on the bench: the bus a clock at a time, the host popping every byte."""
    cpu = CPU(words, gpio_in=1, tx_data=list(POLY))
    bus, got, line = [], [], 1
    for _ in range(clocks):
        if not cpu.halted:
            cpu.step()
        drives = [node.update(line) for node in nodes]
        pad = cpu.gpio[0] if cpu.gpio_oe[0] == 1 else None
        line = 0 if pad == 0 or 0 in drives else 1
        cpu.gpio_in[0] = line
        bus.append(line)
        got.extend(cpu.rx_fifo)
        cpu.rx_fifo.clear()
    return bus, got


async def pins_run(dut, words, nodes, clocks, state):
    """top.v on the bench: the host pushes the polynomial and pops every byte; the bus a clock at a time.
    `state` is the test's own: the clock and the Imem task are started once a test."""
    first = "imem" not in state
    if first:
        dut.imem_word.value = 0
    else:
        await FallingEdge(dut.clk)
    drive_host(dut, program_words=0)
    dut.gpio_in.value = 0b0001
    if first:
        start_clock(dut)
    await reset(dut)
    await FallingEdge(dut.clk)
    if first:
        state["imem"] = Imem(dut, words)
    else:
        state["imem"].load(words)
    queue, got, bus, line = list(POLY), [], [], 1
    dut.program_words.value = len(words)
    for _ in range(clocks):
        await FallingEdge(dut.clk)
        dut.tx_push.value = 0
        dut.rx_pop.value = 0
        if int(dut.rx_empty.value) == 0:
            got.append(int(dut.rx_data.value))
            dut.rx_pop.value = 1
        if queue and not int(dut.tx_full.value):
            dut.tx_data.value = queue.pop(0)
            dut.tx_push.value = 1
        out, oe = int(dut.gpio_out.value), int(dut.gpio_oe.value)
        drives = [node.update(line) for node in nodes]
        pad = out & 1 if oe & 1 else None
        assert not (pad == 1 and 0 in drives), "the pad drives a 1 against a dominant 0"
        line = 0 if pad == 0 or 0 in drives else 1
        dut.gpio_in.value = 0b1110 & int(dut.gpio_in.value) | line
        bus.append(line)
        await RisingEdge(dut.clk)
        await ReadOnly()
    return bus, got


def from_sof(bus):
    return bus[bus.index(0) :]


@cocotb.test()
async def can_receiver_follows_the_dlc_at_the_pins(dut):
    """can_rx_dlc.asm on top.v, a DLC 8 frame and then (a second run) a DLC 3 one: the bus clock for clock
    the model's from the SOF, the same bytes, bit 0 of each the destuffed stream, the residue 0, 0, acked."""
    words = gen.assemble(gen.rx_dlc())
    state = {}
    for ident, data in ((0x123, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]), (0x7C1, [0x00, 0xFF, 0x3C])):
        bits = stuffed(frame_bits(ident, data)) + [1, 1, 1] + [1] * GAP
        clocks = 40 + (len(bits) + 6) * BIT
        slot = len(bits) - GAP - 2
        pins_tx, model_tx = Sender(bits, 40, slot), Sender(bits, 40, slot)
        bus, got = await pins_run(dut, words, [pins_tx], clocks, state)
        model_bus, model_got = model_run(words, [model_tx], clocks)
        stream = frame_bits(ident, data)
        assert from_sof(bus) == from_sof(model_bus)[: len(from_sof(bus))]
        assert got == model_got and [b & 1 for b in got[: len(stream)]] == stream and got[len(stream) :] == [0, 0]
        assert pins_tx.acked and model_tx.acked


@cocotb.test()
async def can_stuff_error_flag_and_rc_drain_at_the_pins(dut):
    """can_rx_check.asm on top.v: 0x5A3 carrying 0x00 with the stuff bit after the data's five dominant
    bits left out, in the 24th run of a 32-run body. The JMP out of the body, the error flag, the 0x00
    marker, the rc drain, the acc clear and the idle wait are the model's clock for clock; the next frame
    is received whole with the residue 0, 0. The early exit behaves on the hardware as the model says."""
    words = gen.patched(gen.rx(42, check=True))
    names = frame_names(0x5A3, [0x00])
    full = stuffed(frame_bits(0x5A3, [0x00]))
    k = next(i for i, name in enumerate(names) if name == "stuff" and i > 20)
    bad = full[:k] + full[k + 1 :] + [1, 1, 1] + [1] * GAP
    good = stuffed(frame_bits(0x0F3, [0x3C])) + [1, 1, 1] + [1] * GAP
    good_at = 120 + (len(bad) + 30) * BIT
    clocks = good_at + (len(good) + 4) * BIT

    def bench():
        return [Sender(bad, 120, len(bad) - GAP - 2, abort=True), Sender(good, good_at, len(good) - GAP - 2)]

    pins_nodes, model_nodes = bench(), bench()
    bus, got = await pins_run(dut, words, pins_nodes, clocks, {})
    model_bus, model_got = model_run(words, model_nodes, clocks)
    assert from_sof(bus) == from_sof(model_bus)[: len(from_sof(bus))]
    assert got == model_got and 0x00 in got
    after = got[got.index(0x00) + 1 :]
    assert [b & 1 for b in after[:42]] == frame_bits(0x0F3, [0x3C]) and after[42:44] == [0, 0]
    assert pins_nodes[1].acked
