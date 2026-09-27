## PYNQ-Z2 constraints for fpga/pynq_z2/smallcore_pynq.v.
## Pins as in the PYNQ base overlay's base.xdc (switches, buttons, LEDs, RGB LEDs, PMOD A) and the
## TUL pynq-z2_v1.0 master XDC (the 125 MHz clock on H16). Check against your board's master XDC.

## 125 MHz from the Ethernet PHY
set_property -dict { PACKAGE_PIN H16 IOSTANDARD LVCMOS33 } [get_ports sysclk]
create_clock -add -name sys_clk_pin -period 8.00 -waveform {0 4} [get_ports sysclk]
## The core clock is div[1] through a BUFG, sysclk / 4; without this Vivado leaves every smallcore path unconstrained
create_generated_clock -name core_clk -source [get_pins {div_reg[1]/C}] -divide_by 4 [get_pins {div_reg[1]/Q}]

## Switches
set_property -dict { PACKAGE_PIN M20 IOSTANDARD LVCMOS33 } [get_ports {sw[0]}]
set_property -dict { PACKAGE_PIN M19 IOSTANDARD LVCMOS33 } [get_ports {sw[1]}]

## Buttons
set_property -dict { PACKAGE_PIN D19 IOSTANDARD LVCMOS33 } [get_ports {btn[0]}]
set_property -dict { PACKAGE_PIN D20 IOSTANDARD LVCMOS33 } [get_ports {btn[1]}]
set_property -dict { PACKAGE_PIN L20 IOSTANDARD LVCMOS33 } [get_ports {btn[2]}]
set_property -dict { PACKAGE_PIN L19 IOSTANDARD LVCMOS33 } [get_ports {btn[3]}]

## LEDs
set_property -dict { PACKAGE_PIN R14 IOSTANDARD LVCMOS33 } [get_ports {led[0]}]
set_property -dict { PACKAGE_PIN P14 IOSTANDARD LVCMOS33 } [get_ports {led[1]}]
set_property -dict { PACKAGE_PIN N16 IOSTANDARD LVCMOS33 } [get_ports {led[2]}]
set_property -dict { PACKAGE_PIN M14 IOSTANDARD LVCMOS33 } [get_ports {led[3]}]

## RGB LEDs
set_property -dict { PACKAGE_PIN N15 IOSTANDARD LVCMOS33 } [get_ports led4_r]
set_property -dict { PACKAGE_PIN G17 IOSTANDARD LVCMOS33 } [get_ports led4_g]
set_property -dict { PACKAGE_PIN L15 IOSTANDARD LVCMOS33 } [get_ports led4_b]
set_property -dict { PACKAGE_PIN M15 IOSTANDARD LVCMOS33 } [get_ports led5_r]
set_property -dict { PACKAGE_PIN L14 IOSTANDARD LVCMOS33 } [get_ports led5_g]
set_property -dict { PACKAGE_PIN G14 IOSTANDARD LVCMOS33 } [get_ports led5_b]

## PMOD A, pins 1..4: gpio 0 MOSI, 1 SCLK, 2 CS, 3 MISO. Jumper pin 1 to pin 4 for the loopback.
set_property -dict { PACKAGE_PIN Y18 IOSTANDARD LVCMOS33 } [get_ports {ja[0]}]
set_property -dict { PACKAGE_PIN Y19 IOSTANDARD LVCMOS33 } [get_ports {ja[1]}]
set_property -dict { PACKAGE_PIN Y16 IOSTANDARD LVCMOS33 } [get_ports {ja[2]}]
set_property -dict { PACKAGE_PIN Y17 IOSTANDARD LVCMOS33 } [get_ports {ja[3]}]

set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
