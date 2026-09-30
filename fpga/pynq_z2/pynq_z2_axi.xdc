## PYNQ-Z2 constraints for fpga/pynq_z2/smallcore_pynq_axi.v, the ARM-hosted build.
## The clock is the PS's FCLK_CLK0, constrained by the PS7's own XDC; the core clock is
## a BUFGCE on it, the same clock to the timer. Pins as in pynq_z2.xdc (the button build).

## LEDs: LD0..LD3 the pad levels
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

## PMOD A, pins 1..4 = gpio 0..3. SPI: MOSI, SCLK, CS, MISO. I2C: SDA, SCL.
## The weak pull-ups hold a released line high: I2C with nothing attached, MISO with no jumper.
## They are weak (tens of kilohms): with a real I2C device, use the board's or the module's pull-ups.
set_property -dict { PACKAGE_PIN Y18 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {ja[0]}]
set_property -dict { PACKAGE_PIN Y19 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {ja[1]}]
set_property -dict { PACKAGE_PIN Y16 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {ja[2]}]
set_property -dict { PACKAGE_PIN Y17 IOSTANDARD LVCMOS33 PULLUP true } [get_ports {ja[3]}]

## The pads are asynchronous to aclk; nothing times them. The core samples gpio_in directly,
## as the chip does; at CLKDIV >= 2 a pad has a whole aclk cycle and more to settle.
set_false_path -to [get_ports {ja[*] led* }]
set_false_path -from [get_ports {ja[*]}]
