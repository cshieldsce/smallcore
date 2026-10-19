# Run a bare-metal program on the Zynq's Cortex-A9 core 0 over JTAG: reset the system, load the
# PL bitstream, initialise the PS from the hardware platform's ps7_init.tcl (clocks, MIO, DDR,
# then the PS-to-PL level shifters and FCLK reset in ps7_post_config), load the ELF into OCM, run.
# Batch: xsdb run_arm.tcl <ps7_init.tcl> <bit> <elf> [result_addr] [seconds] [addr value] [exc_addr]
#   ps7_init.tcl is the one inside the hardware platform .xsa (a zip).
#   With result_addr, waits up to `seconds` (default 3) for the program's 4-word `result` array
#   to hold a verdict in word 0, and prints it. Before loading the ELF it also reads the peripheral's ID and VERSION from the
#   A9's view of the bus (the debugger's loads go out through the core), the XSCT-level check.
#   addr value: a word written into the loaded program before it runs (test_host.c's `tests`);
#   or several as one argument, addr:value+addr:value, with value "-" (cmd.exe, which runs xsdb.bat,
#   splits arguments at "=" and ",").
#   exc_addr: uart.c's exception_seen, which also ends the wait and is printed (build.py
#   prints both addresses).
lassign $argv ps7init bit elf result_addr seconds set_addr set_value exc_addr
if {$seconds eq ""} { set seconds 3 }

connect
targets -set -nocase -filter {name =~ "APU*"}
rst -system
after 500
fpga -file $bit
puts "RESULT fpga programmed"

targets -set -nocase -filter {name =~ "*Cortex-A9*#0"}
catch {stop}
# xsdb blocks the PL's address range (0x4000_0000..0xBFFF_FFFF) unless a hardware design is
# loaded (loadhw, XSCT only) or the check is off
configparams force-mem-accesses 1
source $ps7init
ps7_init
ps7_post_config
puts "RESULT ps7_init done"

puts "RESULT xsdb ID=[format 0x%08X [mrd -value 0x43C00000]] VERSION=[format 0x%08X [mrd -value 0x43C00004]]"

dow $elf
if {[string first : $set_addr] >= 0} {
    foreach pair [split $set_addr +] { lassign [split $pair :] a w; mwr $a $w }
} elseif {$set_addr ne ""} { mwr $set_addr $set_value }
con
# with result_addr, look once a second, up to `seconds`, for the program's verdict in result[0]
set end [expr {[clock milliseconds] + int($seconds * 1000)}]
while {[clock milliseconds] < $end} {
    after 1000
    if {$result_addr eq ""} continue
    catch {stop}
    set done [mrd -value $result_addr]
    if {$exc_addr ne "" && [mrd -value $exc_addr] != 0} { set done 1 }
    if {$done != 0} break
    con
}
catch {stop}
if {$result_addr ne ""} {
    set r [mrd -value $result_addr 4]
    set words {}
    foreach w $r { lappend words [format 0x%08X $w] }
    puts "RESULT words $words"
    if {$exc_addr ne ""} {
        set e {}
        foreach w [mrd -value $exc_addr 3] { lappend e [format 0x%08X $w] }
        puts "RESULT exception $e"
    }
}
disconnect
