# Builds the PYNQ-Z2 design where the Zynq's ARM is the SmallCore host, smallcore_pynq_axi.v with
# the block design sc_ps (PS7, AXI3 to AXI4-Lite, AXI clock converter, resets), into
# build/pynq_z2_axi: smallcore_pynq_axi_div<CORE_DIV>.bit and .xsa (the hardware platform, with
# ps7_init.tcl for xsdb, the bitstream and the .hwh PYNQ wants).
# Batch: vivado -mode batch -source C:/core/fpga/pynq_z2/build_axi.tcl [-tclargs CORE_DIV]
# CORE_DIV 1, 2, 4, 8: a core clock of 8, 4, 2, 1 MHz. The peripheral is at 0x43C0_0000.
set here [file normalize [file dirname [info script]]]
set root [file normalize [file join $here .. ..]]
set div  [expr {[llength $argv] ? [lindex $argv 0] : 8}]
set out  [file join $root build pynq_z2_axi]
set proj [file join $out proj_div$div]
file mkdir $out

create_project -force sc_axi $proj -part xc7z020clg400-1
set_property target_language Verilog [current_project]

create_bd_design sc_ps

set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 ps7]
source [file join $here ps7_pynq_z2.tcl]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} $ps7

# the core clock and its lock come in from the MMCM; the reset synchronous to it goes out
set core_clk [create_bd_port -dir I -type clk core_clk]
set_property CONFIG.FREQ_HZ [expr {8000000 / $div}] $core_clk
create_bd_port -dir I core_locked
create_bd_port -dir O -type rst core_aresetn
set m_axi [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:aximm_rtl:1.0 M_AXI_SC]
set_property -dict [list CONFIG.PROTOCOL AXI4LITE CONFIG.ADDR_WIDTH 32 CONFIG.DATA_WIDTH 32] $m_axi
set_property -dict [list CONFIG.ASSOCIATED_BUSIF M_AXI_SC CONFIG.ASSOCIATED_RESET core_aresetn] $core_clk

set pc [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_protocol_converter pc]
set_property -dict [list CONFIG.SI_PROTOCOL AXI3 CONFIG.MI_PROTOCOL AXI4LITE] $pc
set cc [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter cc]
set_property -dict [list CONFIG.PROTOCOL AXI4LITE CONFIG.ACLK_ASYNC 1] $cc
set rst_ps   [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ps]
set rst_core [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_core]

connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins pc/S_AXI]
connect_bd_intf_net [get_bd_intf_pins pc/M_AXI] [get_bd_intf_pins cc/S_AXI]
connect_bd_intf_net [get_bd_intf_pins cc/M_AXI] $m_axi

# FCLK0 side
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins ps7/M_AXI_GP0_ACLK] [get_bd_pins pc/aclk] \
    [get_bd_pins cc/s_axi_aclk] [get_bd_pins rst_ps/slowest_sync_clk]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins rst_ps/ext_reset_in] [get_bd_pins rst_core/ext_reset_in]
connect_bd_net [get_bd_pins rst_ps/interconnect_aresetn] [get_bd_pins pc/aresetn] [get_bd_pins cc/s_axi_aresetn]

# core clock side: held in reset until the MMCM locks
connect_bd_net $core_clk [get_bd_pins cc/m_axi_aclk] [get_bd_pins rst_core/slowest_sync_clk]
connect_bd_net [get_bd_ports core_locked] [get_bd_pins rst_core/dcm_locked]
connect_bd_net [get_bd_pins rst_core/peripheral_aresetn] [get_bd_pins cc/m_axi_aresetn] [get_bd_ports core_aresetn]

assign_bd_address -offset 0x43C00000 -range 64K [get_bd_addr_segs M_AXI_SC/Reg]
validate_bd_design
save_bd_design
set bd [get_files sc_ps.bd]
generate_target all $bd

add_files [list \
    [file join $here smallcore_pynq_axi.v] \
    [file join $here smallcore_axi.v] \
    [file join $here can_host_engine.v] \
    [file join $here smallcore_pads.v]]
foreach f {smallcore.v host.v rom.v ram.v top.v core.v fifo.v} { add_files [file join $root rtl $f] }
add_files -fileset constrs_1 [file join $here pynq_z2_axi.xdc]
set_property top smallcore_pynq_axi [current_fileset]
set_property generic CORE_DIV=$div [current_fileset]

launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} { error "implementation failed" }

open_run impl_1
report_timing_summary -file [file join $out timing_summary_div$div.rpt]
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
puts "RESULT WNS=$wns"
file copy -force [file join $proj sc_axi.runs impl_1 smallcore_pynq_axi.bit] [file join $out smallcore_pynq_axi_div$div.bit]
write_hw_platform -fixed -include_bit -force [file join $out smallcore_pynq_axi_div$div.xsa]
puts "RESULT built [file join $out smallcore_pynq_axi_div$div.bit]"
