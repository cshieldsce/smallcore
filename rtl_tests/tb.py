"""Test bench pieces shared by the cocotb tests: clock, reset, the instruction
memory the core reads from, and the architectural state in one shape for both
the RTL and the Python model (sim/cpu.py), so the two can be compared with ==.

Nothing here executes instructions. The model does that in cpu.py, the core
does it in core.v; the bench only feeds them the same inputs and reads them back.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

CLK_PERIOD_NS = 10


def start_clock(dut):
    """Toggle dut.clk forever in the background, rising edge first."""
    Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start()


async def reset(dut, cycles=2):
    """Hold reset for `cycles` rising edges, then release it. core.v resets
    synchronously, so the state is the reset state after the first edge."""
    dut.reset.value = 1
    await ClockCycles(dut.clk, cycles)
    dut.reset.value = 0


def drive_inputs(dut, program_words, tx_empty=0, rx_full=0, gpio_in=0, tx_data=0):
    """Drive every input besides clk, reset and imem_word so none is X. The
    defaults are a non-blocking environment: nothing waits on a FIFO flag or a
    pin. A WAIT or FIFO test passes its own values."""
    dut.program_words.value = program_words
    dut.tx_empty.value = tx_empty
    dut.rx_full.value = rx_full
    dut.gpio_in.value = gpio_in
    dut.tx_data.value = tx_data


def drive_host(dut, program_words):
    """top.v's inputs besides clk, reset and imem_word, with the host idle:
    nothing pushed, nothing popped, no restart, the input pins low. The FIFO
    flags are top's own wires; the host sees tx_full and rx_empty."""
    dut.restart.value = 0
    dut.program_words.value = program_words
    dut.gpio_in.value = 0
    dut.tx_data.value = 0
    dut.tx_push.value = 0
    dut.rx_pop.value = 0


class Imem:
    """Combinational instruction memory: imem_word follows imem_addr in the
    same time step, like the model's `self.program[self.pc]`. A background task
    rewrites imem_word every time imem_addr changes. Past the end of the
    program it reads 0; the model halts there, so a comparison stops first."""

    def __init__(self, dut, program):
        self.dut = dut
        self.program = list(program)
        cocotb.start_soon(self._drive())

    def read(self, addr):
        return self.program[addr] if addr < len(self.program) else 0

    def load(self, program):
        """Swap in another program without restarting the task, for a bench
        that runs several in one test. Rewrites imem_word now, so call it
        between edges, not in the read-only phase; the task keeps following
        imem_addr from here."""
        self.program = list(program)
        self.dut.imem_word.value = self.read(int(self.dut.imem_addr.value))

    async def _drive(self):
        while True:
            self.dut.imem_word.value = self.read(int(self.dut.imem_addr.value))
            await self.dut.imem_addr.value_change


def gpio_bits(value):
    """gpio[3:0] as a list indexed by pin, the shape of CPU.gpio."""
    return [(int(value) >> pin) & 1 for pin in range(4)]


# Architectural state, one dict per side with the same keys. Internal regs
# (pc, delay_counter) are read straight out of the design: cocotb's Verilator
# build uses --public-flat-rw, which keeps every signal visible, so no debug
# ports. Add a key to both functions as the core grows (shift_reg,
# in_shift_reg, ...).

def rtl_state(dut):
    return {
        "pc": int(dut.pc.value),
        "counter": int(dut.delay_counter.value),
        "rc": int(dut.rc.value),
        "gpio": gpio_bits(dut.gpio_out.value),
        "halted": bool(dut.halted.value),
        "shift_dir": int(dut.shift_dir.value),
        "open_drain": gpio_bits(dut.open_drain.value),
        "gpio_oe": gpio_bits(dut.gpio_oe.value),
        "shift_reg": int(dut.shift_reg.value),
        "in_shift_reg": int(dut.in_shift_reg.value),
    }


def model_state(cpu):
    return {
        "pc": cpu.pc,
        "counter": cpu.counter,
        "rc": cpu.rc,
        "gpio": list(cpu.gpio),
        "halted": cpu.halted,
        "shift_dir": cpu.shift_dir,
        "open_drain": list(cpu.open_drain),
        "gpio_oe": list(cpu.gpio_oe),
        "shift_reg": cpu.shift_reg,
        "in_shift_reg": cpu.in_shift_reg,
    }


def drive_smallcore(dut):
    """smallcore's inputs besides clk and reset, host idle: no strobe, addr on
    STATUS so host_rdata shows the flags, pads read 1 until Pads takes over."""
    dut.host_wdata.value = 0
    dut.host_addr.value = 2
    dut.host_we.value = 0
    dut.host_re.value = 0
    dut.gpio_in.value = 0b1111


class Pads:
    """Four bidirectional pads on smallcore, resolved on every falling edge of
    clk so gpio_in is settled before the rising edge the core samples on. Pad k
    reads its own gpio_out[k] while gpio_oe[k] drives, else what the outside
    drives: a level from set(), a function from attach(), a wire from another
    pad, or 1 from a weak pull-up when nothing does. A pad driving against an
    outside level is a fight, which no working program ever has: it fails here.

    attach(pin, fn): fn(out, oe) is called with the 4-bit gpio_out and gpio_oe
    each falling edge and returns the outside level for that pin, or None.
    wires: [(from_pin, to_pin)], to_pin reads from_pin's resolved level when
    it is not driving, the board's loopback jumper."""

    def __init__(self, dut, wires=()):
        self.dut = dut
        self.level = [None] * 4
        self.fn = [None] * 4
        self.wires = {to: frm for frm, to in wires}
        cocotb.start_soon(self._run())

    def set(self, pin, level):
        self.level[pin] = level

    def attach(self, pin, fn):
        self.fn[pin] = fn

    def _outside(self, k, out, oe, resolved):
        outside = self.fn[k](out, oe) if self.fn[k] else self.level[k]
        if outside is None and k in self.wires:
            src = self.wires[k]
            outside = resolved[src] if resolved[src] is not None else self._resolve(src, out, oe, resolved)
        return outside

    def _resolve(self, k, out, oe, resolved):
        driving, level = (oe >> k) & 1, (out >> k) & 1
        outside = self._outside(k, out, oe, resolved)
        assert not (driving and outside is not None and outside != level), (
            f"pad {k}: driving {level} against the outside's {outside}"
        )
        return level if driving else (1 if outside is None else outside)

    async def _run(self):
        while True:
            await FallingEdge(self.dut.clk)
            out, oe = int(self.dut.gpio_out.value), int(self.dut.gpio_oe.value)
            resolved = [None] * 4
            for k in range(4):
                resolved[k] = self._resolve(k, out, oe, resolved)
            self.dut.gpio_in.value = sum(resolved[k] << k for k in range(4))
