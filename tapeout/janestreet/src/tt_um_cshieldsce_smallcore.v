/*
 * Tiny Tapeout wrapper for SmallCore. Elaboration only.
 * SPDX-License-Identifier: Apache-2.0
 *
 * This wrapper exists so the IHP CMOS5L flow can synthesize and place
 * rtl/core.v as it stands. It is NOT the pin mapping and NOT the host
 * interface: the core has 31 input bits and Tiny Tapeout has 16, so
 * several core inputs share a pin below. Program loading and the FIFO
 * host side are unresolved and are not decided here.
 */

`default_nettype none

module tt_um_cshieldsce_smallcore (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire [7:0] imem_addr;
  wire [3:0] gpio_out;

  core core_i (
      .clk           (clk),
      .reset         (!rst_n),           // TT reset is active low, the core's is active high
      // PROVISIONAL, elaboration only: keeps every core input driven by a pin
      .imem_word     ({uio_in, ui_in}),  // 16-bit instruction word
      .program_words ({ui_in[1], uio_in}),
      .gpio_in       (ui_in[7:4]),
      .tx_empty      (ui_in[1]),
      .rx_full       (ui_in[4]),
      .imem_addr     (imem_addr),
      .gpio_out      (gpio_out)
  );

  assign uo_out  = imem_addr;
  assign uio_out = {4'b0000, gpio_out};
  assign uio_oe  = 8'b0000_1111;        // gpio_out drives uio[3:0]; the open-drain gpio_oe comes later

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, 1'b0};

endmodule
