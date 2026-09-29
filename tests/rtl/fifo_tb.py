"""cocotb tests for rtl/fifo.v on its own, before it goes anywhere near
core.v. Run through test_fifo.py, not directly.

Inputs change on the falling edge and are checked just after the rising edge,
once the nonblocking assignments have settled, so every check sees exactly one
edge's worth of change. test_fifo.py builds the FIFO at more than one DEPTH and
passes it in FIFO_DEPTH, so every test sizes itself from DEPTH: 4 is the power
of two a plain pointer overflow would get right by accident, 3 is not.
"""

import os

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from tb import reset, start_clock

DEPTH = int(os.environ["FIFO_DEPTH"])
FILL = [0x11 * (i + 1) for i in range(DEPTH)]  # 11 22 33 ..., one per slot
NEXT = 0x11 * (DEPTH + 1)  # the byte after FILL: 44 at DEPTH 3


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
    assert state(dut) == {"empty": 0, "full": int(DEPTH == 3), "count": 3}

    assert await drain(dut) == [0x11, 0x22, 0x33]


@cocotb.test()
async def push_when_full_ignored(dut):
    """DEPTH pushes fill it; a further push with no pop changes nothing, and
    the original bytes still drain out in order."""
    await start(dut)

    for byte in FILL:
        await edge(dut, push=1, data=byte)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}
    wr_ptr = int(dut.wr_ptr.value)

    await edge(dut, push=1, data=0xEE)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}
    assert int(dut.wr_ptr.value) == wr_ptr
    assert int(dut.head_data.value) == FILL[0]

    assert await drain(dut) == FILL


@cocotb.test()
async def push_pop_while_full(dut):
    """Full, then push and pop on the same edge: the head leaves, the new byte
    lands in the slot it frees, and the FIFO stays full. Both pointers are at
    0, so the write wraps onto slot 0 as the read moves to slot 1: this proves
    the circular buffer, not just single pushes and pops."""
    await start(dut)

    for byte in FILL:
        await edge(dut, push=1, data=byte)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}

    await edge(dut, push=1, pop=1, data=0x55)
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}
    assert int(dut.head_data.value) == FILL[1]

    assert await drain(dut) == FILL[1:] + [0x55]


@cocotb.test()
async def push_pop_while_empty_is_push(dut):
    """Empty, then push and pop on the same edge: there is nothing to pop, so
    it is a push only. The byte is at the head and counted."""
    await start(dut)
    assert state(dut) == {"empty": 1, "full": 0, "count": 0}

    await edge(dut, push=1, pop=1, data=0xA5)
    assert state(dut) == {"empty": 0, "full": 0, "count": 1}
    assert int(dut.head_data.value) == 0xA5

    assert await drain(dut) == [0xA5]


@cocotb.test()
async def pointers_wrap_at_depth(dut):
    """Fill, pop one, push one: the write pointer must go LAST -> 0, not on to
    DEPTH. At DEPTH 3 that is 11 22 33, pop 11, push 44, drain 22 33 44; a
    pointer that just overflows would sit at the nonexistent slot 3. Draining
    then wraps the read pointer the same way."""
    await start(dut)

    for byte in FILL:
        await edge(dut, push=1, data=byte)
    assert int(dut.wr_ptr.value) == 0  # wrapped after the last slot

    await edge(dut, pop=1)
    assert int(dut.rd_ptr.value) == 1
    await edge(dut, push=1, data=NEXT)
    assert int(dut.wr_ptr.value) == 1
    assert state(dut) == {"empty": 0, "full": 1, "count": DEPTH}

    assert await drain(dut) == FILL[1:] + [NEXT]
    assert int(dut.rd_ptr.value) == 1  # read pointer wrapped too
