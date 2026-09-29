# Synthesis snapshot @ cccac19 (RTL-0 baseline)

- RTL: `rtl/core.v` at commit `cccac19` ("manual gds workflow for asic/janestreet"); `rtl/` is identical to `2b7bd5a` ("size counter and pc constants")
- Hardened by GitHub Actions "tapeout gds" run 36222459790, 2026-09-26 06:00–06:51 UTC:
  https://github.com/cshieldsce/smallcore/actions/runs/36222459790
  (gds, precheck and viewer passed; gl_test failed with no `test/results.xml`)
- Physical numbers are also in `docs/physical-results.md` (RTL-0 row, commit `27eea7f`)
- Flow: tt-gds-action `ihp-cmos5l`, LibreLane 3.1.0.dev3, IHP-Open-PDK `2bbec755`, typ 1p20V 25C lib
- `cccac19_metrics.csv` is the run's full `tt_submission/stats/metrics.csv`

## Summary

| | local `make synth` (core) | local `make synth-top` | action: LibreLane synth | action: routed |
|---|---|---|---|---|
| cells | 104 | 108 | 161 (30 tie cells, 8 buf) | 209 |
| area (µm²) | 1525.8 | 1560.4 | 1999.4 | 2641.8 |
| flops (`dfrbpq_1`) | 14, 685.8 | 14, 685.8 | 14, 685.8 | |

Routed (from metrics.csv): utilization 0.29% of 902,417 µm² core, setup WS +12.21 ns, hold WS +0.12 ns at 20 ns,
0 route DRC, 0 Magic DRC, 0 antenna, 0 LVS.

The local columns were re-run on 2026-09-26 with Yosys 0.63 in a checkout of `cccac19`. `docs/physical-results.md`
records the core as 98 cells / 1517 µm² with the same 14 flops; the gap is combinational mapping (yosys/abc version
or run), not a design change.

## Raw: action LibreLane synthesis (`tt_submission/stats/synthesis-stats.txt`)

```
125. Printing statistics.

=== tt_um_cshieldsce_smallcore ===

        +----------Local Count, excluding submodules.
        |        +-Local Area, excluding submodules.
        |        | 
      145        - wires
      180        - wire bits
       22        - public wires
       57        - public wire bits
        8        - ports
       43        - port bits
      161    2E+03 cells
        3   38.102   sg13cmos5l_a21o_1
       10    90.72   sg13cmos5l_a21oi_1
        5   72.576   sg13cmos5l_a221oi_1
        2   21.697   sg13cmos5l_a22oi_1
        1    9.072   sg13cmos5l_and2_1
        4   50.803   sg13cmos5l_and3_1
        8   58.061   sg13cmos5l_buf_1
       14  685.843   sg13cmos5l_dfrbpq_1
       12   65.318   sg13cmos5l_inv_1
        1   18.144   sg13cmos5l_mux2_1
        1   38.102   sg13cmos5l_mux4_1
        9   65.318   sg13cmos5l_nand2_1
       10    90.72   sg13cmos5l_nand2b_1
        8   72.576   sg13cmos5l_nand3_1
        1   12.701   sg13cmos5l_nand3b_1
        2   21.773   sg13cmos5l_nand4_1
        7   50.803   sg13cmos5l_nor2_1
       12  108.864   sg13cmos5l_nor2b_1
        5    45.36   sg13cmos5l_nor3_1
        2   21.773   sg13cmos5l_nor4_1
        8   72.576   sg13cmos5l_o21ai_1
        3   27.216   sg13cmos5l_or2_1
        1   14.515   sg13cmos5l_or4_1
       22  159.667   sg13cmos5l_tiehi
        8   58.061   sg13cmos5l_tielo
        1   14.515   sg13cmos5l_xnor2_1
        1   14.515   sg13cmos5l_xor2_1

   Chip area for module '\tt_um_cshieldsce_smallcore': 1999.393200
     of which used for sequential elements: 685.843200 (34.30%)

```

## Raw: local yosys `stat`, core

```

7. Printing statistics.

=== core ===

        +----------Local Count, excluding submodules.
        |        +-Local Area, excluding submodules.
        |        | 
      101        - wires
      149        - wire bits
       11        - public wires
       59        - public wire bits
        9        - ports
       45        - port bits
      104 1.53E+03 cells
       12  108.864   sg13cmos5l_a21oi_1
        2    29.03   sg13cmos5l_a221oi_1
        2   21.697   sg13cmos5l_a22oi_1
        2   18.144   sg13cmos5l_and2_1
        1   14.515   sg13cmos5l_and4_1
       14  685.843   sg13cmos5l_dfrbpq_1
        9   48.989   sg13cmos5l_inv_1
        1   18.144   sg13cmos5l_mux2_1
        1   38.102   sg13cmos5l_mux4_1
        5   36.288   sg13cmos5l_nand2_1
        7   63.504   sg13cmos5l_nand2b_1
        1    9.072   sg13cmos5l_nand3_1
        1   12.701   sg13cmos5l_nand3b_1
        2   21.773   sg13cmos5l_nand4_1
       10   72.576   sg13cmos5l_nor2_1
        4   36.288   sg13cmos5l_nor2b_1
        7   63.504   sg13cmos5l_nor3_1
        4   43.546   sg13cmos5l_nor4_1
       15   136.08   sg13cmos5l_o21ai_1
        2   18.144   sg13cmos5l_or2_1
        1   14.515   sg13cmos5l_xnor2_1
        1   14.515   sg13cmos5l_xor2_1

   Chip area for module '\core': 1525.834800
     of which used for sequential elements: 685.843200 (44.95%)

```

## Raw: local yosys `stat`, tt_um_cshieldsce_smallcore

```

8. Printing statistics.

=== tt_um_cshieldsce_smallcore ===

        +----------Local Count, excluding submodules.
        |        +-Local Area, excluding submodules.
        |        | 
      104        - wires
      151        - wire bits
       10        - public wires
       57        - public wire bits
        8        - ports
       43        - port bits
      108 1.56E+03 cells
        1   12.701   sg13cmos5l_a21o_1
       10    90.72   sg13cmos5l_a21oi_1
        1   14.515   sg13cmos5l_a221oi_1
        1    9.072   sg13cmos5l_and2_1
        1   14.515   sg13cmos5l_and4_1
       14  685.843   sg13cmos5l_dfrbpq_1
       10   54.432   sg13cmos5l_inv_1
        1   38.102   sg13cmos5l_mux4_1
        7   50.803   sg13cmos5l_nand2_1
       10    90.72   sg13cmos5l_nand2b_1
        1   12.701   sg13cmos5l_nand3b_1
        2   21.773   sg13cmos5l_nand4_1
        8   58.061   sg13cmos5l_nor2_1
        7   63.504   sg13cmos5l_nor2b_1
        9   81.648   sg13cmos5l_nor3_1
        4   43.546   sg13cmos5l_nor4_1
       15   136.08   sg13cmos5l_o21ai_1
        1    9.072   sg13cmos5l_or2_1
        1   14.515   sg13cmos5l_or4_1
        1   14.515   sg13cmos5l_xnor2_1
        3   43.546   sg13cmos5l_xor2_1

   Chip area for module '\tt_um_cshieldsce_smallcore': 1560.384000
     of which used for sequential elements: 685.843200 (43.95%)

```
