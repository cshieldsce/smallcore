"""Test bench pieces shared by the cocotb tests: clock, reset, the instruction
memory the core reads from, and the architectural state in one shape for both
the RTL and the Python model (sim/cpu.py), so the two can be compared with ==.

Nothing here executes instructions. The model does that in cpu.py, the core
does it in core.v; the bench only feeds them the same inputs and reads them back.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

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


def drive_inputs(dut, program_words, tx_empty=0, rx_full=0, gpio_in=0):
    """Drive every input besides clk, reset and imem_word so none is X. The
    defaults are a non-blocking environment: nothing waits on a FIFO flag or a
    pin. A WAIT or FIFO test passes its own values."""
    dut.program_words.value = program_words
    dut.tx_empty.value = tx_empty
    dut.rx_full.value = rx_full
    dut.gpio_in.value = gpio_in


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
# in_shift_reg, shift_dir, open_drain, ...).

def rtl_state(dut):
    return {
        "pc": int(dut.pc.value),
        "counter": int(dut.delay_counter.value),
        "gpio": gpio_bits(dut.gpio_out.value),
        "halted": bool(dut.halted.value),
    }


def model_state(cpu):
    return {
        "pc": cpu.pc,
        "counter": cpu.counter,
        "gpio": list(cpu.gpio),
        "halted": cpu.halted,
    }
