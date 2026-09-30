# Creates the Vivado project for SmallCore with the Zynq's ARM as its host: a block
# design with the PS7 and a SmartConnect out to an external M_AXI port, and the RTL
# top smallcore_pynq_axi.v around it (the AXI bridge, SmallCore, the pads, an ILA).
# GUI:   vivado -mode gui   -source fpga/pynq_z2/create_project_axi.tcl
# Batch: vivado -mode batch -source fpga/pynq_z2/create_project_axi.tcl -tclargs build
# With `build` it runs to a bitstream and copies what the board needs to
# build/pynq_z2_axi/overlay/: smallcore.bit and smallcore.hwh for pynq.Overlay,
# smallcore.ltx for the ILA in Hardware Manager.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set proj [file join $root build pynq_z2_axi]
set part xc7z020clg400-1
set board tul.com.tw:pynq-z2:part0:1.0

create_project -force smallcore_pynq_axi $proj -part $part
set have_board [expr {[llength [get_board_parts -quiet $board]] > 0}]
if {$have_board} {
    set_property board_part $board [current_project]
} else {
    puts "note: board files for $board not installed; the PS7 gets the settings below and no DDR preset. Loading with pynq.Overlay on a running PYNQ image does not need them: Linux already set up the PS."
}

# --- block design: PS7, FCLK_CLK0 100 MHz, reset, SmartConnect -> M_AXI -------------------
create_bd_design system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 ps7]
if {$have_board} {
    apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
        -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} $ps
} else {
    make_bd_intf_pins_external [get_bd_intf_pins ps7/DDR]
    make_bd_intf_pins_external [get_bd_intf_pins ps7/FIXED_IO]
    set_property name DDR [get_bd_intf_ports DDR_0]
    set_property name FIXED_IO [get_bd_intf_ports FIXED_IO_0]
}
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_EN_RST0_PORT {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}] $ps

set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_fclk0]
set sc  [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smartconnect]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $sc

set m_axi [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:aximm_rtl:1.0 M_AXI]
set_property -dict [list \
    CONFIG.PROTOCOL {AXI4LITE} \
    CONFIG.ADDR_WIDTH {32} \
    CONFIG.DATA_WIDTH {32} \
    CONFIG.FREQ_HZ {100000000} \
    CONFIG.HAS_BURST {0} CONFIG.HAS_CACHE {0} CONFIG.HAS_LOCK {0} CONFIG.HAS_QOS {0} CONFIG.HAS_REGION {0}] $m_axi
set aclk [create_bd_port -dir O -type clk aclk]
set_property -dict [list CONFIG.ASSOCIATED_BUSIF {M_AXI} CONFIG.ASSOCIATED_RESET {aresetn} CONFIG.FREQ_HZ {100000000}] $aclk
create_bd_port -dir O -from 0 -to 0 -type rst aresetn

connect_bd_net [get_bd_pins ps7/FCLK_CLK0] \
    [get_bd_pins ps7/M_AXI_GP0_ACLK] [get_bd_pins rst_fclk0/slowest_sync_clk] [get_bd_pins smartconnect/aclk] [get_bd_ports aclk]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins rst_fclk0/ext_reset_in]
connect_bd_net [get_bd_pins rst_fclk0/peripheral_aresetn] [get_bd_pins smartconnect/aresetn] [get_bd_ports aresetn]
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins smartconnect/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins smartconnect/M00_AXI] [get_bd_intf_ports M_AXI]

assign_bd_address -target_address_space /ps7/Data -offset 0x43C00000 -range 64K [get_bd_addr_segs M_AXI/Reg]
validate_bd_design
save_bd_design

set bd [get_files system.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]

# --- the ILA, 10 probes on aclk ------------------------------------------------------------
create_ip -name ila -vendor xilinx.com -library ip -module_name ila_smallcore
set widths {4 4 4 2 1 1 8 8 1 1}
set props [list CONFIG.C_NUM_OF_PROBES [llength $widths] CONFIG.C_DATA_DEPTH {8192} CONFIG.C_INPUT_PIPE_STAGES {0}]
for {set i 0} {$i < [llength $widths]} {incr i} {
    lappend props CONFIG.C_PROBE${i}_WIDTH [lindex $widths $i]
}
set_property -dict $props [get_ips ila_smallcore]
generate_target all [get_files ila_smallcore.xci]

# --- RTL -----------------------------------------------------------------------------------
add_files -norecurse [list \
    [file join $root fpga pynq_z2 smallcore_pynq_axi.v] \
    [file join $root fpga pynq_z2 smallcore_axi.v] \
    [file join $root fpga pynq_z2 axi_host.v] \
    [file join $root rtl smallcore.v] \
    [file join $root rtl host.v] \
    [file join $root rtl rom.v] \
    [file join $root rtl ram.v] \
    [file join $root rtl top.v] \
    [file join $root rtl core.v] \
    [file join $root rtl fifo.v]]
add_files -fileset constrs_1 -norecurse [file join $root fpga pynq_z2 pynq_z2_axi.xdc]
set_property top smallcore_pynq_axi [current_fileset]
update_compile_order -fileset sources_1

if {[lsearch -exact $argv build] >= 0} {
    launch_runs impl_1 -to_step write_bitstream -jobs 4
    wait_on_run impl_1
    open_run impl_1
    report_timing_summary -file [file join $proj timing_summary.rpt]
    set out [file join $proj overlay]
    file mkdir $out
    set impl [get_property DIRECTORY [get_runs impl_1]]
    file copy -force [file join $impl smallcore_pynq_axi.bit] [file join $out smallcore.bit]
    foreach ltx [glob -nocomplain [file join $impl *.ltx]] {
        file copy -force $ltx [file join $out smallcore.ltx]
    }
    set hwh [lindex [glob -nocomplain [file join $proj smallcore_pynq_axi.gen sources_1 bd system hw_handoff system.hwh] \
                                      [file join $proj smallcore_pynq_axi.srcs sources_1 bd system hw_handoff system.hwh]] 0]
    file copy -force $hwh [file join $out smallcore.hwh]
    puts "overlay: $out"
}
