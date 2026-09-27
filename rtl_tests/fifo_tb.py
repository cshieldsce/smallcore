"""cocotb tests for rtl/fifo.v on its own, before it goes anywhere near
core.v. Run through test_fifo.py, not directly.

Inputs change on the falling edge and are checked just after the rising edge,
once the nonblocking assignments have settled, so every check sees exactly one
edge's worth of change. DEPTH is the default 4.
"""

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from tb import reset, start_clock

DEPTH = 4


async def start(dut):
    """Clock running, inputs idle, reset done and settled."""
    dut.push.value = 0
    dut.pop.value = 0
    dut.push_data.value = 0
    start_clock(dut)
    await reset(dut)
    await ReadOnly()


async def edge(dut, push=0, pop=0, data=0):
    """Drive push/pop/push_data for one rising edge, then settle. The next
    edge() drives new values on the falling edge before the next rise, so a
    push or pop here lasts exactly one edge."""
    await FallingEdge(dut.clk)
    dut.push.value = push
    dut.pop.value = pop
    dut.push_data.value = data
    await RisingEdge(dut.clk)
    await ReadOnly()


def state(dut):
    return {
        "empty": int(dut.empty.value),
        "full": int(dut.full.value),
        "count": int(dut.count.value),  # internal, read through VPI
    }


async def drain(dut):
    """Pop until empty, returning the bytes in the order they came out."""
    out = []
    while not int(dut.empty.value):
        out.append(int(dut.head_data.value))
        await edge(dut, pop=1)
    return out


@cocotb.test()
async def reset_state(dut):
    """After reset: empty, not full, nothing counted, both pointers at 0."""
    await start(dut)

    assert int(dut.empty.value) == 1
    assert int(dut.full.value) == 0
    assert int(dut.count.value) == 0
    assert int(dut.rd_ptr.value) == 0
    assert int(dut.wr_ptr.value) == 0


@cocotb.test()
async def push_then_pop(dut):
    """One byte in shows up at the head; popping it empties the FIFO."""
    await start(dut)

    await edge(dut, push=1, data=0xA5)
    assert int(dut.head_data.value) == 0xA5
    assert state(dut) == {"empty": 0, "full": 0, "count": 1}

    await edge(dut, pop=1)
    assert state(dut) == {"empty": 1, "full": 0, "count": 0}


@cocotb.test()
async def fifo_ordering(dut):
    """Bytes come out in the order they went in."""
    await start(dut)

    for byte in (0x11, 0x22, 0x33):
        await edge(dut, push=1, data=byte)
    assert state(dut) == {"empty": 0, "full": 0, "count": 3}

    assert await drain(dut) == [0x11, 0x22, 0x33]


@cocotb.test()
async def push_when_full_ignored(dut):
    """DEPTH pushes fill it; a further push with no pop changes nothing, and
    the original bytes still drain out in order."""
    await start(dut)

    data = [0x11, 0x22, 0x33, 0x44]
    for byte in data:
        await edge(dut, push=1, data=byte)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}
    wr_ptr = int(dut.wr_ptr.value)

    await edge(dut, push=1, data=0xEE)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}
    assert int(dut.wr_ptr.value) == wr_ptr
    assert int(dut.head_data.value) == 0x11

    assert await drain(dut) == data


@cocotb.test()
async def push_pop_while_full(dut):
    """Full, then push and pop on the same edge: the head leaves, the new byte
    lands in the slot it frees, and the FIFO stays full. With DEPTH 4 and both
    pointers at 0, the write wraps onto slot 0 as the read moves to slot 1, so
    this proves the circular buffer, not just single pushes and pops."""
    await start(dut)

    for byte in (0x11, 0x22, 0x33, 0x44):
        await edge(dut, push=1, data=byte)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}

    await edge(dut, push=1, pop=1, data=0x55)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}
    assert int(dut.head_data.value) == 0x22

    assert await drain(dut) == [0x22, 0x33, 0x44, 0x55]
