# The host for smallcore_pynq_can.v: can_host_engine.v's commands through the VIO over JTAG.
# Source it from a Vivado Tcl session or a batch script, then sc_open:
#   source C:/core/fpga/pynq_z2/can_host.tcl
#   sc_open 8                        ;# programs build/pynq_z2_can/*_div8 (125 kbit/s), finds the VIO and ILAs
#   can_tx 0x123 {0x5A}              ;# slot 13: {acked 1 status ... rx {..}}
#   can_rx_start 14 ; ... ; can_rx_read
#
# The VIO is slow (milliseconds a commit); the engine does every bus
# transaction at the core clock: the TX bytes go into a 32-byte buffer first,
# the RX FIFO drains into a 256-byte buffer read back here at leisure.
# Each engine command is a rising edge on its VIO output.
set sc_root [file normalize [file join [file dirname [info script]] .. ..]]
set sc_out  [file join $sc_root build pynq_z2_can]

proc sc_open {{div 8} {program 1}} {
    global sc_out sc_dev sc_vio sc_ila sc_loop
    open_hw_manager
    connect_hw_server
    open_hw_target
    set sc_dev [lindex [get_hw_devices xc7z020_1] 0]
    current_hw_device $sc_dev
    set_property PROBES.FILE      [file join $sc_out smallcore_pynq_can_div$div.ltx] $sc_dev
    set_property FULL_PROBES.FILE [file join $sc_out smallcore_pynq_can_div$div.ltx] $sc_dev
    if {$program} {
        set_property PROGRAM.FILE [file join $sc_out smallcore_pynq_can_div$div.bit] $sc_dev
        program_hw_devices $sc_dev
    }
    refresh_hw_device $sc_dev
    set sc_vio  [lindex [get_hw_vios -of_objects $sc_dev] 0]
    set sc_ila  [get_hw_ilas -of_objects $sc_dev -filter {CELL_NAME =~ "*ila_i*"}]
    set sc_loop [get_hw_ilas -of_objects $sc_dev -filter {CELL_NAME =~ "*ila_loop*"}]
    foreach p [get_hw_probes -of_objects $sc_vio] {
        catch {set_property INPUT_VALUE_RADIX UNSIGNED $p}
        catch {set_property OUTPUT_VALUE_RADIX UNSIGNED $p}
    }
    set_property OUTPUT_VALUE_RADIX HEX [sc_probe vo_txbuf]
    foreach n {vo_we vo_re vo_rst vo_manual vo_txgo vo_rungo vo_rxen vo_rxclr} { sc_set $n 0 }
    sc_commit
    if {[sc_in locked] != 1} { error "MMCM not locked" }
}

proc sc_probe {name} {
    global sc_vio
    set p [get_hw_probes -of_objects $sc_vio -filter "NAME == $name"]
    if {[llength $p] != 1} { error "VIO probe $name: [llength $p] matches" }
    return $p
}

proc sc_set {name value} { set_property OUTPUT_VALUE $value [sc_probe $name] }
proc sc_commit {} { global sc_vio; commit_hw_vio $sc_vio }
proc sc_out {name value} { sc_set $name $value; sc_commit }

proc sc_in {name} {
    global sc_vio
    refresh_hw_vio $sc_vio
    return [get_property INPUT_VALUE [sc_probe $name]]
}

# an engine command: a rising edge on its VIO output
proc sc_pulse {name} { sc_out $name 0; sc_out $name 1; sc_out $name 0 }

# hard reset: core, FIFOs, slot 0; the engine's strobes held low through it
proc sc_reset {} { sc_pulse vo_rst }

# STATUS as the engine last read it: halted, tx_full, rx_empty
proc sc_status {} {
    set s [sc_in eng_status]
    return [dict create halted [expr {($s >> 2) & 1}] tx_full [expr {($s >> 1) & 1}] rx_empty [expr {$s & 1}]]
}

proc sc_engine {} {
    global sc_vio
    refresh_hw_vio $sc_vio
    set d [dict create]
    foreach n {eng_state eng_status eng_txidx eng_txactive eng_rxcount eng_rxovf} {
        dict set d $n [get_property INPUT_VALUE [sc_probe $n]]
    }
    return $d
}

# up to 32 bytes into the engine's TX buffer, then tx_go pushes them as space allows
proc sc_tx_load {bytes} {
    if {[llength $bytes] > 32} { error "32 bytes at most" }
    set hex ""
    for {set i 31} {$i >= 0} {incr i -1} {
        append hex [format %02X [expr {$i < [llength $bytes] ? [lindex $bytes $i] : 0}]]
    }
    sc_set vo_txbuf $hex
    sc_set vo_txlen [llength $bytes]
    sc_commit
}
proc sc_tx_go {} { sc_pulse vo_txgo }

# CONTROL = slot through the engine, in its turn with the TX pushes
proc sc_run {slot} { sc_set vo_slot $slot; sc_commit; sc_pulse vo_rungo }

proc sc_rx_enable {on} { sc_out vo_rxen $on }
proc sc_rx_clear {} { sc_pulse vo_rxclr }

# the engine's RX buffer, every byte captured since the last clear
proc sc_rx_read {} {
    global sc_vio
    set n [sc_in eng_rxcount]
    set bytes {}
    for {set i 0} {$i < $n && $i < 256} {incr i} {
        sc_out vo_rxidx $i
        refresh_hw_vio $sc_vio
        lappend bytes [get_property INPUT_VALUE [sc_probe eng_rxbyte]]
    }
    return $bytes
}

# The three header bytes can_tx_crc.asm takes, base frame:
# {SOF, ID[10], ID[9], 00000}, ID[8:1], {ID[0], RTR, IDE, r0, DLC[3:0]}
proc can_header {id dlc {rtr 0}} {
    set id [expr {$id & 0x7FF}]
    return [list \
        [expr {(($id >> 9) & 3) << 5}] \
        [expr {($id >> 1) & 0xFF}] \
        [expr {(($id & 1) << 7) | ($rtr << 6) | ($dlc & 0xF)}]]
}

set CAN_POLY {0x32 0x8B}

# One base frame by slot 13, can_tx_crc (DLC 1, as the ROM's CAN programs).
# The TX FIFO is filled before RUN, the rest pushed as the program PULLs.
# Acked: the program halts. Returns {acked 0|1 status {...} rx {bytes}}: rx holds
# the program's PUSH after the ACK slot, {the last seven samples, ACK}.
proc can_tx {id data {timeout_ms 300}} {
    global CAN_POLY
    sc_reset
    sc_rx_clear
    sc_rx_enable 1
    sc_tx_load [concat $CAN_POLY [can_header $id [llength $data]] $data]
    sc_tx_go
    after 5
    sc_run 13
    set t [expr {[clock milliseconds] + $timeout_ms}]
    set acked 0
    while {[clock milliseconds] < $t} {
        if {[dict get [sc_status] halted]} { set acked 1; break }
    }
    return [dict create acked $acked status [sc_status] engine [sc_engine] rx [sc_rx_read]]
}

# Start a receiver: 15 can_rx_bytes (6 destuffed bytes), 14 can_rx_crc (42 bits + residue),
# both DLC 1 and both pulling the ACK.
proc can_rx_start {slot} {
    global CAN_POLY
    sc_reset
    sc_rx_clear
    sc_rx_enable 1
    if {$slot == 14} {
        sc_tx_load $CAN_POLY
        sc_tx_go
        after 5
    }
    sc_run $slot
}

# Arm an ILA: `which` sc_ila (core clock) or sc_loop (125 MHz); trigger on `probe` == 0
proc sc_arm {which probe {position 512}} {
    upvar #0 $which ila
    set_property CONTROL.TRIGGER_POSITION $position $ila
    foreach p [get_hw_probes -of_objects $ila] {
        set w [get_property WIDTH $p]
        set_property TRIGGER_COMPARE_VALUE "eq${w}'b[string repeat X $w]" $p
    }
    set_property TRIGGER_COMPARE_VALUE eq1'b0 [get_hw_probes $probe -of_objects $ila]
    run_hw_ila $ila
}

proc sc_save {which csv {timeout_min 1}} {
    upvar #0 $which ila
    wait_on_hw_ila -timeout $timeout_min $ila
    if {[get_property STATUS.CORE_STATUS $ila] ne "FULL"} { return 0 }
    write_hw_ila_data -force -csv_file $csv [upload_hw_ila_data $ila]
    return 1
}
