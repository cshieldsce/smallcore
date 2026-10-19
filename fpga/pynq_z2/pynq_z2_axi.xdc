## PYNQ-Z2 constraints for fpga/pynq_z2/smallcore_pynq_axi.v. The MMCM derives the core clock;
## the PS7's FCLK0 and the AXI clock converter's crossing are constrained by their IP.

set_property -dict { PACKAGE_PIN H16 IOSTANDARD LVCMOS33 } [get_ports sysclk]
create_clock -add -name sys_clk_pin -period 8.00 -waveform {0 4} [get_ports sysclk]

## LEDs: LD0 locked, LD1 bus dominant, LD2 halted, LD3 core reset
set_property -dict { PACKAGE_PIN R14 IOSTANDARD LVCMOS33 } [get_ports {led[0]}]
set_property -dict { PACKAGE_PIN P14 IOSTANDARD LVCMOS33 } [get_ports {led[1]}]
set_property -dict { PACKAGE_PIN N16 IOSTANDARD LVCMOS33 } [get_ports {led[2]}]
set_property -dict { PACKAGE_PIN M14 IOSTANDARD LVCMOS33 } [get_ports {led[3]}]

## PMOD A, the CAN transceiver: pin 1 CTX, pin 2 CRX (pulled up: recessive with no transceiver),
## pins 3, 4, 7 inputs
set_property -dict { PACKAGE_PIN Y18 IOSTANDARD LVCMOS33 } [get_ports can_ctx]
set_property -dict { PACKAGE_PIN Y19 IOSTANDARD LVCMOS33 PULLUP true } [get_ports can_crx]
set_property -dict { PACKAGE_PIN Y16 IOSTANDARD LVCMOS33 } [get_ports {ja_gpio[0]}]
set_property -dict { PACKAGE_PIN Y17 IOSTANDARD LVCMOS33 } [get_ports {ja_gpio[1]}]
set_property -dict { PACKAGE_PIN U18 IOSTANDARD LVCMOS33 } [get_ports {ja_gpio[2]}]

## PMOD B pins 1..4: the four GPIOs with CTRL[2] = 1, pulled up so a released pin reads 1
## (pins from the PYNQ v3.0.1 base overlay's base.xdc)
set_property -dict { PACKAGE_PIN W14 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {jb[0]}]
set_property -dict { PACKAGE_PIN Y14 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {jb[1]}]
set_property -dict { PACKAGE_PIN T11 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {jb[2]}]
set_property -dict { PACKAGE_PIN T10 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {jb[3]}]

## CRX, PMOD A's inputs and PMOD B are asynchronous, each sampled through one flop
set_false_path -from [get_ports {can_crx ja_gpio[*] jb[*]}]

set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
