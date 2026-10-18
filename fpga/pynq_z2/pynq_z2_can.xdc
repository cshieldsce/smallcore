## PYNQ-Z2 constraints for fpga/pynq_z2/smallcore_pynq_can.v. The MMCM derives the 8 MHz core clock.

set_property -dict { PACKAGE_PIN H16 IOSTANDARD LVCMOS33 } [get_ports sysclk]
create_clock -add -name sys_clk_pin -period 8.00 -waveform {0 4} [get_ports sysclk]

## LEDs: LD0 locked, LD1 bus dominant, LD2 halted, LD3 reset
set_property -dict { PACKAGE_PIN R14 IOSTANDARD LVCMOS33 } [get_ports {led[0]}]
set_property -dict { PACKAGE_PIN P14 IOSTANDARD LVCMOS33 } [get_ports {led[1]}]
set_property -dict { PACKAGE_PIN N16 IOSTANDARD LVCMOS33 } [get_ports {led[2]}]
set_property -dict { PACKAGE_PIN M14 IOSTANDARD LVCMOS33 } [get_ports {led[3]}]

## PMOD A: pin 1 CTX, pin 2 CRX (pulled up: recessive with no transceiver), pins 3, 4, 7 gpio 1..3
set_property -dict { PACKAGE_PIN Y18 IOSTANDARD LVCMOS33 } [get_ports can_ctx]
set_property -dict { PACKAGE_PIN Y19 IOSTANDARD LVCMOS33 PULLUP true } [get_ports can_crx]
set_property -dict { PACKAGE_PIN Y16 IOSTANDARD LVCMOS33 } [get_ports {ja_gpio[0]}]
set_property -dict { PACKAGE_PIN Y17 IOSTANDARD LVCMOS33 } [get_ports {ja_gpio[1]}]
set_property -dict { PACKAGE_PIN U18 IOSTANDARD LVCMOS33 } [get_ports {ja_gpio[2]}]

## CRX is asynchronous, sampled through one flop
set_false_path -from [get_ports can_crx]
## ila_loop samples CTX, a core-clock signal, on sysclk: observation only
set_false_path -to [get_cells -hierarchical ctx_f_reg]

set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
