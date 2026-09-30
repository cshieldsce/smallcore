# Tiny Tapeout IHP CMOS5L packaging for the Jane Street protocol emulator competition.
# The RTL lives in ../../rtl; `make sync` stages it into src/. Nothing in src/smallcore.v, host.v, rom.v, ram.v, top.v, core.v, fifo.v is edited by hand.
#
# One-time setup (WSL/Linux): make setup            clones tt-support-tools into tt/ and installs the PDK into $(PDK_ROOT)
#                              python venv with     pip install -r tt/requirements.txt librelane==$(LIBRELANE_VERSION)
#                              docker or podman     LibreLane runs its tools in ghcr.io/librelane/librelane:$(LIBRELANE_VERSION)
PDK_ROOT          ?= $(HOME)/pdk
VENV              ?= $(HOME)/venvs/tt
PYTHON            ?= python3
YOSYS             ?= yosys
LIBRELANE_VERSION ?= 3.1.0.dev3
TT_TOOLS_REF      ?= ihp-sg13cmos5l
TT                 = $(PYTHON) tt/tt_tool.py --ihp
RTL                = ../../rtl
RTL_FILES          = smallcore.v host.v rom.v ram.v top.v core.v fifo.v

export PDK_ROOT
# tt_tool.py shells out to yowasp-yosys by name, so the venv's bin/ has to be on PATH, not just its python
ifneq ($(wildcard $(VENV)/bin/python),)
export PATH := $(VENV)/bin:$(PATH)
endif
# Rootless podman under SELinux (Fedora): LibreLane mounts $HOME and the PDK without :z, so the container can't read
# them. This override turns off SELinux labelling for these containers only; docker ignores it
export CONTAINERS_CONF_OVERRIDE = $(CURDIR)/scripts/containers.conf
export PDK = ihp-sg13cmos5l

.PHONY: sync check synth synth-top synth-breakdown config harden stats test setup clean

sync:  # stage the canonical RTL into src/ for the physical build
	cp $(addprefix $(RTL)/,$(RTL_FILES)) src/

check:  # fail if src/ has drifted from rtl/
	for f in $(RTL_FILES); do diff -q $(RTL)/$$f src/$$f || exit 1; done

synth: sync  # quick yosys mapping of the core alone against the typ lib: cells and cell area, seconds not minutes
	mkdir -p build/synth
	TOP=core $(YOSYS) -q -c scripts/synth_core.tcl
	grep -E " cells$$|Chip area" build/synth/core_stat.txt

synth-top: sync  # same for the TT wrapper + core, what LibreLane's synthesis step sees
	mkdir -p build/synth
	TOP=tt_um_cshieldsce_smallcore $(YOSYS) -q -c scripts/synth_core.tcl
	grep -E " cells$$|Chip area" build/synth/tt_um_cshieldsce_smallcore_stat.txt

synth-breakdown: sync  # cells, area and flops for core, top, smallcore and wrapper, one row of docs/physical-results.md's breakdown table
	mkdir -p build/synth
	@for t in core top smallcore tt_um_cshieldsce_smallcore; do \
	  TOP=$$t $(YOSYS) -q -c scripts/synth_core.tcl || exit 1; \
	  f=build/synth/$${t}_stat.txt; \
	  printf '%-28s cells %6s  area %10s um2  flops %4s\n' $$t \
	    "$$(awk '/ cells$$/ {print $$1; exit}' $$f)" \
	    "$$(awk '/Chip area/ {printf "%.0f", $$NF}' $$f)" \
	    "$$(awk '/dfrbp/ {n += $$1} END {print n+0}' $$f)"; \
	done

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

test: sync  # cocotb smoke test of the wrapper, test/. The template defaults to icarus; Verilator is what tests/rtl/ uses
	cd test && $(MAKE) SIM=verilator EXTRA_ARGS="--timing -Wno-fatal"

setup:
	test -d tt || git clone -b $(TT_TOOLS_REF) https://github.com/TinyTapeout/tt-support-tools tt
	test -f $(PDK_ROOT)/ihp-sg13cmos5l/SOURCES || bash scripts/install_pdk.sh

clean:
	rm -rf build runs tt_submission src/user_config.json src/config_merged.json test/sim_build test/results.xml
