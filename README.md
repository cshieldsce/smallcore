# core

A mini PIO-style CPU simulator. 16-bit instructions with a per-instruction delay, four output pins `gpio[3:0]`, each push-pull or open-drain, four input pins `gpio_in[3:0]`, an 8-bit output shift register fed by a TX FIFO, an 8-bit input shift register drained into an RX FIFO, a wait on an input level, a skip on a bit of the input shift register, a counted repeat of a run of words, and two pieces of configuration, `shift_dir` and `open_drain`. Eleven mnemonics in eight opcodes. The encoding is in `isa.yaml`.

| instruction | does |
|---|---|
| `NOP [d]` | nothing |
| `SET pin, value [d]` | gpio[pin] <- value |
| `SHIFT_OUT [d]` | gpio[0] <- next bit of the output shift register, then shift |
| `SHIFT_IN pin [d]` | sample gpio_in[pin] into the input shift register, then shift |
| `PULL [d]` | output shift register <- next TX FIFO byte; stalls while the FIFO is empty |
| `PUSH [d]` | RX FIFO <- input shift register; stalls while the FIFO is full |
| `WAIT pin, level [d]` | stalls while gpio_in[pin] != level, a level not an edge |
| `SKIP bit, level [d]` | steps over the next word if in_shift_reg[bit] == level: pc <- pc + 2 |
| `JMP label [d]` | continue at label |
| `REPEAT count, label` | back to label until the words from label to here have run count times, 1..32; one cycle, no `[d]`: bits 12:8 hold the count |
| `CONFIG field, value [d]` | config[field] <- value: `shift_dir` 0 (reset) or 1, LSB or MSB first for both shift registers; `open_drain01` and `open_drain23`, a 2-bit mask for pins 1:0 or 3:2, 1 = open-drain |

`[d]` holds for d extra cycles. Every instruction but `JMP` and `REPEAT` can take a GPIO side effect, `pin, value` after its own operands, that drives one more pin on the same edge as the operation: `SHIFT_OUT 1, 0` puts the next bit on MOSI and drops the clock, `SHIFT_IN 3, 1, 1` raises the clock and samples MISO, `PULL 2, 0` drops CS the moment a byte arrives, `PUSH 2, 1` raises it as the received byte leaves, and a WAIT's side effect lands on the cycle the level arrives. `SET` is the side effect on its own. The FIFOs are fed and drained from outside the core: by the test bench, the CLI, or the host register bus of `rtl/smallcore.v`, the chip, which also holds every program in a ROM (see Host interface).

```
isa.yaml      instruction set: encoding, opcodes, operand ranges
programs/     assembly programs (.asm); manifest.txt gives each its permanent ROM slot
sim/          simulator and assembler (cpu.py)
tests/        pytest test benches
rtl/          Verilog-2001: core.v, fifo.v, top.v (the core with its TX and RX FIFOs), host.v (the register bus),
              rom.v (GENERATED from programs/ by make rom), smallcore.v (host + rom + top: the chip)
rtl_tests/    cocotb benches for rtl/ under Verilator, checked against sim/cpu.py; top_tb.py runs the protocols end to end,
              smallcore_tb.py runs them from the ROM through the host bus, pynq_tb.py the board wrapper
docs/         Mermaid diagrams (.mmd) and rendered .svg, see Docs below
tools/        gen_rom.py (programs/manifest.txt -> rtl/rom.v), wavetrace.py (waveform helper), render_docs.py (docs/*.mmd -> .svg)
tapeout/      janestreet/: Tiny Tapeout IHP CMOS5L packaging, 6x4 tiles; src/*.v are staged from rtl/ by make tapeout-sync
fpga/         pynq_z2/: the FPGA smoke test, buttons for a host, LEDs for read data, a PMOD jumper for the wire
build/        generated: test waveforms, caches (safe to delete)
```

## Host interface

`rtl/smallcore.v` is SmallCore packaged as a peripheral: `host.v`, a four-register bus, `rom.v`, every program in `programs/manifest.txt` at its slot, and `top.v`. A host selects a program by number, queues bytes, runs it, watches for completion and reads the result, with nothing outside the chip supplying instructions. The Tiny Tapeout wrapper maps the ports onto the 24 pins one for one:

| signal | dir | width | Tiny Tapeout pin |
|---|---|---|---|
| `host_wdata` | in | 8 | `ui[7:0]` |
| `host_rdata` | out | 8 | `uo[7:0]` |
| `host_addr`, `host_we`, `host_re` | in | 2, 1, 1 | `uio[5:4]`, `uio[6]`, `uio[7]` as inputs |
| `gpio[3:0]` | bidir | 4 | `uio[3:0]`: `gpio_out` drives when `gpio_oe`, `gpio_in` is the pad readback |

`host_rdata` continuously shows the register `host_addr` selects. A write happens on the rising edge of `host_we`, a pop on the rising edge of `host_re`, each decoded against `host_addr` at that moment:

| addr | write (`host_we` rises) | read (`host_rdata`) |
|---|---|---|
| 0 TX_DATA | push `host_wdata` into the TX FIFO; dropped if full, check STATUS first | 0 |
| 1 RX_DATA | – | RX FIFO head, 0 while empty; `host_re` rising here pops it, nothing if empty |
| 2 STATUS | – | `{5'b0, halted, tx_full, rx_empty}` |
| 3 CONTROL | `sel <= host_wdata[3:0]`, the core restarts at pc 0 in that slot; both FIFOs keep their bytes | `{4'b0, sel}` |

Rules: a strobe is held at least 4 clocks high and 3 low between strobes, and low for 3 clocks after reset before the first one; `host_wdata` and `host_addr` are set before it rises and held until it falls (the transaction decodes them from the pins two clocks after the strobe is first captured, so 4 high leaves a clock of margin whatever the strobe's phase). `RX_DATA` reads 0 while the RX FIFO is empty. Exactly one push, pop or select happens per rising edge, so a host on GPIO pins, an MCU or a button, works. Hard reset clears the core, both FIFOs and `sel`, and slot 0 is no program: a fresh chip sits halted with every pad driven high until the host selects. A CONTROL write while a program runs is an abort and restart, a defined thing: the core resets, its pads return to their reset levels, the FIFOs are untouched, even on the clock a PULL or PUSH was about to act, so a byte queued behind the one in flight goes out on the next run. `halted` says execution finished, not that the protocol succeeded; the RX FIFO says what happened (an I²C program halts after a NACK too, with the ACK bit pushed for the host to read).

| slot | program | slot | program | slot | program |
|---|---|---|---|---|---|
| 0 | none, halted | 4 | `uart_rx` | 8 | `spi_duplex_msb` |
| 1 | `uart_tx_0x55` | 5 | `spi_tx_lsb` | 9 | `i2c_write` |
| 2 | `uart_tx_pull` | 6 | `spi_tx_msb` | 10 | `i2c_write_stretch` |
| 3 | `uart_tx_loop` | 7 | `spi_duplex_lsb` | 11 | `i2c_write_addr_data` |

Slots are permanent: a new program takes an unused slot, 12..15 read as slot 0. `rom.v` is one lookup on `{sel, addr}`, so every program keeps its own addresses from 0 and `JMP` targets need no relocation; the whole 272-word library costs about as much as one FIFO. Because `gpio_in[k]` is the readback of pad `k` and every pad is push-pull high out of reset, a program that listens on a pin lets go of it first, the way the I²C programs always did: `uart_rx` opens with `CONFIG open_drain01, 1`, the SPI duplex programs with `CONFIG open_drain23, 2`.

## Status

**Peripheral v1**, tag `v1.1`, 2026-09-27: SmallCore is a usable programmable protocol peripheral, not only a core that can be made to run protocols under a bench. `rtl_tests/smallcore_tb.py` drives only the chip's ports: a host at the register bus selects slot 8, sees STATUS say running, writes 0x96, and reads 0x53 back, with a mode 0 slave on the pads the only thing outside the chip; the program came from `rom.v`, the byte went through `host.v` into the real TX FIFO, out of the pads as one 8-clock frame MSB first, and the slave's byte came back through the pad readback, SHIFT_IN, PUSH, the real RX FIFO and the bus. The same bench proves strobes are edges not levels, that a strobe held high through reset does nothing, that CONTROL restarts the core and keeps the FIFOs, and switches slots mid-frame so the queued byte goes out under the new program, and that a loopback jumper from pad 0 to pad 3 returns the byte written, the wiring of the board test. `rtl_tests/pynq_tb.py` presses the PYNQ-Z2 wrapper's buttons in simulation and reads 0x96 on its LEDs; `fpga/pynq_z2/README.md` has the Vivado steps for the board itself, not yet run. The Tiny Tapeout wrapper now has its real pinout, above. Hardened through the same flow at 6x4 tiles, zero DRC, antenna and LVS violations, `docs/physical-results.md` row "+ program memory/interface": 1,010 synth cells, 1,334 routed, 20,249 µm², 2.24% of the tile, setup slack +10.15 ns and hold +0.11 ns at 20 ns, worst corners. Against v1 the host block, the whole eleven-program ROM and the real pinout cost 343 routed cells; the ROM folds to a few hundred gates because its words repeat.

**Baseline v1**, tag `v1`, 2026-09-27: UART, SPI and I²C are verified end to end in RTL. Each program runs on `rtl/top.v`, the core with its TX and RX FIFOs, under Verilator, and the bench is the far end of the wire: it touches only top's host ports and pins, pushing bytes into the real TX FIFO, popping them from the real RX FIFO, and reading or driving `gpio_out`, `gpio_oe` and `gpio_in`.

| protocol | programs | the bench is | proves |
|---|---|---|---|
| UART | `uart_tx_pull.asm`, `uart_rx.asm` | a line sampled once per clock; an 8N1 frame driven in | a host byte leaves as a frame at 8 clocks per bit; a frame arrives as one host byte |
| SPI mode 0 | `spi_tx_lsb.asm`, `spi_tx_msb.asm`, `spi_duplex_lsb.asm`, `spi_duplex_msb.asm` | a slave that samples MOSI on SCLK's rise and drives MISO while it is low | CS frames exactly eight clocks; 0x96 leaves in either bit order under `CONFIG shift_dir`; 0x53 comes back through SHIFT_IN, PUSH and the RX FIFO in both orders |
| I²C master write | `i2c_write.asm`, `i2c_write_addr_data.asm`, `i2c_write_stretch.asm` | two open-drain lines with pull-ups, resolved every clock from `gpio_oe`, and a slave that ACKs or NACKs and can hold SCL | START, the byte, the ACK or NACK sampled and PUSHed to the host, STOP; the ACK steers SKIP, address then data on an ACK, STOP with the data byte still in the FIFO on a NACK; a slave stretching 8 clocks holds the master 5 clocks per clock, 50 in all, the model's numbers |

Behind that: `sim/cpu.py` is the golden model, with 2431 pytest tests in `tests/` including an adversarial sweep of every 16-bit word. `rtl_tests/core_tb.py` runs the core in lockstep with the model (18 tests), `fifo_tb.py` the FIFO (7), `top_tb.py` the protocols above (13), and `top_adversarial_tb.py` (21) is the adversarial sweep, every run in lockstep with the model and every byte in both FIFOs after every edge: each kind of stall held 37 clocks and released once, every delayed word acting once, LSB against MSB first for all 256 bytes, a stall against a delay, a SKIP right after the sample it reads, branches on their last edge, CONFIG next to a pin write, a pin driven, released, sampled and driven again on a pad model, an open-drain SDA with a slave on the pad, restarts and resets with bytes queued in both FIFOs, the FIFOs wrapping around and at their full and empty boundaries under a host that never reads STATUS, host traffic while the core is stalled, the last addresses of a 256-word program, the 45,312 words the ISA rejects, and 250 seeded programs of up to 64 words under random host pushes, pops, restarts, resets and pin levels. The SPI, I²C and adversarial tests were each shown to fail under a mutation of the program, the bench or the RTL before being kept.

The v1 RTL hardened through the Tiny Tapeout IHP CMOS5L flow at 6x4 tiles with zero DRC, antenna and LVS violations; `docs/physical-results.md` has the row, "+ FIFO storage", and its notes.

| synth cells | routed cells | cell area | utilization of 6x4 | setup slack | hold slack |
|---|---|---|---|---|---|
| 695 | 991 | 16,571 µm² | 1.84% | +10.86 ns | +0.14 ns |

Slacks are at the flow's 20 ns clock, worst corner. The two DEPTH 4 FIFOs are 60% of `top` and the biggest area lever; the wrapper's pin mapping is still provisional. Known gap, accepted for v1: the random lockstep compares each FIFO by count and head, not every queued byte, so a byte corrupted deeper in a FIFO would show only on reaching the head; `fifo_tb.py` covers ordering, wrap and full on its own.

## Commands

```
python -m pip install -r requirements.txt           # plus Verilator 5.036+ on the PATH for the RTL
python -m pytest -v                                 # writes build/waves/<test bench>/<test>.svg
python sim/cpu.py                                   # runs programs/uart_tx_0x55.asm: listing + one trace per pin
python sim/cpu.py programs/uart_tx_pull.asm 0xA3    # one byte from the TX FIFO
python sim/cpu.py programs/uart_tx_loop.asm 0x55 0xA3   # streams the FIFO, then stalls on PULL
python sim/cpu.py programs/spi_tx_lsb.asm 0xA3      # SPI mode 0: MOSI, SCLK, CS on gpio 0, 1, 2
python sim/cpu.py programs/spi_tx_msb.asm 0xA3      # same words except CONFIG shift_dir, 1
python sim/cpu.py programs/spi_duplex_msb.asm 0xA3  # also samples MISO on gpio_in 3 and PUSHes the byte (the CLI holds inputs at 0)
python -m pytest tests/test_uart_rx.py -v           # UART RX: uart_rx.asm fed by uart_tx_loop.asm over a wire, waves in build/waves/uart_rx/
python -m pytest tests/test_i2c.py -v               # I2C master write on a bus model with a slave: one byte, clock stretching, address + data
python sim/cpu.py programs/swd_write.asm 0xA9      # SWD write: request, turnaround, ACK, turnaround back, branch on the ACK, on OK four data bytes and a parity byte; SWDIO on gpio 0, SWCLK on gpio 1 (the CLI holds inputs at 0: no ACK, the program exits)
python sim/cpu.py programs/swd_read.asm 0x8D       # SWD read: on OK 32 data bits and the parity follow, six bytes to the host (the CLI holds inputs at 0: no ACK, the program exits)
python -m pytest tests/test_swd.py -v               # SWD: a target on the wire decodes every request the host can make, answers OK, WAIT or FAULT, sends a word
python sim/cpu.py programs/can_tx.asm 0x5A 0x30      # CAN stage 1: the SOF and identifier 0x5A3 as two host bytes, 8 cycles a bit on gpio 0, the bus (the CLI holds inputs at 0: the sampled byte reads 0)
python sim/cpu.py programs/can_tx_arb.asm 0x5A 0x30  # CAN stage 2: the same frame under arbitration, TXD on gpio 0 read back on gpio_in 0, the bus on gpio_in 1 (the CLI holds inputs at 0: TXD reads back dominant, nothing is ever lost, the frame goes out whole)
python sim/cpu.py programs/can_tx_ack.asm 0x5A 0x30  # CAN stage 3: the frame, then the ACK slot let go and sampled, the decision in the delimiter (the CLI holds inputs at 0: acked, one byte, the halt)
python sim/cpu.py programs/can_tx_stuff.asm 0x7F 0xF0 # CAN stage 4: 0x7FF stuffed, 16 cycles a bit, the decision tree needing seven after the sample (the CLI holds inputs at 0: every sample dominant, so a recessive stuff bit follows every bit from ID[7] on, 20 bits)
python -m pytest tests/test_can.py -v               # CAN: a wired-AND bus with an ideal receiver and a competing transmitter; the SOF and the identifier held 8 cycles a bit, the sample point probed with a one-cycle glitch, a host late mid-frame, arbitration won and lost on every recessive bit, the ACK slot pulled dominant by the receiver or not, the frame again after no ACK, stuff bits after every run of five and a receiver that drops them
python -m pytest tests/test_can_candidates.py -v    # the CAN candidates (experiments/can/) spliced into the arbitration and stuffing programs against the baselines, the bus cycle for cycle and bit for bit
python -m pytest tests/test_repeat.py -v            # REPEAT on the model: count 1..32, one- and 255-word bodies, stalls in the body, restart every cycle, the assembler's rules, every program with REPEAT against its canonical one
python -m pytest tests/test_repeat_candidates.py -v # the repeat candidates (experiments/repeat/) spliced into the SWD programs against the baseline, cycle for cycle
python experiments/repeat/suite.py                  # the existing model suite run on each candidate's model: what each one disturbs
python tools/render_docs.py                         # docs/*.mmd -> .svg (needs mermaid-cli)
make lint                                           # verilator --lint-only -Wall -Wno-fatal rtl/core.v
make test-rtl                                       # python -m pytest rtl_tests: Verilator builds core.v and top.v into build/rtl/, cocotb runs rtl_tests/*_tb.py
python -m pytest rtl_tests/test_smallcore.py -v     # the chip: host bus semantics, spi_duplex_msb from the ROM through the bus with a slave on the pads, the loopback
python -m pytest rtl_tests/test_rom.py -v           # rom.v word for word against the assembler
python -m pytest rtl_tests/test_pynq.py -v          # fpga/pynq_z2/ wrapper: buttons, debounce, LEDs, the PMOD jumper modelled in the bench
make rom                                            # programs/manifest.txt + the assembler -> rtl/rom.v; rom-check fails if it is stale (make test runs it)
python -m pytest rtl_tests/test_top_adversarial.py -v  # top.v under a hostile host: stalls held, delays one-shot, metamorphic pairs, seeded traffic in lockstep with the model
WAVES=1 make test-rtl                               # same, plus build/rtl/dump.vcd (gtkwave build/rtl/dump.vcd)
make test                                           # tests/ then rtl_tests/
```

## Design pressures

What the protocols have asked of the core, in order. Open items stay open until a program needs them.

| pressure | from | status |
|---|---|---|
| more than one output pin | SPI | `gpio[3:0]`, `SET pin, value` |
| shift and drive a second pin on one edge | SPI | the side effect: 2 instructions, 8 cycles per bit |
| MSB first | SPI | `shift_dir`, `CONFIG shift_dir, 1` |
| sample a pin on the edge that raises the clock | SPI duplex | `gpio_in[3:0]`, `SHIFT_IN pin, out_pin, value`; RX costs no instructions or cycles |
| get the received byte out | SPI duplex | `PUSH` into an RX FIFO; `PUSH 2, 1` also ends the frame |
| six of eight opcodes used | the ISA | one `SHIFT` opcode with an in bit, one `FIFO` opcode with a push bit, generic `CONFIG`, the side effect on every opcode, `SET` = `NOP` + side effect |
| wait for an input level: the start bit | UART RX | `WAIT pin, level`: the stall PULL and PUSH already had, with a pin level as its third condition; `uart_rx.asm` is 11 words, `WAIT 0, 0 [11]` then eight mid-bit `SHIFT_IN`s |
| let go of a line: a third output state | I2C | `open_drain[3:0]`, one mode bit per pin: `gpio_oe[k] = !(open_drain[k] & gpio[k])`, an open-drain pin drives its 0 and lets go on a 1; the same words see the ACK and follow the stretch. `CONFIG open_drain01, 3` sets both I2C pins in one word: two 2-bit fields cover the four pins with CONFIG's shape unchanged, field 3 stays free |
| wait for the clock to really rise | I2C clock stretching | `SET 1, 1` then `WAIT 1, 1 [2]`: the WAIT as built, one more word per clock |
| act on the ACK: STOP after a NACK | I2C address + data | `SKIP bit, level`, pc + 2 when a bit of the input shift register holds the level: `SKIP 0, 0` then `JMP stop` after the ACK clock, from the register since SDA has let go by then. A conditional JMP on the last sample was one word shorter and could not pick the bit, the polarity or the word it guards; JMP keeps its 8-bit target |
| compact repetition / bit count | SPI, 16 words per byte; I2C, 3 per bit; SWD, 89 of 103 and 90 of 106 words repeat an earlier word | `REPEAT count, label`, opcode 111, the last one: a counted backward branch, count - 1 in the delay bits, the distance back in the operand byte, a 5-bit counter that moves on the REPEAT's cycle only, so stalls and delays inside the body leave it alone. How it was chosen is the method on record: no loop word for four protocols, because their bit cells could be unrolled; SWD made the repetition measurable rather than assumed; four ways to say "again" compared on the model against the real programs, `docs/repeat-candidates.md` (A 40/40, C 43/43, D 33/36 words, B nothing); the smallest general one taken; then run backwards over every earlier protocol and found to serve each without moving a cycle, the ROM's 275 words to 111. In `isa.yaml`, the model and `core.v`: a 5-bit register, a decrement, a zero test and the subtract, nothing else in the core touched; the corners pinned on the model (`tests/test_repeat.py`) and RTL against model on the same corners, stalls inside random bodies included (`rtl_tests/core_tb.py`), the 40-word SWD programs clock for clock the 103- and 106-word ones at the pins (`rtl_tests/top_tb.py`). The 103- and 106-word programs stay as the record of why |
| per-pin idle level | SPI, one `SET` for SCLK | open, not hurting yet |
| configurable shift-output pin | SPI | open, fixed `gpio[0]` has not failed |
| listen on a pad that is push-pull high at reset | the chip: `gpio_in` is the pad readback | one `CONFIG` word releases the pin, `uart_rx`, `spi_duplex_*`; the I²C programs already did |
| clock a request out, the target sampling on the rise | SWD stage 1, the request alone | nothing new: the first 18 words of `swd_write.asm` and `swd_read.asm` are `spi_tx_lsb.asm`'s two words per bit without CS, LSB first as the core resets |
| let go of the line for one clock: the turnaround | SWD stage 2 | nothing new: `CONFIG open_drain01, 1` with the park bit's 1 on the pin, the word's side effect dropping SWCLK, so the release is one word on the beat, as I²C's ACK clock was |
| take a 3-bit field from the target and hand it to the host | SWD stage 3, the ACK | nothing new: three `SHIFT_IN 0, 1, 1` and a `PUSH`, I²C's ACK clock three times. Observed, not hurting: three LSB-first samples sit in bits 7:5 of the byte, the host reads OK as 0x20, WAIT 0x40, FAULT 0x80 |
| branch three ways on a 3-bit field | SWD stage 4, OK / WAIT / FAULT | works, on record: SKIP sees one bit, so the decision is `SKIP 5, 0`, `JMP data`, `SKIP 6, 0`, `JMP request`, `JMP done`, five words. Two things the core cannot do, found here and left open: resend the request on WAIT (SHIFT_OUT empties `shift_reg`, only PULL reloads it, so the retry is a JMP to the PULL and the host pushes the request again) and tell a read from a write (the RnW bit went out on the wire; SKIP sees only sampled input), so read and write are two programs |
| take 32 data bits and a parity bit from the target | SWD stage 5, the read, `swd_read.asm` | works, 103 words: two per bit and a `PUSH` in place of every eighth clock drop, the repetition pressure at its widest. On record: a read is six bytes (ACK, four data, parity as bit 7 of a fifth over data[31:25]) through a 4-deep RX FIFO, so the host pops mid-transaction or the fifth PUSH stalls with SWCLK stopped (SWD allows it); the core has no XOR, so parity is the host's to check; the branch must come before the turnaround back, because on OK the target keeps the line |
| send 32 data bits and a parity bit the host computed | SWD stage 6, the write, `swd_write.asm` | works, 106 words: a PULL per data byte in the last high cycle of the clock before, so a prompt host costs no cycles; the parity is bit 0 of a fifth byte, the host's to compute. On record: the host must not queue the data behind the request, because on a WAIT the retry PULLs the next byte as the request and nothing but PULL can discard a queued byte, so a host writes the request, reads the ACK, then queues the data; request, data and parity are six bytes through a 4-deep TX FIFO |
| stop the clock mid-transaction: a host that does not read | SWD, the sleeping host | nothing new, the stall as built, on a real protocol: the fifth `PUSH` finds the RX FIFO full after data bit 31 and the core stands still for as long as the host sleeps, SWCLK high without a glitch, the pad off SWDIO with the target holding bit 31, pc on the PUSH, `in_shift_reg` and the FIFO unchanged; one pop and it moves exactly once, one rise (the parity's) to the sixth PUSH's stall; the six bytes arrive whole. At the pins on `top.v` (`imem_addr` is the pc, the FIFO's full flag) and in the model |
| the host pushes the request again on WAIT: must it hurry? | SWD, the slow host | no. The retry's `PULL` stalls with SWCLK low and SWDIO high and the host's; the target sees no edge to count; once the byte lands the run is the prompt host's cycle for cycle, whether the host is 1 or 1000 cycles late (13 clocks in hand on `top.v`). SWD moves on SWCLK alone and has no timeout on a stopped clock. On record as an API inconvenience, not a timing burden |
| drive a bit for a fixed time and sample it at a fixed point, no clock line | CAN stage 1, the SOF + 11-bit identifier, `can_tx.asm` | nothing new: `SHIFT_OUT [5]`, `SHIFT_IN 0`, `REPEAT` is an 8-cycle bit driven on its first cycle and sampled on its seventh, the level the bus held through its sixth (75%), `uart_tx`'s cell with a sample in it; dominant is a driven 0 and recessive a let-go 1, `CONFIG open_drain01, 1` as for I²C's SDA, the bus is the pad readback; 13 words for 12 bits, 100 cycles, the receiver on the bus reads every identifier back. Observed, not hurting: the second byte's PULL needs the cycle the REPEAT has, so the first byte's last cell is unrolled (three words); the register zero-fills, and a 0 is dominant, so the host writes the SOF as bit 7 of the first byte and the program lets go after ID[0] rather than run the register out |
| a host that is late in the middle of a frame | CAN stage 1, the second byte | on record, not fixed: the PULL for {ID[3:0], 0000} issues in ID[4]'s eighth cycle, and a host `n` cycles late stretches ID[4] by exactly `n`, every later bit late by as much. The transmitter's own samples move with its bits, so the byte it hands the host is right; a receiver counting from the SOF reads the frame right up to 5 cycles late and wrong from 6. CAN has no clock line to stop: the stall that let SWD's host sleep is a timing fault here, so the host queues both bytes before the frame, which a 4-deep FIFO has room for |
| know what was sent while seeing what came back: arbitration | CAN stage 2, a second transmitter on the bus, `can_tx_arb.asm` | **the first thing the core cannot do**, on record. A node that sent recessive and sees dominant has lost and must send nothing more. With the pad on the bus, `gpio_in 0` the bus as I²C and SWD had it, no program can tell that bit from its own dominant one: the sent bit sits on the pin register, which nothing reads, `shift_reg` has zero-filled, SKIP and WAIT see inputs only. `can_tx.asm` against a competitor (`tests/test_can.py`): it wins when its identifier is lower, free, because the competitor withdraws; when it should lose it drives on, the bus is the AND of both frames until the competitor withdraws too, and the receiver reads an identifier nobody sent. The workaround that works is the transceiver's view: TXD on pin 0 push-pull, its own pad readback on `gpio_in 0` as the bit sent, RXD on `gpio_in 1`; then two `SHIFT_IN`s a bit and the pair decides, `SKIP 1, 1`, `JMP next [1]`, `SKIP 0, 0`, `JMP next`, `JMP lost`, three cycles on every path. Costs, measured: a JMP out of a body is what REPEAT forbids, so the eleven identifier cells unroll, 95 words and 34 distinct for 12 bits against 13 and 8; the decision's three cycles move the sample point from the sixth clock of the bit to the fourth at 8 cycles a bit, or the bit grows; a loss before ID[4]'s PULL strands the second byte in the TX FIFO, and only a PULL drops it (SWD's finding again), one more exit; the host reads one byte, the last four (sent, seen) pairs, a loss as (1, 0) last, and cannot tell from it which bit was lost. The sent bit, the compare and the exit from a loop are the candidates' problem, the reviewer's to weigh; nothing in the core is touched |
| a FIFO stall inside a frame | CAN, the first protocol where a stall is not protocol-safe | on record, since stage 1: SWD's host could sleep because SWCLK stopped with it; a CAN bit has a length the network keeps, so a PULL or PUSH that waits inside a frame stretches the bit under it and every receiver's sample after it lands wrong (stage 1's late host: 5 cycles of margin at 8 a bit, then the frame is lost). Between frames a stall is safe: stage 3's retry PULL waits on an idle bus for as long as the host takes. Not an ISA question yet: it will press on the host's choreography or the FIFO depth once frames carry 8 data bytes and a receiver has to buffer, so the number to watch is the cycles in hand at every PULL and PUSH |
| release the bus for one bit, sample it, decide | CAN stage 3, the ACK slot, `can_tx_ack.asm` | nothing new, as expected: `SET 0, 1 [5]` lets go for the slot and `SHIFT_IN 0 [1]` samples it as every bit is sampled, the receiver's dominant lands in the byte the host reads; the decision is one `SKIP 0, 1` in the delimiter, because the bit sent in the slot is the program's constant, not shift_reg's: what arbitration lacked, the ACK has for free. 21 words for stage 1's 13. Not acked: the byte says so, EOF and the intermission are `NOP [6]` and `REPEAT 10`, and the frame goes again from two more host bytes, since nothing but PULL loads shift_reg (SWD's WAIT retry again); the host has 87 cycles to queue them before the PULL stalls, safely, on the idle bus. Error signalling, the frame CAN really sends there, is a later stage |
| remember the run: after five bits of one level, send one of the other | CAN stage 4, dynamic bit stuffing, `can_tx_stuff.asm` | works, ugly, on record, the second complaint. No counter is needed: the bus is sampled every bit and the last five samples sit in `in_shift_reg` bits 4:0, the run itself. The decision is the cost: a tree of single-bit SKIPs, the newest sample picks a side, four SKIPs ask whether the four before it match, a JMP out at the first that does not, the stuff bit at the end of the fall-through, `SET 0, level [7]` for a full bit that takes nothing from `shift_reg` and is sampled so the next window counts it. Seven cycles on the longest path after the sample, and a two-way branch whose two continuations must both land on the next bit edge costs a cycle more on the JMP side than on the fall-through, so every exit carries a delay. At 8 cycles a bit the tree is one cycle too long even sampling on the bit's first clock, so a bit is 16 here, sampled on its eighth (50%): the bit rate halves. ID[7] to ID[0] are written out, 27 words each: 224 words, 71 distinct, for 12 bits, against 13 for stage 1 (a mistake found in the candidate round: every exit can land on the REPEAT that ends the body, which the assembler allows, so the same cell is a body and the same frame is 91 words on today's ISA, `experiments/can/can_tx_stuff_loop.asm`; the 224 stay as written, the bit time and the seven-cycle tree do not change); 196 cycles for an identifier with no run, 228 with two stuff bits; the host's byte holds stuff bits among the samples. What arbitration and stuffing share: a decision on the last samples that has to leave a loop body and land on the very next bit edge; what stuffing adds: the decision is over five bits, not two |

SWD by the numbers: one transaction the target says OK to, a host at the FIFOs every cycle (`tests/test_swd.py::test_swd_by_the_numbers`, the cycle counts also on `top.v`). The repeats are the number to watch: the core cannot count, so 32 data bits are 64 words in each program.

| | read, `swd_read.asm` | write, `swd_write.asm` |
|---|---|---|
| program words | 103 | 106 |
| distinct words | 14 | 16 |
| words that repeat an earlier word | 89 | 90 |
| the 32 data bits | 64 words, two per bit | 64 words, two per bit |
| host interactions | 1 push, 6 pops | 6 pushes, 1 pop |
| RX FIFO fill, most | 1; 4 and a stall when the host does not read | 1 |
| TX FIFO fill, most | 1 | 4, the host holding the parity byte for the first data PULL |
| cycles, release to halt | 379 | 384 |

CAN by the numbers: one frame's SOF and identifier on the bus, a host at the FIFOs every cycle (`tests/test_can.py`'s numbers tests, the cycle counts also on `top.v`). Stages 1 and 2 are the baselines and stay as written; 3 and 4 are stage 1's frame with one more piece each. The inventory for the architecture review, before CRC: two complaints, arbitration and stuffing, and what they share.

| | 1 the frame, `can_tx.asm` | 2 arbitration, `can_tx_arb.asm` | 3 the ACK slot, `can_tx_ack.asm` | 4 stuffing, `can_tx_stuff.asm` |
|---|---|---|---|---|
| program words / distinct | 13 / 8 | 95 / 34 | 21 / 16 | 224 / 71 |
| cycles a bit / the sample on its | 8 / 6th (75%) | 8 / 4th (50%) | 8 / 6th | 16 / 8th (50%) |
| words per identifier bit | 3, a REPEAT body | 8, written out | 3, a REPEAT body | 27, written out |
| decision, cycles after the sample | none | 3, on every path | 1, one SKIP | 7 on the longest path, every exit padded |
| what the decision reads | – | the sent bit and the seen bit: two samples, the pad's own readback for the first | the seen bit alone: the sent bit is the program's constant | the last five samples: bits 4:0 of `in_shift_reg` |
| REPEAT | yes | no: the lost exit leaves the body | yes | yes, missed at the time: the exits can land on the REPEAT, 91 words that way (`experiments/can/can_tx_stuff_loop.asm`) |
| cycles, release to halt | 100 | 100 won; 8 (k + 1) + 4 lost on bit k, 5 before ID[4] | 115 acked; 194 + the host's lateness to the second SOF | 196; 228 with two stuff bits |
| host interactions | 2 pushes, 1 pop | 2 pushes, 1 pop | 2 pushes, 1 pop; 2 more pushes per retry | 2 pushes, 1 pop |
| cycles in hand at the mid-frame PULL | 0: a late host stretches ID[4] | 0 | 0; 87 at the retry's PULL, between frames | 0 |
| what the core lacks, if anything | nothing | the bit it sent, once SHIFT_OUT has put it on the pin | nothing | a run count, or a cheaper five-bit compare; a branch that lands on the next edge from either side |

What the two complaints share: a decision on the last few samples that must land on the very next bit edge, where a two-way branch is a SKIP and a JMP, one cycle longer on the taken side than the fall-through, so every exit carries a delay. What they do not share: arbitration wants a bit the core once had and let go of, and its lost exit leaves any loop, so REPEAT is out there; stuffing wants a count over bits it still has, and its exits can land on the REPEAT, so it was never out (the 224-word baseline missed that: 91 words the other way). Neither is fixed here; the candidates are compared on these programs the way REPEAT's were, `docs/can-candidates.md`.

Three kinds of state: instruction (`pc`, the delay counter), stream (the shift registers and FIFOs) and configuration (`shift_dir`, `open_drain`), each a `CONFIG` field. A shift pin or input pin would join the third kind as the last field.

## Docs

From the big picture down to what the Verilog will look like:

| diagram | shows |
|---|---|
| `docs/overview.svg` | program and bytes in, UART or SPI out, how a byte reaches the pins |
| `docs/isa_encoding.svg` | the 16-bit word: opcode / delay / side effect / own operands per instruction |
| `docs/isa_execute.svg` | what each instruction does, cycles, the PULL, PUSH and WAIT stalls |
| `docs/core.svg` | datapath at register level, named as in the Verilog |
| `docs/control.svg` | the control block: inputs, equations, counter, enables |
| `docs/states.svg` | the same block as per-cycle states: Issue, Hold, Stall, Halt |
| `docs/physical-results.md` | cells, area, utilization and timing per RTL milestone from the Tiny Tapeout CMOS5L flow in `tapeout/janestreet/` |
| `docs/repeat-candidates.md` | the repeat comparison that chose REPEAT: four candidate words for "again" against the SWD programs, on the model only; words, encoding, state, timing, stalls, restart, what each disturbs; the spec; the outcome |
| `docs/can-candidates.md` | the CAN comparison: a one-cycle branch, the sent bit exposed, a run test and a run counter, and their combinations, spliced into the arbitration and stuffing programs on the model only; words, cycles a bit, sample point, pins, REPEAT, state, encoding, what each disturbs; stuffing back from 16 cycles a bit to 8; no outcome yet |

Diagrams show only hardware that exists in `sim/cpu.py` and passes the tests.
