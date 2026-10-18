# Loads the ILA build, triggers on CS falling (the start of an SPI frame) and writes the
# capture to build/pynq_z2_ila/capture.csv. Press BTN3, BTN0, BTN1 once it prints ARMED.
# Batch: vivado -mode batch -source C:/core/fpga/pynq_z2/ila_capture.tcl
# Decode: python fpga/pynq_z2/decode_capture.py
# Run build_ila.tcl first.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set out  [file join $root build pynq_z2_ila]

open_hw_manager
connect_hw_server
open_hw_target
set dev [lindex [get_hw_devices xc7z020_1] 0]
current_hw_device $dev
set_property PROGRAM.FILE [file join $out smallcore_pynq_ila.bit] $dev
set_property PROBES.FILE [file join $out smallcore_pynq_ila.ltx] $dev
set_property FULL_PROBES.FILE [file join $out smallcore_pynq_ila.ltx] $dev
program_hw_devices $dev
refresh_hw_device $dev

set ila [lindex [get_hw_ilas -of_objects $dev] 0]
set_property CONTROL.DATA_DEPTH 4096 $ila
set_property CONTROL.TRIGGER_POSITION 256 $ila
# gpio_out[2] is CS; the core holds it high out of reset
set_property TRIGGER_COMPARE_VALUE eq4'bX0XX [get_hw_probes ja_OBUF -of_objects $ila]
run_hw_ila $ila
puts "ARMED"
flush stdout

wait_on_hw_ila -timeout 5 $ila
if {[get_property STATUS.CORE_STATUS $ila] ne "FULL"} {
    puts "TIMEOUT: no CS falling edge within 5 minutes, nothing captured"
} else {
    write_hw_ila_data -force -csv_file [file join $out capture.csv] [upload_hw_ila_data $ila]
    puts "CAPTURED: [file join $out capture.csv]"
}

close_hw_target
disconnect_hw_server
close_hw_manager
