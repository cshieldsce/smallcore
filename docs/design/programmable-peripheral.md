# SmallCore as a programmable peripheral: program ROM, host interface, FPGA smoke test

Date: 2026-09-27. Builds on Baseline v1 (tag `v1`).

## Goal

Prove that SmallCore can be packaged as a usable programmable protocol peripheral, not only that it can implement UART, SPI and I²C under a test bench. A developer at a fixed chip-level interface selects a compiled protocol program, queues bytes, runs it, sees completion and status, and retrieves results, with nothing outside the chip supplying instruction memory.

The experiment is deliberately small. It is not the final ASIC program loader. It ends when:

1. `spi_duplex_msb` runs from a real on-chip ROM through a real host register interface, with real FIFOs and real pad-level pins, in RTL under cocotb, and the host reads back the byte the far end sent.
2. The same RTL, in a PYNQ-Z2 wrapper with MOSI jumpered to MISO, returns the byte the host wrote.

Stretch goals (JTAG/SWD, CAN, Ethernet) come after and are out of scope here.

## Decisions already taken

| decision | choice | why |
|---|---|---|
| host at the far end | an MCU, FPGA or bench controller on a tiny register bus, not switches and LEDs, not a serial console | answers "could someone integrate this as a peripheral"; a console would validate a second UART on top of SmallCore; switches do not fit the chip pins |
| program storage | one ROM per program, looked up by `(sel, addr)`; every program starts at address 0 | absolute 8-bit `JMP` targets need no relocation; all 272 words of the eleven programs go in; no ISA change |
| program select | latched by a CONTROL write, which restarts the core; no live switching | simplest defined behaviour; a CONTROL write mid-program is an abort/restart by definition |
| reset split | hard reset clears core, both FIFOs and `sel`; CONTROL restart resets the core only | queued TX bytes survive a restart, so a one-shot program can be run again on the next byte; the host drains stale RX |
| slot 0 and invalid slots | slot 0 and slots 12..15 read `program_words = 0`, `imem_word = 0` | a fresh chip after hard reset sits halted until the host selects; no aliasing, no X |
| strobes | `we` and `re` pass a 2-flop synchronizer and a rising-edge detector | an MCU on GPIO cannot make one-clock pulses; the host holds a strobe ≥3 core clocks and exactly one push or pop happens |
| status | `halted` is exposed | the only clean way for the host to tell "finished" from "stalled or working"; `halted` means execution finished, the RX FIFO says what the protocol did |
| protocol pins | the four `gpio_out`/`gpio_oe`/`gpio_in` triples collapse onto four bidirectional pads; `gpio_in[k]` is the pad readback of `gpio[k]` | I²C needs output-enable and readback on the same SDA/SCL wires; eight separate pins do not fit 24 |
| programs that listen | `uart_rx`, `spi_duplex_lsb`, `spi_duplex_msb` gain one `CONFIG` word that releases their input pin | with pad readback every pin is push-pull high after reset; "this pin is an input" is the program's statement and the ISA already says it that way, as the I²C programs do. Rejected: a per-slot pad mask in the wrapper (a second source of truth) and a core reset change (moves every existing trace) |

## Chip-level interface

Module `smallcore`, `rtl/smallcore.v`. Its ports are the pad-level signals; a pad wrapper maps them one for one.

| signal | dir | width | Tiny Tapeout pin |
|---|---|---|---|
| `clk`, `reset` | in | 1 | `clk`, `!rst_n` |
| `host_wdata` | in | 8 | `ui[7:0]` |
| `host_rdata` | out | 8 | `uo[7:0]` |
| `host_addr` | in | 2 | `uio[5:4]` as inputs |
| `host_we` | in | 1 | `uio[6]` as input |
| `host_re` | in | 1 | `uio[7]` as input |
| `gpio_out`, `gpio_oe` | out | 4 each | `uio_out[3:0]`, `uio_oe[3:0]` |
| `gpio_in` | in | 4 | `uio_in[3:0]` |

24 pins, none spare. `smallcore` keeps the three GPIO buses separate because synthesizable RTL has no `inout`; the pad wrapper (TT or FPGA) does the collapse: `uio_out[3:0] = gpio_out`, `uio_oe[3:0] = gpio_oe`, `gpio_in = uio_in[3:0]`, and `uio_oe[7:4] = 0` so the host control pins are inputs.

### Register map

`host_rdata` continuously shows the register `host_addr` selects. A write happens on the rising edge of `host_we`, a pop on the rising edge of `host_re`, both decoded against `host_addr` at that moment.

| addr | name | write (`host_we` rises) | read (`host_rdata`) |
|---|---|---|---|
| 0 | TX_DATA | push `host_wdata` into the TX FIFO; dropped if the FIFO is full, the host checks STATUS first | `0x00` |
| 1 | RX_DATA | ignored | RX FIFO head; `host_re` rising with addr 1 pops it, ignored when empty |
| 2 | STATUS | ignored | `{5'b0, halted, tx_full, rx_empty}` |
| 3 | CONTROL | `sel <= host_wdata[3:0]`; the core restarts at pc 0 reading slot `sel`; both FIFOs keep their contents | `{4'b0, sel}` |

`halted` is `pc >= program_words` from the core: 1 while slot 0 or an invalid slot is selected, 1 when a program has run off its end, 0 while a program is issuing, stalled or holding a delay.

### Host timing rules

- `host_we` and `host_re` are held high for at least 3 core clocks per strobe and low for at least 3 core clocks between strobes. Exactly one push, pop or CONTROL write happens per rising edge. Shorter pulses are undefined.
- `host_wdata` and `host_addr` are set before the strobe rises and held until it falls. They are not synchronized internally; the two-flop synchronizer on the strobe gives them at least two clocks of setup.
- A read of `host_rdata` is combinational on `host_addr`; the host samples after the mux settles, any time.
- Hard reset: core, TX FIFO, RX FIFO and `sel` all reset. `sel` = 0, so the core halts.
- CONTROL write while a program runs: an abort/restart. The core resets, so GPIO returns to its reset levels (all four pins push-pull high) mid-transaction if one was in flight. Defined, not accidental. FIFOs untouched.
- A clear-FIFOs control bit is deliberately not added. Hard reset covers this phase.

## Structure

```
rtl/smallcore.v   module smallcore: host + rom + top. The chip. Ports as above.
rtl/host.v        module host: strobe sync + edge detect, address decode, sel, restart, rdata mux
rtl/rom.v         module rom, GENERATED by tools/gen_rom.py from programs/manifest.txt. Do not edit.
rtl/top.v         + input restart; core reset = reset | restart; FIFOs reset on reset only; + output halted
rtl/core.v        halted becomes an output port. No logic change.
rtl/fifo.v        unchanged
```

Alternatives rejected: growing `top` (breaks the interface the 21 existing top tests drive), putting the host block in the Tiny Tapeout wrapper (the PYNQ wrapper would need a copy).

### `host`

Ports: `clk`, `reset`, `wdata[7:0]`, `addr[1:0]`, `we`, `re` in; `tx_full`, `rx_empty`, `rx_data[7:0]`, `halted` in from `top`; `rdata[7:0]`, `tx_push`, `rx_pop`, `sel[3:0]`, `restart` out.

- Each strobe: `s0 <= pin; s1 <= s0; s2 <= s1;` rising `= s1 & !s2`. Three flops per strobe, six in all.
- `tx_push = we_rise && addr == 0`. `rx_pop = re_rise && addr == 1`. `restart = we_rise && addr == 3`, and on that same edge `sel <= wdata[3:0]`.
- `rdata`: `case (addr)` 0 → `8'h00`, 1 → `rx_data`, 2 → `{5'b0, halted, tx_full, rx_empty}`, 3 → `{4'b0, sel}`.
- `sel` resets to 0. Ten flops total.
- `restart` is a one-clock pulse. The core's reset is synchronous and one cycle is enough. On the restart edge `sel` takes its new value, so on the next clock the core is at pc 0 reading the new slot; what the ROM showed during the restart cycle does not matter, the core was in reset.

### `rom`

`module rom(input [3:0] sel, input [7:0] addr, output reg [15:0] word, output reg [8:0] words)`. Combinational: `always @*` with `case ({sel, addr})` for `word` and `case (sel)` for `words`, both `default: 0`. That default covers slot 0, slots 12..15 and every address past a program's end, so no X and no aliasing.

`tools/gen_rom.py` reads `programs/manifest.txt`, assembles each listed `.asm` with `sim/cpu.py`'s `assemble`, and writes `rtl/rom.v`. Deterministic: same inputs, byte-identical output, no timestamps. The header comment names the manifest, the generator and each slot with its program and word count. It is committed because the Tiny Tapeout action builds from the repository.

`make rom` regenerates. `make rom-check` generates to a scratch file and diffs, failing on drift. `make test` depends on `rom-check`. `make lint` covers `rom.v`, `host.v` and `smallcore.v`.

### `top` and `core`

`top` gains `input restart` and `output halted`. Inside: `core_i.reset = reset | restart`; both FIFOs keep `.reset(reset)`. `core` gains `output halted`, the existing `halted` wire. `rtl_tests/tb.py`'s `drive_host` drives `restart = 0`; hierarchical reads of `dut.core_i.halted` and `dut.halted` keep working. Nothing else in the existing benches moves.

## Programs and manifest

`programs/manifest.txt`, one line per slot, `slot file`, with a comment: slots are permanent, a new program takes an unused slot, an old slot never shifts. Slot 0 is NONE and is not a line.

| slot | program | slot | program |
|---|---|---|---|
| 1 | `uart_tx_0x55.asm` | 7 | `spi_duplex_lsb.asm` |
| 2 | `uart_tx_pull.asm` | 8 | `spi_duplex_msb.asm` |
| 3 | `uart_tx_loop.asm` | 9 | `i2c_write.asm` |
| 4 | `uart_rx.asm` | 10 | `i2c_write_stretch.asm` |
| 5 | `spi_tx_lsb.asm` | 11 | `i2c_write_addr_data.asm` |
| 6 | `spi_tx_msb.asm` | | |

Three programs get one word at the top, before anything touches a pin:

| program | listens on | added word | effect |
|---|---|---|---|
| `uart_rx.asm` | gpio 0 | `CONFIG open_drain01, 1` | pin 0 open-drain; with `gpio[0]` at its reset 1 the pad lets go |
| `spi_duplex_lsb.asm`, `spi_duplex_msb.asm` | gpio 3 (MISO) | `CONFIG open_drain23, 2` | pin 3 open-drain, released |

Each adds one cycle before the program's first `PULL` or `WAIT`. Tests that pin absolute cycle counts from reset shift by one and are updated; each updated test is re-checked to still fail under its mutation. Model-versus-RTL lockstep is unaffected, both sides run the same words. The metamorphic LSB/MSB pair stays symmetric because both members change the same way. The I²C programs already release their pins.

## Verification

### `rtl_tests/test_rom.py`, `rom_tb.py`

Verilator builds `rom.v` alone. One test: for every slot 0..15 and every addr 0..255, `word` equals the assembler's word for that manifest entry, or 0 past its end or for slots 0 and 12..15; `words` equals the program length, or 0. Doubles as the drift check in cocotb form.

### `rtl_tests/test_smallcore.py`, `smallcore_tb.py`

Builds `smallcore.v`, `host.v`, `rom.v`, `top.v`, `core.v`, `fifo.v`. The bench is the host and the far end of the wire: it drives only `smallcore`'s ports. A `Pads` helper in `tb.py` resolves `gpio_in[k]` every clock from `gpio_oe[k]`, `gpio_out[k]` and an external driver, like the I²C bus model: driven pin reads its own level, released pin reads the external driver, or 1 if there is none. Bytes are non-palindromic, 0x96 out and 0x53 in, never 0xA5.

Tests, each shown to fail under a mutation of the program, the bench or the RTL before it is kept:

1. **hard reset state**: after reset, STATUS reads `halted=1, tx_full=0, rx_empty=1`, CONTROL reads 0, the core stays at pc 0 with `program_words = 0`, pads all driven high.
2. **strobe edge, not level**: `we` held high 3 clocks with addr 0 pushes once; held 20 clocks pushes once; two writes 3 clocks apart push twice. TX FIFO count read hierarchically.
3. **TX full**: five TX writes; the FIFO holds four, STATUS shows `tx_full`, the fifth byte is not in the FIFO.
4. **CONTROL restarts the core only**: select `spi_tx_msb` with a byte queued, let it get several words in; write CONTROL again; next clock pc is 0, `gpio_out` is back to 1111, the TX FIFO count is unchanged. Then CONTROL 13: STATUS `halted=1`, `program_words = 0`.
5. **queued bytes survive restart**: push 0x96 then 0x3C; CONTROL `spi_tx_msb`; the slave sees 0x96 and the core halts; CONTROL again; the slave sees 0x3C.
6. **the milestone, `spi_duplex_msb` over the bus**: CONTROL 8, STATUS `halted=0` and the core stalled on PULL; TX write 0x96; the SPI slave on the pads (samples MOSI on SCLK's rise, drives MISO 0x53 while it is low, MSB first) sees 0x96 in one 8-clock CS frame; STATUS reaches `halted=1, rx_empty=0`; RX_DATA reads 0x53; `re` pops it and STATUS shows `rx_empty=1`; a second `re` changes nothing.
7. **loopback rehearsal**: pad 0 wired to pad 3 in the `Pads` helper, the wiring the board will have. Slots 7 and 8 each return the byte written, `spi_duplex_lsb` and `spi_duplex_msb` both, so the FPGA result has an RTL twin.

### Existing suites

`make test` still passes: `tests/` (model), `rtl_tests/test_core.py`, `test_fifo.py`, `test_top.py`, `test_top_adversarial.py`, with only the timing updates from the three program changes.

## Tapeout

- `tapeout/janestreet/src/tt_um_cshieldsce_smallcore.v` rewritten: instantiates `smallcore`, pins as in the interface table, `uio_oe = {4'b0000, gpio_oe}`. No folding, no parity tricks; every output reaches a pin honestly.
- `info.yaml` pinout becomes the real one, the word "provisional" goes. `source_files` adds `smallcore.v`, `host.v`, `rom.v`. `docs/info.md` describes the register map and how to test: select, push, read.
- `make sync` and `make check` cover the three new files.
- `test/` smoke test updated to the new wrapper: reset, CONTROL write, STATUS read.
- Harden and record the "+ program memory/interface" row in `docs/physical-results.md`, Milestones and Synthesis breakdown, with notes on what the ROM cost. The v1 row is already recorded, so `make harden` may wipe `runs/wokwi`. The ROM is expected to be the largest block; that number is a result of the experiment, not something to optimize first.

## FPGA smoke test, PYNQ-Z2

Directory `fpga/pynq_z2/`: `smallcore_pynq.v`, `pynq_z2.xdc`, `README.md`, and a cocotb test of the wrapper. Vivado and the board are the user's side; this repo supplies sources, constraints and steps.

- **Clock**: the board's 125 MHz into a 2-bit counter, the divided bit through a `BUFG`, SmallCore at 31.25 MHz. SCLK at 8 clocks per bit is about 3.9 MHz. Removes doubt about timing for a smoke test.
- **Buttons**, debounced by a counter whose length is a parameter (`DEBOUNCE`, small in simulation). The wrapper is the host: while a button is down it drives the bus for that button's transaction, and the host block's edge detect makes it one transaction.

| button | drives |
|---|---|
| BTN0 | `addr=3`, `wdata=8` (or 7 when SW0 is up), `we` |
| BTN1 | `addr=0`, `wdata=0x96`, `we` |
| BTN2 | `addr=1`, `re` |
| BTN3 | hard reset |

- **Idle bus**: no button down, `addr = 1` (RX_DATA), or `2` (STATUS) when SW1 is up. `we = re = 0`.
- **LEDs**: `host_rdata[3:0]` on LD0..3, `host_rdata[6:4]` on LD4's three channels, `host_rdata[7]` on one channel of LD5. Reading the RX head or STATUS byte at a glance.
- **Pads**: PMOD A pins 1..4 carry `gpio[3:0]` as tristates, `assign pmod[k] = gpio_oe[k] ? gpio_out[k] : 1'bz; assign gpio_in[k] = pmod[k];`. A jumper from pin 1 (MOSI, gpio 0) to pin 4 (MISO, gpio 3) is the loopback.
- **Expected**: press BTN3, BTN0, BTN1, then BTN2 pops and LD shows 0x96; SW1 up shows STATUS with `halted` set.
- **Simulation**: a cocotb test presses the buttons in that order against the wrapper with the loopback wired and reads 0x96 on the LED outputs, so the wrapper is verified before Vivado sees it.
- **README**: Vivado project steps, which sources, the XDC, generate bitstream, load, the button sequence and what the LEDs should show.

## Documentation

- `README.md`: the tree listing gains the new files and `fpga/`; a "Host interface" section with the pin table, register map and timing rules; the Status section records the milestone once the tests pass and the harden row is in; the Commands block adds `make rom`, `make rom-check`, the new pytest entries.
- `docs/physical-results.md`: the new row and notes.

## Milestones, in order

1. `core` and `top`: `halted` port, `restart` input, `drive_host` update. Existing suites green.
2. Programs: the three CONFIG words, tests updated and mutation-checked. Existing suites green.
3. `tools/gen_rom.py`, `programs/manifest.txt`, `rtl/rom.v`, `make rom`/`rom-check`, `test_rom.py`.
4. `host.v`, `smallcore.v`, `smallcore_tb.py` tests 1..5.
5. Tests 6 and 7: the milestone and the loopback rehearsal.
6. Tapeout wrapper, `info.yaml`, harden, physical results row.
7. `fpga/pynq_z2/` wrapper, XDC, cocotb test, README. User runs Vivado and the board.
8. README and status.

Each RTL step commits as `add <thing>` with its bench helper changes, its tests as `add <thing> RTL test(s)`, pushed to `origin main`.
