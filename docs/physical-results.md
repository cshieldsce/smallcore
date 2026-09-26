# Physical results

Measured numbers from the Tiny Tapeout IHP CMOS5L flow in `tapeout/janestreet/`, one row per RTL milestone. Architectural tradeoffs get decided against this table, not by estimate.

## Milestones

| Milestone | Synth cells | Routed cells | Cell area | Util. | Setup slack | Hold slack | Date |
|---|---|---|---|---|---|---|---|
| RTL-0 control (pc, delay counter, decode, stall) | 161 | 209 | 2642 µm² | 0.29% | +12.2 ns | +0.12 ns | 2026-09-25 |
| + SET/GPIO | | | | | | | |
| + CONFIG | | | | | | | |
| + SHIFT | | | | | | | |
| + WAIT/JMP/SKIP | | | | | | | |
| + FIFO interface | | | | | | | |
| + FIFO storage | | | | | | | |
| + program memory/interface | | | | | | | |
| final | | | | | | | |

Columns, all from `runs/wokwi/final/metrics.csv` unless noted:

- Synth cells: LibreLane's Yosys report, `*-yosys-synthesis/reports/stat.rpt`, wrapper plus core, including tie cells.
- Routed cells: `design__instance__count__stdcell` after routing; adds clock-tree, hold and timing-repair buffers. Excludes fill and tap cells.
- Cell area: `design__instance__area__stdcell`, µm² of standard cells.
- Util.: `design__instance__utilization`, cell area over the 6x4 core area of 902,417 µm² (die 1289.28 µm x 710.64 µm).
- Setup and hold slack: `timing__setup__ws` and `timing__hold__ws` at the template's 20 ns clock, typ corner, post-route parasitics.

Every row so far also had zero routing DRC errors, zero Magic DRC errors, zero antenna violations and zero LVS errors; a row that does not will say so.

## RTL-0 notes

- Core alone under Yosys (`make synth`, no wrapper): 98 cells, 1517 µm², 14 flops. The flops are `pc[8:0]` and `delay_counter[4:0]`. `gpio_out` folds to constant 1111 because nothing drives it after reset yet.
- 30 of the 161 synth cells are tie-high/tie-low from the wrapper's constant outputs and the constant `gpio_out`; 27 routed cells are hold-fix delay gates on the input paths. Both are wrapper and pin artefacts, not core logic.
- Timing: the worst path is under 8 ns, so the flow's 50 MHz constraint is not close to binding. The clock target is not decided.
- Budget: Jane Street's guidance is about 1K logic cells per tile, roughly 24K for 6x4, with room left for clock tree and routing.
- Verilator lint in the flow: 11 `UNUSEDSIGNAL` warnings in `core.v`, all decode wires for instructions not yet built. No errors.
- The wrapper's pin mapping is provisional and shares pins between core inputs; see `tapeout/janestreet/src/tt_um_cshieldsce_smallcore.v`. Rows are comparable to each other as long as the wrapper stays the same; when the real pin mapping lands, note it in that row.

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
