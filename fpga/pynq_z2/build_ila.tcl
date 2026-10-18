# Builds the PYNQ-Z2 smoke test with an ILA on the core clock, non-project, into build/pynq_z2_ila.
# Batch: vivado -mode batch -source C:/core/fpga/pynq_z2/build_ila.tcl
# Needs a license tier with debug cores: the free 2023.2 install has them, a 2026.1 BASIC
# license refuses create_debug_core.
#
# Probes, as Vivado names them after synthesis:
#   ja_IBUF[3:0]   the four pads as read back: MOSI, SCLK, CS, MISO
#   ja_OBUF[3:0]   gpio_out, what the core drives
#   gpio_oe[3:0]   which pads the core drives; pin 3 (MISO) is released by the SPI programs
#   led*_OBUF      host_rdata, what the LEDs show
#   reset, host_we, host_re
set root [file normalize [file join [file dirname [info script]] .. ..]]
set out  [file join $root build pynq_z2_ila]
file mkdir $out

read_verilog [list \
    [file join $root fpga pynq_z2 smallcore_pynq.v] \
    [file join $root rtl smallcore.v] \
    [file join $root rtl host.v] \
    [file join $root rtl rom.v] \
    [file join $root rtl ram.v] \
    [file join $root rtl top.v] \
    [file join $root rtl core.v] \
    [file join $root rtl fifo.v]]
read_xdc [file join $root fpga pynq_z2 pynq_z2.xdc]

# hierarchy kept so the smallcore_i port nets can be found by name
synth_design -top smallcore_pynq -part xc7z020clg400-1 -flatten_hierarchy none

proc nets {pat} {
    set n [get_nets -quiet $pat]
    if {[llength $n] == 0} { set n [get_nets -quiet -of_objects [get_pins -quiet smallcore_i/$pat]] }
    if {[llength $n] == 0} { error "no nets for $pat" }
    return [lsort -dictionary $n]
}

create_debug_core u_ila_0 ila
set_property C_DATA_DEPTH 4096 [get_debug_cores u_ila_0]
set_property C_INPUT_PIPE_STAGES 0 [get_debug_cores u_ila_0]
set_property C_TRIGIN_EN false [get_debug_cores u_ila_0]
set_property C_ADV_TRIGGER false [get_debug_cores u_ila_0]
set_property port_width 1 [get_debug_ports u_ila_0/clk]
connect_debug_port u_ila_0/clk [get_nets clk]

set first 1
foreach pat {gpio_in[*] gpio_out[*] gpio_oe[*] host_rdata[*] reset host_we host_re} {
    set ns [nets $pat]
    if {$first} {
        set p u_ila_0/probe0
        set first 0
    } else {
        create_debug_port u_ila_0 probe
        set p [lindex [get_debug_ports u_ila_0/probe*] end]
    }
    set_property port_width [llength $ns] [get_debug_ports $p]
    connect_debug_port $p $ns
}
implement_debug_core

opt_design
place_design
route_design
report_timing_summary -file [file join $out timing_summary.rpt]
write_bitstream -force [file join $out smallcore_pynq_ila.bit]
write_debug_probes -force [file join $out smallcore_pynq_ila.ltx]
