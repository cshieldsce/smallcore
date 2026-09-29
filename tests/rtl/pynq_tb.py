"""cocotb tests for fpga/pynq_z2/smallcore_pynq.v: the board wrapper is a
host made of buttons. With the PMOD loopback (ja[0] MOSI to ja[3] MISO)
modelled here, the button sequence BTN3, BTN0, BTN1, BTN2 lights 0x96 on the
LEDs. DEBOUNCE_BITS is 3 in simulation, so a press is 2**3 core clocks long
at least. Run through test_pynq.py."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly

RUN, TX, POP, RST = 0, 1, 2, 3  # btn
PRESS = 80  # sysclk cycles a press lasts: 20 core clocks, past the 8 debounce steps and the 2 sync flops
HALTED, RX_EMPTY = 0b100, 0b001


def leds(dut):
    """host_rdata as the board shows it: LD0..3, LD4 r/g/b, LD5 r."""
    return (
        int(dut.led.value)
        | (int(dut.led4_r.value) << 4)
        | (int(dut.led4_g.value) << 5)
        | (int(dut.led4_b.value) << 6)
        | (int(dut.led5_r.value) << 7)
    )


async def press(dut, button, cycles=PRESS):
    await FallingEdge(dut.sysclk)
    dut.btn.value = 1 << button
    await ClockCycles(dut.sysclk, cycles)
    await FallingEdge(dut.sysclk)
    dut.btn.value = 0
    await ClockCycles(dut.sysclk, PRESS)


async def pmod_loopback(dut):
    """The PMOD with a jumper from pin 1 (ja[0], MOSI) to pin 4 (ja[3], MISO).
    Verilator's --pins-inout-enables makes the inout ja the input side alone
    (what the wrapper drives lives in ja__out/ja__en, which VPI does not
    expose), so the bench is the wire, resolved from smallcore's pads every
    falling edge: a driven pin reads its own level, a released pin reads the
    jumper, or 1 with nothing on it."""
    while True:
        await FallingEdge(dut.sysclk)
        out = int(dut.smallcore_i.gpio_out.value)
        oe = int(dut.smallcore_i.gpio_oe.value)
        level = [(out >> k) & 1 if (oe >> k) & 1 else 1 for k in range(4)]
        if not (oe >> 3) & 1:
            level[3] = level[0]
        dut.ja.value = sum(level[k] << k for k in range(4))


@cocotb.test()
async def buttons_run_spi_loopback_and_show_the_byte(dut):
    Clock(dut.sysclk, 8, unit="ns").start()
    dut.sw.value = 0
    dut.btn.value = 0
    cocotb.start_soon(pmod_loopback(dut))
    await ClockCycles(dut.sysclk, 100)  # power-on reset
    await press(dut, RST)
    await ReadOnly()
    assert leds(dut) == 0, "RX_DATA of an empty FIFO"
    await FallingEdge(dut.sysclk)
    dut.sw.value = 0b10  # STATUS on the LEDs
    await ReadOnly()
    assert leds(dut) == HALTED | RX_EMPTY
    await press(dut, RUN)
    await ReadOnly()
    assert leds(dut) == RX_EMPTY, "running, stalled on PULL"
    await press(dut, TX)
    await ClockCycles(dut.sysclk, 1200)  # the frame, at 4 sysclk per core clock
    await ReadOnly()
    assert leds(dut) == HALTED, "halted, a byte waiting"
    await FallingEdge(dut.sysclk)
    dut.sw.value = 0
    await ReadOnly()
    assert leds(dut) == 0x96
    await press(dut, POP)
    await FallingEdge(dut.sysclk)
    dut.sw.value = 0b10
    await ReadOnly()
    assert leds(dut) == HALTED | RX_EMPTY


@cocotb.test()
async def a_short_bounce_is_ignored(dut):
    """A press shorter than the debounce is a bounce: no CONTROL write. The
    bounce is 4 core clocks, long enough to be a valid strobe by the bus rules
    (3 high, addr held), so only the debounce stands between it and a
    restart; a 2-clock press would be dropped by the host's own edge timing
    with or without a debounce."""
    Clock(dut.sysclk, 8, unit="ns").start()
    dut.sw.value = 0b10
    dut.btn.value = 0
    cocotb.start_soon(pmod_loopback(dut))
    await ClockCycles(dut.sysclk, 100)
    await press(dut, RST)
    await press(dut, RUN, cycles=16)  # 4 core clocks: a strobe, but under the 8 debounce steps
    await ReadOnly()
    assert leds(dut) == HALTED | RX_EMPTY, "still halted: the bounce did nothing"
