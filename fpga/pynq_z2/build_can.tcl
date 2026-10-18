# Builds the PYNQ-Z2 CAN design, smallcore_pynq_can.v with its VIO host and ILAs, into build/pynq_z2_can
# as smallcore_pynq_can_div<CORE_DIV>.bit/.ltx.
# Batch: vivado -mode batch -source C:/core/fpga/pynq_z2/build_can.tcl [-tclargs CORE_DIV]
# CORE_DIV 1, 2, 4, 8: a core clock of 8, 4, 2, 1 MHz, so 1000, 500, 250, 125 kbit/s.
# Needs a license tier with debug cores (the free 2023.2 install has them).
set root [file normalize [file join [file dirname [info script]] .. ..]]
set out  [file join $root build pynq_z2_can]
set div  [expr {[llength $argv] ? [lindex $argv 0] : 1}]
set ipdir [file join $out ip_div$div]
file delete -force $ipdir
file mkdir $ipdir

create_project -in_memory -part xc7z020clg400-1
set_property target_language Verilog [current_project]

create_ip -name vio -vendor xilinx.com -library ip -module_name vio_host -dir $ipdir
set in_w  {8 1 3 3 6 1 9 1 8}
set out_w {8 2 1 1 1 1 256 6 1 4 1 1 1 8}
set cfg [list CONFIG.C_NUM_PROBE_IN [llength $in_w] CONFIG.C_NUM_PROBE_OUT [llength $out_w]]
for {set i 0} {$i < [llength $in_w]} {incr i} { lappend cfg CONFIG.C_PROBE_IN${i}_WIDTH [lindex $in_w $i] }
for {set i 0} {$i < [llength $out_w]} {incr i} { lappend cfg CONFIG.C_PROBE_OUT${i}_WIDTH [lindex $out_w $i] }
set_property -dict $cfg [get_ips vio_host]

create_ip -name ila -vendor xilinx.com -library ip -module_name ila_can -dir $ipdir
set ila_w {1 1 4 4 8 1 1 1 3 3 6 9 2}
set cfg [list CONFIG.C_NUM_OF_PROBES [llength $ila_w] CONFIG.C_DATA_DEPTH 8192]
for {set i 0} {$i < [llength $ila_w]} {incr i} { lappend cfg CONFIG.C_PROBE${i}_WIDTH [lindex $ila_w $i] }
set_property -dict $cfg [get_ips ila_can]

create_ip -name ila -vendor xilinx.com -library ip -module_name ila_loop -dir $ipdir
set_property -dict [list CONFIG.C_NUM_OF_PROBES 2 CONFIG.C_DATA_DEPTH 4096 \
    CONFIG.C_PROBE0_WIDTH 1 CONFIG.C_PROBE1_WIDTH 1] [get_ips ila_loop]

generate_target all [get_ips]
synth_ip [get_ips]

read_verilog [list \
    [file join $root fpga pynq_z2 smallcore_pynq_can.v] \
    [file join $root fpga pynq_z2 can_host_engine.v] \
    [file join $root rtl smallcore.v] \
    [file join $root rtl host.v] \
    [file join $root rtl rom.v] \
    [file join $root rtl ram.v] \
    [file join $root rtl top.v] \
    [file join $root rtl core.v] \
    [file join $root rtl fifo.v]]
read_xdc [file join $root fpga pynq_z2 pynq_z2_can.xdc]

synth_design -top smallcore_pynq_can -part xc7z020clg400-1 -generic CORE_DIV=$div
# the debug hub on 125 MHz: an 8 MHz hub would cap the JTAG clock below 4 MHz
set_property C_CLK_INPUT_FREQ_HZ 125000000 [get_debug_cores dbg_hub]
set_property C_ENABLE_CLK_DIVIDER false [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sysclk_bufg]

opt_design
place_design
route_design
report_timing_summary -file [file join $out timing_summary_div$div.rpt]
write_bitstream -force [file join $out smallcore_pynq_can_div$div.bit]
write_debug_probes -force [file join $out smallcore_pynq_can_div$div.ltx]
