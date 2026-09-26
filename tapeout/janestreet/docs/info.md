<!---
Tiny Tapeout datasheet source. Filled in as the design settles; today it describes the elaboration baseline.
-->

## How it works

SmallCore is a PIO-style programmable protocol engine. A program of 16-bit words runs one word per cycle plus a per-word delay; each word can shift a bit out or in, move a byte between a shift register and a FIFO, wait on an input level, skip on a bit of the received byte, jump, or set configuration, and every word can drive one GPIO pin as a side effect on the same edge. The architecture, simulator, assembler and tests live in the repository root; `src/core.v` is staged from `rtl/core.v`.

The current wrapper is provisional: it exists so the CMOS5L flow can elaborate and place the core while the host interface and pin mapping are still open.

## How to test

`test/` holds a cocotb smoke test of the wrapper. The cycle-accurate tests run against the Python golden model in the repository root (`make test`).

## External hardware

None decided yet.
