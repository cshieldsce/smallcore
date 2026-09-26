# SmallCore on Tiny Tapeout IHP CMOS5L

Packaging for the Jane Street protocol emulator competition: Tiny Tapeout's IHP 130 nm CMOS5L flow, 6x4 tiles. Laid out like the official [ttihp-verilog-template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l) (`cmos5l` branch) so the same tools and GitHub action apply.

This directory is packaging, not a source tree. The RTL is `rtl/core.v` at the repository root; `make sync` copies it into `src/`, `make check` fails if the two have drifted. The staged copy is committed because the Tiny Tapeout action builds from the repository, so run `make sync` before committing an RTL change (or `make tapeout-sync` from the root).

```
info.yaml                       project metadata, tiles: "6x4", top module, source list, provisional pinout
src/tt_um_cshieldsce_smallcore.v  TT wrapper: pins, active-low reset, core instance. Provisional, elaboration only
src/core.v                      staged from ../../rtl/core.v, do not edit here
src/config.json                 LibreLane config from the template, unchanged
test/                           cocotb smoke test of the wrapper (template layout)
docs/info.md                    datasheet source
scripts/synth_core.tcl          quick yosys mapping against the CMOS5L typ lib, no P&R
scripts/install_pdk.sh          the PDK install step from tt-gds-action (ihp-cmos5l branch)
Makefile                        sync, check, synth, synth-top, config, harden, stats, test, setup
```

## Setup (Linux or WSL)

```
make setup                                  # tt/ = tt-support-tools (ihp-sg13cmos5l branch), PDK into $PDK_ROOT (default ~/pdk)
python3.11 -m venv ~/venvs/tt && . ~/venvs/tt/bin/activate
pip install -r tt/requirements.txt librelane==3.1.0.dev3
docker pull ghcr.io/librelane/librelane:3.1.0.dev3    # LibreLane runs OpenROAD etc. in this image
```

`yosys` on the PATH (oss-cad-suite) is enough for `make synth`; the full flow needs the venv and Docker. Versions match `tt-gds-action@ihp-cmos5l` on 2026-09-25: tt-support-tools `ihp-sg13cmos5l`, LibreLane `3.1.0.dev3`, IHP-Open-PDK `2bbec755`.

## Commands

```
make sync         # rtl/core.v -> src/core.v
make check        # diff, fails on drift
make synth        # yosys: cells and cell area of core alone, build/synth/core_stat.txt
make synth-top    # same for wrapper + core
make harden       # LibreLane, runs/wokwi/, what the GitHub action does
make stats        # after harden: utilization, cell categories, yosys warnings
make test         # cocotb smoke test under icarus
```

## What to read from a run

- `build/synth/*_stat.txt`: mapped cell count and cell area (µm²) from yosys + abc against `sg13cmos5l_stdcell_typ_1p20V_25C.lib`. Fast, use it for architectural comparisons.
- `runs/wokwi/final/metrics.csv`: `design__instance__count`, `design__instance__area`, `design__instance__utilization`, `timing__setup__ws`, `timing__hold__ws`, `route__drc_errors`, `antenna__violating__nets`. The numbers that count.
- `runs/wokwi/*-yosys-synthesis/reports/stat.rpt`: LibreLane's own synthesis report.
- `runs/wokwi/*-verilator-lint/verilator-lint.log`: the flow's lint (`-Wall`); the action prints it in the job summary.

Jane Street's guidance: budget about 1K logic cells per tile, so roughly 24K for 6x4, and leave room for clock-tree buffers and routing. The 6x4 die is 1289.28 µm x 710.64 µm (`tt/tech/ihp-sg13cmos5l/tile_sizes.yaml`).

## Results

The milestone table lives in `docs/physical-results.md` at the repository root, with the column definitions and the RTL-0 baseline.

## Submission note

The Tiny Tapeout action and the submission app expect `info.yaml`, `src/`, `docs/` and `test/` at a repository root. When it is time to submit, either mirror this directory to its own repository or run `tt/tt_tool.py --project-dir tapeout/janestreet` from a workflow in this one. Not decided yet.
