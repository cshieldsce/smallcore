# Physical results

Measured numbers from the Tiny Tapeout IHP CMOS5L flow in `tapeout/janestreet/`, one row per RTL milestone. Architectural tradeoffs get decided against this table, not by estimate.

## Milestones

| Milestone | Synth cells | Routed cells | Cell area | Util. | Setup slack | Hold slack | Date |
|---|---|---|---|---|---|---|---|
| RTL-0 control (pc, delay counter, decode, stall) | 161 | 209 | 2642 µm² | 0.29% | +12.2 ns | +0.12 ns | 2026-09-25 |
| + SET/GPIO | – | | | | | | |
| + CONFIG | – | | | | | | |
| + SHIFT | – | | | | | | |
| + WAIT/JMP/SKIP | – | | | | | | |
| + FIFO interface | – | | | | | | |
| + FIFO storage (top: core + TX/RX FIFOs, DEPTH 4) | 695 | pending | pending | pending | pending | pending | 2026-09-26 |
| + program memory/interface | | | | | | | |
| final | | | | | | | |

Columns, all from `runs/wokwi/final/metrics.csv` unless noted:

- Synth cells: LibreLane's Yosys report, `*-yosys-synthesis/reports/stat.rpt`, wrapper plus core, including tie cells.
- Routed cells: `design__instance__count__stdcell` after routing; adds clock-tree, hold and timing-repair buffers. Excludes fill and tap cells.
- Cell area: `design__instance__area__stdcell`, µm² of standard cells.
- Util.: `design__instance__utilization`, cell area over the 6x4 core area of 902,417 µm² (die 1289.28 µm x 710.64 µm).
- Setup and hold slack: `timing__setup__ws` and `timing__hold__ws` at the template's 20 ns clock, typ corner, post-route parasitics.

Every row so far also had zero routing DRC errors, zero Magic DRC errors, zero antenna violations and zero LVS errors; a row that does not will say so.

## Synthesis breakdown

Where the cells go, one row per milestone, appended as they land. Yosys + abc against the typ lib, no place and route, so a row takes seconds; the flow column is the Milestones table's synth cells.

| Milestone | Core cells | Core area | Core flops | FIFO cells | FIFO area | FIFO flops | Top cells | Top area | Flow synth cells | Flow synth area | Commit | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RTL-0 control | 98 | 1,517 µm² | 14 | – | – | – | 98 | 1,517 µm² | 161 | – | – | 2026-09-25 |
| + FIFO storage (2 × DEPTH 4) | 310 | 4,380 µm² | 39 | 257 | 6,630 µm² | 82 | 567 | 11,010 µm² | 695 | 11,948 µm² | `f795664` | 2026-09-26 |

- Core: `make synth`, `core` alone.
- FIFO: `top` minus `core`, both FIFOs together. Derived, since the two are flattened into one netlist.
- Top: `top` alone, core plus FIFOs, no wrapper. At RTL-0 there was no `top`, so it is the core.
- Flow synth: LibreLane's `*-yosys-synthesis/reports/stat.rpt`, wrapper included, so it adds tie cells and the wrapper's pin logic.
- Flops: `sg13cmos5l_dfrbpq_1` count in the mapped netlist.

To add a row: from `tapeout/janestreet/`, run `make synth-breakdown`. It prints cells, area and flops for `core`, `top` and the wrapper; subtract core from top for the FIFO columns. Take the flow columns from the harden, and put anything surprising in that milestone's notes section.

## RTL-0 notes

- Core alone under Yosys (`make synth`, no wrapper): 98 cells, 1517 µm², 14 flops. The flops are `pc[8:0]` and `delay_counter[4:0]`. `gpio_out` folds to constant 1111 because nothing drives it after reset yet.
- 30 of the 161 synth cells are tie-high/tie-low from the wrapper's constant outputs and the constant `gpio_out`; 27 routed cells are hold-fix delay gates on the input paths. Both are wrapper and pin artefacts, not core logic.
- Timing: the worst path is under 8 ns, so the flow's 50 MHz constraint is not close to binding. The clock target is not decided.
- Budget: Jane Street's guidance is about 1K logic cells per tile, roughly 24K for 6x4, with room left for clock tree and routing.
- Verilator lint in the flow: 11 `UNUSEDSIGNAL` warnings in `core.v`, all decode wires for instructions not yet built. No errors.
- The wrapper's pin mapping is provisional and shares pins between core inputs; see `tapeout/janestreet/src/tt_um_cshieldsce_smallcore.v`. Rows are comparable to each other as long as the wrapper stays the same; when the real pin mapping lands, note it in that row.

## FIFO storage notes

Commit `f795664`: `rtl/top.v` with the complete ISA core, a TX FIFO and an RX FIFO, both DEPTH 4, end-to-end UART TX and RX passing in `rtl_tests/top_tb.py`. The rows from SET/GPIO to FIFO interface were not hardened on their own; this row is the first measurement after RTL-0 and covers all of them.

- Wrapper change: `src/tt_um_cshieldsce_smallcore.v` now instantiates `top` instead of `core`, and `make sync` stages `top.v`, `core.v` and `fifo.v`. The old wrapper predated the FIFO ports: it left the core's `tx_data` undriven and `gpio_oe`, `rx_data`, `pull_en`, `push_en` unconnected, so synthesis would have pruned logic and under-reported the core. The new wrapper folds `tx_full`, `rx_empty` and the parity of each `rx_data` nibble into `uio_out[7:4]` with `gpio_oe`, so every output reaches a port. Still provisional pins; not comparable one-for-one with RTL-0's wrapper.
- Synth cells 695 (11,948 µm² synth area) from LibreLane's `06-yosys-synthesis/reports/stat.rpt`. 125 of them are tie-high: every flop maps to `dfrbpq_1` with its async `RESET_B` tied off, since reset is synchronous, so each of the 121 flops gets a tie, plus 4 for the constant `uio_oe` bits.
- Per-block numbers are in the Synthesis breakdown table. Wrapper + `top` under the quick script is 585 cells and 11,091 µm²; the flow's 695 is higher mostly from its tie cells.
- Core flops, 39, match its registers exactly: pc 9, delay_counter 5, gpio_out 4, shift_dir 1, open_drain 4, shift_reg 8, in_shift_reg 8. RTL-0's core was 98 cells and 1,517 µm², so the ISA added about 212 cells and 2,860 µm².
- The two FIFOs cost about 257 cells and 6,630 µm², 60% of `top`. They have 82 flops: 64 storage, 4 + 4 pointers, 3 + 3 count, and 4 more that appear to be duplicate read-pointer registers from Yosys's memory mapping (2-bit registers driving the read-mux selects). 49 µm² × 82 ≈ 4,020 µm² is flops, the rest is write enables and the read mux. FIFO depth is the biggest area lever so far.
- Verilator lint in the flow: 0 warnings (RTL-0 had 11 `UNUSEDSIGNAL`).
- Budget: 695 synth cells is under 3% of the ~24K guidance for 6x4.
- An earlier harden of the core alone, through the old wrapper, finished at 22:54 but was never recorded, and its `runs/wokwi/` was deleted by this run. It would not have been a valid FIFO-interface row anyway, for the pruning reason above.

## Unit costs, typ lib

Per-cell areas from the mapped netlist, for reading deltas: a reset flop `dfrbpq_1` is 49.0 µm², `mux2_1` 18.1, `mux4_1` 38.1, `nand2_1` 7.3, `inv_1` 5.4. So a plain 8-bit register is about 390 µm² of flops before its muxing, and a FIFO's storage scales at about 49 µm² per bit plus pointers and the read mux. Measure anyway; abc does not always map the way the arithmetic suggests.

## Flow

Same versions as `tt-gds-action@ihp-cmos5l` on 2026-09-25: ttihp-verilog-template `cmos5l`, tt-support-tools `ihp-sg13cmos5l`, LibreLane 3.1.0.dev3 in Docker, IHP-Open-PDK `2bbec755`, `sg13cmos5l_stdcell_typ_1p20V_25C.lib`. The 6x4 run takes about 50 minutes on this machine, most of it Magic DRC over the fill. `make synth` takes seconds and tracks the synth-cells column; use it while iterating and run `make harden` at each milestone.

```
cd tapeout/janestreet
make synth      # yosys, core alone
make harden     # full flow, runs/wokwi/
make stats      # utilization, cell categories, warnings
```
