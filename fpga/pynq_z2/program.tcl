# Loads the PYNQ-Z2 bitstream over USB-JTAG. Volatile: power cycling, PROG or SRST clears it.
# Plain: vivado -mode batch -source C:/core/fpga/pynq_z2/program.tcl
# ILA:   vivado -mode batch -source C:/core/fpga/pynq_z2/program.tcl -tclargs ila
# Build first: create_project.tcl -tclargs build, or build_ila.tcl for the ILA build.
set root [file normalize [file join [file dirname [info script]] .. ..]]

if {[lsearch -exact $argv ila] >= 0} {
    set bit [file join $root build pynq_z2_ila smallcore_pynq_ila.bit]
    set ltx [file join $root build pynq_z2_ila smallcore_pynq_ila.ltx]
} else {
    set bit [file join $root build pynq_z2 smallcore_pynq.runs impl_1 smallcore_pynq.bit]
    set ltx ""
}

open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target
set dev [lindex [get_hw_devices xc7z020_1] 0]
current_hw_device $dev
set_property PROGRAM.FILE $bit $dev
if {$ltx ne ""} {
    set_property PROBES.FILE $ltx $dev
    set_property FULL_PROBES.FILE $ltx $dev
}
program_hw_devices $dev
refresh_hw_device $dev
# DONE goes to 0 if anything clears the PL afterwards; the green DONE LED shows the same
puts "DONE: [get_property REGISTER.IR.BIT5_DONE $dev]"
close_hw_target
disconnect_hw_server
close_hw_manager
