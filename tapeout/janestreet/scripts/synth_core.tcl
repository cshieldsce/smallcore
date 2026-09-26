# Quick area check of the staged RTL, no place-and-route.
# TOP=core yosys -c scripts/synth_core.tcl      (needs PDK_ROOT; see Makefile `synth` and `synth-top`)
# Same front end LibreLane uses (yosys synth, dfflibmap, abc against the typ lib) minus the physical steps,
# so the numbers track the flow's synthesis report but are not the post-route numbers.
yosys -import
set lib $::env(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib
set top $::env(TOP)
read_verilog -sv src/core.v
if {$top ne "core"} { read_verilog -sv src/tt_um_cshieldsce_smallcore.v }
hierarchy -check -top $top
synth -top $top -flatten
dfflibmap -liberty $lib
abc -liberty $lib
opt_clean -purge
tee -o build/synth/${top}_stat.txt stat -liberty $lib
write_verilog -noattr build/synth/${top}_mapped.v
