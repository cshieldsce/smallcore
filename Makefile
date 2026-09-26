# Short names for the commands in the README. Each one is a plain command you can run by hand.
PYTHON ?= python3

.PHONY: test test-model test-rtl lint clean tapeout-sync tapeout-check

test: test-model test-rtl

test-model:  # the golden Python model and assembler, tests/
	$(PYTHON) -m pytest tests

test-rtl:  # rtl/core.v under Verilator + cocotb, rtl_tests/; WAVES=1 also writes build/rtl/dump.vcd
	$(PYTHON) -m pytest rtl_tests -v

lint:  # Verilator static checks, no simulation; -Wno-fatal prints warnings without failing while the core is incomplete
	verilator --lint-only -Wall -Wno-fatal rtl/core.v

clean:
	rm -rf build

tapeout-sync:  # stage rtl/core.v into tapeout/janestreet/src/ for the Tiny Tapeout CMOS5L build, see tapeout/janestreet/README.md
	$(MAKE) -C tapeout/janestreet sync

tapeout-check:  # fail if the staged copy has drifted from rtl/
	$(MAKE) -C tapeout/janestreet check
