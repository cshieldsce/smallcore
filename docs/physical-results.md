# Physical results

Measured numbers from the Tiny Tapeout IHP CMOS5L flow in `asic/janestreet/`, one row per RTL milestone. Architectural tradeoffs get decided against this table, not by estimate.

## Milestones

| Milestone | Synth cells | Routed cells | Cell area | Util. | Setup slack | Hold slack | Date |
|---|---|---|---|---|---|---|---|
| RTL-0 control (pc, delay counter, decode, stall) | 161 | 209 | 2642 µm² | 0.29% | +12.2 ns | +0.12 ns | 2026-09-25 |
| + SET/GPIO | – | | | | | | |
| + CONFIG | – | | | | | | |
| + SHIFT | – | | | | | | |
| + WAIT/JMP/SKIP | – | | | | | | |
| + FIFO interface | – | | | | | | |
| + FIFO storage (top: core + TX/RX FIFOs, DEPTH 4), Baseline v1 | 695 | 991 | 16,571 µm² | 1.84% | +10.86 ns | +0.14 ns | 2026-09-26 |
| + program memory/interface (`smallcore`: host + ROM + top, real pinout), Peripheral v1 | 1,010 | 1,334 | 20,249 µm² | 2.24% | +10.15 ns | +0.11 ns | 2026-09-27 |
| + REPEAT, run test, accumulator; ROM slots 12..15, Protocol Engine v2 | 1,894 | 2,403 | 31,759 µm² | 3.52% | +7.20 ns | +0.11 ns | 2026-09-28 |
| final | | | | | | | |

Columns, all from `runs/wokwi/final/metrics.csv` unless noted:

- Synth cells: LibreLane's Yosys report, `*-yosys-synthesis/reports/stat.rpt`, wrapper plus core, including tie cells.
- Routed cells: `design__instance__count__stdcell` after routing; adds clock-tree, hold and timing-repair buffers. Excludes fill and tap cells.
- Cell area: `design__instance__area__stdcell`, µm² of standard cells.
- Util.: `design__instance__utilization`, cell area over the 6x4 core area of 902,417 µm² (die 1289.28 µm x 710.64 µm).
- Setup and hold slack: `timing__setup__ws` and `timing__hold__ws` at the template's 20 ns clock, post-route parasitics. These are the worst over the three nom corners, which in practice means setup at slow (1.08 V, 125 °C) and hold at fast (1.32 V, −40 °C). The per-corner values are `timing__*__ws__corner:nom_*`; the notes give typ where it matters.

Every hardened row so far also had zero routing DRC errors, zero Magic DRC errors, zero antenna violations and zero LVS errors; a row that does not will say so.

## Synthesis breakdown

Where the cells go, one row per milestone, appended as they land. Yosys + abc against the typ lib, no place and route, so a row takes seconds; the flow column is the Milestones table's synth cells.

| Milestone | Core cells | Core area | Core flops | FIFO cells | FIFO area | FIFO flops | Top cells | Top area | Flow synth cells | Flow synth area | Commit | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RTL-0 control | 98 | 1,517 µm² | 14 | – | – | – | 98 | 1,517 µm² | 161 | – | – | 2026-09-25 |
| + FIFO storage (2 × DEPTH 4) | 310 | 4,380 µm² | 39 | 257 | 6,630 µm² | 82 | 567 | 11,010 µm² | 695 | 11,948 µm² | `f795664` | 2026-09-26 |
| + program memory/interface (`smallcore`: host + ROM + top) | 312 | 4,420 µm² | 39 | 236 | 6,608 µm² | 82 | 548 | 11,028 µm² | 1,010 | 15,372 µm² | `132fe20` | 2026-09-27 |
| + REPEAT, run test, accumulator; ROM slots 12..15 (Protocol Engine v2) | 719 | 9,772 µm² | 76 | 246 | 6,530 µm² | 82 | 965 | 16,302 µm² | 1,894 | 25,268 µm² | `85d9380` | 2026-09-28 |

- Core: `make synth`, `core` alone.
- FIFO: `top` minus `core`, both FIFOs together. Derived, since the two are flattened into one netlist.
- Top: `top` alone, core plus FIFOs, no wrapper. At RTL-0 there was no `top`, so it is the core.
- Flow synth: LibreLane's `*-yosys-synthesis/reports/stat.rpt`, wrapper included, so it adds tie cells and the wrapper's pin logic.
- Flops: `sg13cmos5l_dfrbpq_1` count in the mapped netlist.
- The program memory/interface row's Top is still `top` alone; `smallcore` (host + ROM + top) under the quick script is 843 cells, 14,141 µm², 138 flops, so the host block and the whole ROM together are 295 cells, 3,113 µm² and 17 flops. `make synth-breakdown` prints `smallcore` as a fourth line.

To add a row: from `asic/janestreet/`, run `make synth-breakdown`. It prints cells, area and flops for `core`, `top` and the wrapper; subtract core from top for the FIFO columns. Take the flow columns from the harden, and put anything surprising in that milestone's notes section.

## RTL-0 notes

- Core alone under Yosys (`make synth`, no wrapper): 98 cells, 1517 µm², 14 flops. The flops are `pc[8:0]` and `delay_counter[4:0]`. `gpio_out` folds to constant 1111 because nothing drives it after reset yet.
- 30 of the 161 synth cells are tie-high/tie-low from the wrapper's constant outputs and the constant `gpio_out`; 27 routed cells are hold-fix delay gates on the input paths. Both are wrapper and pin artefacts, not core logic.
- Timing: the worst path is under 8 ns, so the flow's 50 MHz constraint is not close to binding. The clock target is not decided.
- Budget: Jane Street's guidance is about 1K logic cells per tile, roughly 24K for 6x4, with room left for clock tree and routing.
- Verilator lint in the flow: 11 `UNUSEDSIGNAL` warnings in `core.v`, all decode wires for instructions not yet built. No errors.
- The wrapper's pin mapping is provisional and shares pins between core inputs; see `asic/janestreet/src/tt_um_cshieldsce_smallcore.v`. Rows are comparable to each other as long as the wrapper stays the same; when the real pin mapping lands, note it in that row.

## FIFO storage notes

Commit `f795664`: `rtl/top.v` with the complete ISA core, a TX FIFO and an RX FIFO, both DEPTH 4, end-to-end UART TX and RX passing in `tests/rtl/top_tb.py`. The rows from SET/GPIO to FIFO interface were not hardened on their own; this row is the first measurement after RTL-0 and covers all of them.

- This RTL is Baseline v1. Tag `v1` (2026-09-27) has `rtl/` byte for byte as at `f795664`; what landed between is tests and docs: SPI and I2C end to end in `tests/rtl/top_tb.py` and the `top_adversarial_tb.py` suite. So this row is the v1 numbers, and the README's Status section quotes it.

- Wrapper change: `src/tt_um_cshieldsce_smallcore.v` now instantiates `top` instead of `core`, and `make sync` stages `top.v`, `core.v` and `fifo.v`. The old wrapper predated the FIFO ports: it left the core's `tx_data` undriven and `gpio_oe`, `rx_data`, `pull_en`, `push_en` unconnected, so synthesis would have pruned logic and under-reported the core. The new wrapper folds `tx_full`, `rx_empty` and the parity of each `rx_data` nibble into `uio_out[7:4]` with `gpio_oe`, so every output reaches a port. Still provisional pins; not comparable one-for-one with RTL-0's wrapper.
- Synth cells 695 (11,948 µm² synth area) from LibreLane's `06-yosys-synthesis/reports/stat.rpt`. 125 of them are tie-high: every flop maps to `dfrbpq_1` with its async `RESET_B` tied off, since reset is synchronous, so each of the 121 flops gets a tie, plus 4 for the constant `uio_oe` bits.
- Per-block numbers are in the Synthesis breakdown table. Wrapper + `top` under the quick script is 585 cells and 11,091 µm²; the flow's 695 is higher mostly from its tie cells.
- Core flops, 39, match its registers exactly: pc 9, delay_counter 5, gpio_out 4, shift_dir 1, open_drain 4, shift_reg 8, in_shift_reg 8. RTL-0's core was 98 cells and 1,517 µm², so the ISA added about 212 cells and 2,860 µm².
- The two FIFOs cost about 257 cells and 6,630 µm², 60% of `top`. They have 82 flops: 64 storage, 4 + 4 pointers, 3 + 3 count, and 4 more that appear to be duplicate read-pointer registers from Yosys's memory mapping (2-bit registers driving the read-mux selects). 49 µm² × 82 ≈ 4,020 µm² is flops, the rest is write enables and the read mux. FIFO depth is the biggest area lever so far.
- Verilator lint in the flow: 0 warnings (RTL-0 had 11 `UNUSEDSIGNAL`).
- Routed: 991 cells, 16,571 µm², 1.84% of the 6x4 core. Zero routing DRC, Magic DRC, antenna, LVS, setup or hold violations, and no slew or cap violations at any corner.
- Routed minus synth is 296 cells. 186 of them are `dlygate4sd3_1` hold-fix delays, the same input-path artefact as RTL-0's 27, now much larger because more input pins fan into flops (the FIFO data and push/pop). The rest are buffers from resizing and the clock tree; the ~121 flops plus FIFO fan-out give CTS more to do. The hold fixes will change when the real pin mapping lands.
- Timing per corner: setup +10.86 ns slow, +12.67 typ, +13.74 fast; hold +0.14 fast, +0.35 typ, +0.70 slow. At RTL-0 slow setup was +12.21, so the full ISA and FIFOs made the worst path about 1.35 ns longer, to about 9.1 ns at the slow corner. 50 MHz still has plenty of margin.
- Budget: 695 synth cells is under 3% of the ~24K guidance for 6x4.
- An earlier harden of the core alone, through the old wrapper, finished at 22:54 but was never recorded, and its `runs/wokwi/` was deleted by this run. It would not have been a valid FIFO-interface row anyway, for the pruning reason above.

## Program memory/interface notes

Commit `132fe20`: `rtl/smallcore.v`, the chip: `host.v` (a four-register bus, strobes synchronized and edge-detected, a program select that restarts the core), `rom.v` (all eleven programs, 272 words, generated from `programs/manifest.txt`, looked up by `{sel, addr}`) and `top.v` with a core-only `restart` and `halted` out. The Tiny Tapeout wrapper has its real pinout: `ui` write data, `uo` read data, `uio[7:4]` address and strobes as inputs, `uio[3:0]` the four protocol pads, bidirectional. This is Peripheral v1, tag `v1.1`.

- Quick synth, `make synth-breakdown`: `core` 312 cells, `top` 548, `smallcore` 843, wrapper 886. The host block and the ROM together are 295 cells and 3,113 µm², about what one DEPTH 4 FIFO costs. Yosys folds the 272-word case statement hard: most SPI and I²C words repeat, and each word is a 16-bit constant, so the ROM is a few hundred gates, not 4,352 bits of storage. Doubling the library would not double this.
- Flops: 138 in `smallcore`, 121 in `top` plus 17: 3 + 3 strobe synchronizers, 4 `sel`, and 7 named `program_words` that Yosys keeps beside `sel` for the `words` lookup (the lookup depends on `sel` alone, and `words` never exceeds 64, so 7 bits). `top` itself is 548 cells against 567 at v1 with two more ports; abc variance, the core is 312 against 310.
- The wrapper adds 43 cells over `smallcore`: the pin mapping is direct, no folding, so the rest is tie cells for `uio_oe[7:4]`, `uio_out[7:4]` and the reset inversion.
- Flow synth: 1,010 cells, 15,372 µm², from `06-yosys-synthesis/reports/stat.rpt`; 138 of them tie-high, one per flop as before, plus 8 tie-low for `uio_out[7:4]` and `uio_oe[7:4]`. v1 was 695, so the flow saw +315 cells for the host block, the ROM and the pin change.
- Routed: 1,334 cells, 20,249 µm², 2.24% of the 6x4 core, +343 cells and +3,678 µm² over v1. Zero routing DRC, Magic DRC, antenna and LVS errors, no slew or cap violations, no setup or hold violations at any corner.
- Routed minus synth is 324: 192 `dlygate4sd3_1` hold fixes (v1 had 186; the pin mapping changed but the input fan-in is similar, 8 write-data pins into the FIFO and now 4 control pins into the synchronizers), 73 `buf_1` and the rest from resizing and the clock tree over 138 flops.
- Timing per corner: setup +10.15 ns slow, +10.74 typ, +11.09 fast; hold +0.11 fast, +0.31 typ, +0.64 slow. The worst path at the slow corner is about 9.85 ns, 0.7 ns longer than v1: the ROM lookup sits in the instruction fetch path, `sel` and `pc` through the case statement into decode, and that is now the critical path. 50 MHz still has half the period spare.
- Budget: 1,010 synth cells is about 4% of the ~24K guidance for 6x4. The program library is not what fills the tile.
- This run is the first with the real pinout, so hold-fix and pin counts from here on compare with this row, not with v1's provisional wrapper.
- After this harden, review fixes added two AND gates in `top.v` (the FIFO pop and push are held off on a restart's clock) and eight in `host.v` (RX_DATA reads 0 while empty). Not re-hardened by hand; the CI run for that push has the numbers, a handful of cells over this row.

## Protocol Engine v2 notes

Commit `85d9380`: the core with REPEAT (`cd91c7c`), the run test, SKIP_RUN and SKIP_NORUN (`f4c205f`), and the accumulator, a second stream register with optional LFSR feedback (`543f55d`); and the ROM's last four slots taken so the chip carries programs that use them: 12 the SWD read in REPEAT form, 13 CAN stage 6A (the whole data frame, stuffing by the run test, the CRC in the accumulator, 8 clocks a bit), 14 the CAN receiver with the CRC in the core, 15 the destuffing receiver on the accumulator. Every instruction the ISA has is in the ROM but SKIP_RUN, which no program uses (`tests/model/test_rom_slots.py`).

- **A fixed ROM is everything the chip can fetch, and synthesis keeps only what those words reach.** Measured: CI run 36466255523 (`35ea2da`, REPEAT and the run test in `core.v`, the ROM still slots 1..11, none of whose words is a REPEAT or a run test) synthesized to 1,009 cells, 15,509 µm², and routed to 1,340 cells, 20,454 µm², against Peripheral v1's 1,010 and 1,334. The 145 cells the two features cost the core alone were pruned out of the chip. That run is a valid chip, but it does not measure the architecture; this row does, as far as the ROM's programs reach.
- Core alone, `make synth` on `core.v` at each architectural commit, the instruction word an input so nothing is pruned:

  | core.v at | cells | area | flops |
  |---|---|---|---|
  | v1.1, `5b21506` | 312 | 4,420 µm² | 39 |
  | + REPEAT, `cd91c7c` | 434 | 5,815 µm² | 44 |
  | + SKIP_RUN, `f4c205f` | 457 | 6,150 µm² | 44 |
  | + accumulator, `543f55d` | 719 | 9,772 µm² | 76 |

  REPEAT is 122 cells and 1,395 µm²: rc's five flops, its decrement and zero test, and a 9-bit subtract into the pc. The run test is 23 cells and 335 µm²: a turn of the register, a mask and a compare, no state. The accumulator is 262 cells and 3,622 µm²: 32 flops, acc and poly, about 1,570 µm² of it, and the rest the acc input mux over five sources, the sixteen XORs, poly's load and the push mux onto the RX FIFO's port. The 37 new flops are exactly rc, acc and poly.
- `top` 965 cells, 16,302 µm², 158 flops: the FIFOs are 246 cells as before. `smallcore` 1,709 cells, 24,185 µm², 176 flops; the wrapper 1,724 cells. The host block and the ROM are now 744 cells, 7,883 µm², against 295 and 3,113: the four new programs, 319 words, repeat far less than SPI and I²C did, so Yosys folds them less, about 1.4 cells a word. The ROM is now as big as the accumulator and the run test together.
- Harden: CI run 36480996749 on `85d9380`, tapeout-gds workflow, precheck green. Flow synth 1,894 cells, 25,268 µm², from `06-yosys-synthesis/reports/stat.rpt`: 176 tie-high, one per flop, and 8 tie-low as before, so the wrapper's 1,724 under the quick script plus the ties. v1.1 was 1,010: +884 cells, of which the core's new logic is about 407, the ROM's new words about 449, the rest ties for the 38 new flops.
- Routed: 2,403 cells, 31,759 µm², 3.52% of the 6x4 core, +1,069 cells and +11,510 µm² over v1.1. Zero routing DRC, Magic DRC, antenna and LVS errors, no setup or hold violations at any corner.
- **First row with slew violations: 26 at the slow corner, none at typ or fast.** Three nets, each a NOR3 or NOR4 of the fetch address (`imem_addr`, the pc, through its fanout buffers) that the ROM's `{sel, addr}` decode shares out to a dozen gates: `_1900_` and `_1906_` 2.80 ns and 2.68 ns against the 2.51 ns limit, `_1949_` 2.55 ns. Nine, eight and nine pins, so 26, all on `_1` cells. Signoff does not fail on slew and timing is met with the degraded edges; this flow repairs design rules once, after global placement (step 32), and nothing after routing. They are the ROM's address minterms, so the pressure is the library's size, not the core's logic.
- The one max-fanout violation, `clkbuf_0_clk` driving 16 against a limit of 8, is the clock tree's root buffer and was there in CI run 36466255523 as well; not new, and not in the notes before because earlier rows did not look.
- Routed minus synth is 509: 224 `dlygate4sd3_1` hold fixes (v1.1 had 192, same pins), 215 `buf_1` in the netlist against v1.1's 73, and the clock tree over 176 flops.
- Timing per corner: setup +7.20 ns slow, +10.74 typ, +11.09 fast; hold +0.11 fast, +0.33 typ, +0.69 slow. At slow the worst path is 12.9 ns, 3 ns longer than v1.1, and it is the fetch into the accumulator: `imem_addr[2]` through a hold gate, the ROM decode, the instruction decode, the acc input mux, into `acc[4]`. Typ and fast match v1.1 to 10 ps because there the worst path is not flop to flop; flop to flop at typ is +11.91. 50 MHz still has over a third of the period spare at slow.
- Budget: 1,894 synth cells is about 8% of the ~24K guidance for 6x4, 3.5% of the area. Of that, the ROM and host are 744 quick-synth cells and the core 719; the library is now as much of the chip as the engine.
- The CI run on `35ea2da` (36466255523), where the ROM reached neither feature, routed at +10.01 ns slow setup with no slew violations: so both the 3 ns and the slew come from what the new programs make the fetch reach, not from REPEAT's or the accumulator's logic sitting idle.

## Unit costs, typ lib

Per-cell areas from the mapped netlist, for reading deltas: a reset flop `dfrbpq_1` is 49.0 µm², `mux2_1` 18.1, `mux4_1` 38.1, `nand2_1` 7.3, `inv_1` 5.4. So a plain 8-bit register is about 390 µm² of flops before its muxing, and a FIFO's storage scales at about 49 µm² per bit plus pointers and the read mux. Measure anyway; abc does not always map the way the arithmetic suggests.

## Flow

Same versions as `tt-gds-action@ihp-cmos5l` on 2026-09-25: ttihp-verilog-template `cmos5l`, tt-support-tools `ihp-sg13cmos5l`, LibreLane 3.1.0.dev3 in Docker, IHP-Open-PDK `2bbec755`, `sg13cmos5l_stdcell_typ_1p20V_25C.lib`. The 6x4 run takes about 50 minutes on this machine, most of it Magic DRC over the fill. `make synth` takes seconds and tracks the synth-cells column; use it while iterating and run `make harden` at each milestone.

```
cd asic/janestreet
make synth      # yosys, core alone
make harden     # full flow, runs/wokwi/
make stats      # utilization, cell categories, warnings
```
