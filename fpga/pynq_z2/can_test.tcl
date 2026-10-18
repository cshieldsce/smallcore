# The two hardware CAN tests on smallcore_pynq_can.v, with captures for can_decode.py.
# Batch: vivado -mode batch -source C:/core/fpga/pynq_z2/can_test.tcl -tclargs tx|rx [CORE_DIV] [noprogram]
#   tx  slot 13 sends 0x123 [5A]; prints acked 1 when the other node ACKed. Run a CAN node on the
#       bus at 1 Mbit/s / CORE_DIV (125 kbit/s for the default 8), e.g.
#       cantap capture candor:<SERIAL>:ch0 --bitrate 125000 --duration 60
#   rx  slot 15 (can_rx_bytes) listens; within a minute of RESULT armed, send 0x123 [5A], e.g.
#       cantap send candor:<SERIAL>:ch0 --bitrate 125000 --id 123 --data 5A
#       The RX buffer should read 18 48 43 65 38 1 (12 30 2B 41 26 01).
# Captures land in build/pynq_z2_can/<tx|rx>_core.csv (8 MHz) and <tx|rx>_loop.csv (125 MHz):
#   python fpga/pynq_z2/can_decode.py tx build/pynq_z2_can/tx_core.csv 123 5A --loop build/pynq_z2_can/tx_loop.csv --div 8
#   python fpga/pynq_z2/can_decode.py bus build/pynq_z2_can/rx_core.csv --div 8
# Build first with build_can.tcl -tclargs CORE_DIV.
source [file join [file dirname [info script]] can_host.tcl]

set mode    [lindex $argv 0]
set div     [expr {[llength $argv] > 1 ? [lindex $argv 1] : 8}]
set program [expr {[lsearch -exact $argv noprogram] < 0}]
set core    [file join $sc_out ${mode}_core.csv]
set loop    [file join $sc_out ${mode}_loop.csv]

sc_open $div $program
puts "RESULT locked=[sc_in locked] CORE_DIV=$div"

if {$mode eq "tx"} {
    sc_arm sc_ila can_ctx_OBUF 64
    sc_arm sc_loop ctx_f 256
    set r [can_tx 0x123 {0x5A}]
    puts "RESULT acked=[dict get $r acked] status=[dict get $r status] post-ACK byte=[dict get $r rx]"
} elseif {$mode eq "rx"} {
    can_rx_start 15
    sc_arm sc_ila crx_s 64
    sc_arm sc_loop crx_f 256
    puts "RESULT armed: send 0x123 \[5A\] within a minute"
    flush stdout
} else {
    error "mode is tx or rx"
}

puts "RESULT ila=[sc_save sc_ila $core 1] loop=[sc_save sc_loop $loop 1]"
if {$mode eq "rx"} {
    puts "RESULT status=[sc_status] rx=[sc_rx_read]"
}
