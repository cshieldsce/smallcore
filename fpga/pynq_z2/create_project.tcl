# Creates the Vivado project for the PYNQ-Z2 smoke test.
# GUI:   vivado -mode gui -source C:/core/fpga/pynq_z2/create_project.tcl
# Batch: vivado -mode batch -source C:/core/fpga/pynq_z2/create_project.tcl -tclargs build
set root [file normalize [file join [file dirname [info script]] .. ..]]
set proj [file join $root build pynq_z2]

create_project -force smallcore_pynq $proj -part xc7z020clg400-1

add_files -norecurse [list \
    [file join $root fpga pynq_z2 smallcore_pynq.v] \
    [file join $root rtl smallcore.v] \
    [file join $root rtl host.v] \
    [file join $root rtl rom.v] \
    [file join $root rtl ram.v] \
    [file join $root rtl top.v] \
    [file join $root rtl core.v] \
    [file join $root rtl fifo.v]]
add_files -fileset constrs_1 -norecurse [file join $root fpga pynq_z2 pynq_z2.xdc]
set_property top smallcore_pynq [current_fileset]
update_compile_order -fileset sources_1

if {[lsearch -exact $argv build] >= 0} {
    launch_runs impl_1 -to_step write_bitstream -jobs 4
    wait_on_run impl_1
    open_run impl_1
    report_timing_summary -file [file join $proj timing_summary.rpt]
}
