# Tiny Tapeout IHP CMOS5L packaging for the Jane Street protocol emulator competition.
# The RTL lives in ../../rtl; `make sync` stages it into src/. Nothing in src/core.v is edited by hand.
#
# One-time setup (WSL/Linux): make setup            clones tt-support-tools into tt/ and installs the PDK into $(PDK_ROOT)
#                              python venv with     pip install -r tt/requirements.txt librelane==$(LIBRELANE_VERSION)
#                              docker               LibreLane runs its tools in ghcr.io/librelane/librelane:$(LIBRELANE_VERSION)
PDK_ROOT          ?= $(HOME)/pdk
PYTHON            ?= python3
YOSYS             ?= yosys
LIBRELANE_VERSION ?= 3.1.0.dev3
TT_TOOLS_REF      ?= ihp-sg13cmos5l
TT                 = $(PYTHON) tt/tt_tool.py --ihp
RTL                = ../../rtl

export PDK_ROOT
export PDK = ihp-sg13cmos5l

.PHONY: sync check synth synth-top config harden stats test setup clean

sync:  # stage the canonical RTL into src/ for the physical build
	cp $(RTL)/core.v src/core.v

check:  # fail if src/ has drifted from rtl/
	diff -q $(RTL)/core.v src/core.v

synth: sync  # quick yosys mapping of the core alone against the typ lib: cells and cell area, seconds not minutes
	mkdir -p build/synth
	TOP=core $(YOSYS) -q -c scripts/synth_core.tcl
	grep -E " cells$|Chip area" build/synth/core_stat.txt

synth-top: sync  # same for the TT wrapper + core, what LibreLane's synthesis step sees
	mkdir -p build/synth
	TOP=tt_um_cshieldsce_smallcore $(YOSYS) -q -c scripts/synth_core.tcl
	grep -E " cells$|Chip area" build/synth/tt_um_cshieldsce_smallcore_stat.txt

config: sync  # src/user_config.json + src/config_merged.json from info.yaml (6x4 die area, def template)
	$(TT) --create-user-config

harden: config  # full LibreLane flow into runs/wokwi: the command tt_tool.py --harden runs, spelled out because
	# tt_tool wants the project dir to be a git root and this one is nested in the SmallCore repo
	rm -rf runs/wokwi && mkdir -p runs/wokwi
	$(PYTHON) -m librelane --pdk-root "$(PDK_ROOT)" --docker-no-tty --dockerized --pdk ihp-sg13cmos5l --manual-pdk 	  --run-tag wokwi --force-run-dir runs/wokwi src/config_merged.json

stats:  # after harden: LibreLane's routing summary, cell categories, yosys warnings
	$(TT) --print-stats
	$(TT) --print-cell-category
	$(TT) --print-warnings

test: sync  # cocotb smoke test of the wrapper, test/. The template defaults to icarus; Verilator is what rtl_tests/ uses
	$(MAKE) -C test SIM=verilator EXTRA_ARGS="--timing -Wno-fatal"

setup:
	test -d tt || git clone -b $(TT_TOOLS_REF) https://github.com/TinyTapeout/tt-support-tools tt
	test -f $(PDK_ROOT)/ihp-sg13cmos5l/SOURCES || bash scripts/install_pdk.sh

clean:
	rm -rf build runs tt_submission src/user_config.json src/config_merged.json test/sim_build test/results.xml
