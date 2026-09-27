/*
 * Tiny Tapeout wrapper for SmallCore. Elaboration only.
 * SPDX-License-Identifier: Apache-2.0
 *
 * This wrapper exists so the IHP CMOS5L flow can synthesize and place
 * rtl/top.v (core plus TX and RX FIFOs) as it stands. It is NOT the pin
 * mapping and NOT the host interface: top has 39 input bits and 26 output
 * bits against Tiny Tapeout's 16 and 16, so inputs share pins and outputs
 * are folded together below. Every output reaches a pin so synthesis keeps
 * the logic behind it. Program loading and the FIFO host side are
 * unresolved and are not decided here.
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
  wire [3:0] gpio_oe;
  wire [7:0] rx_data;
  wire       tx_full;
  wire       rx_empty;

  top top_i (
      .clk           (clk),
      .reset         (!rst_n),           // TT reset is active low, top's is active high
      // PROVISIONAL, elaboration only: keeps every top input driven by a pin
      .imem_word     ({uio_in, ui_in}),  // 16-bit instruction word
      .program_words ({ui_in[1], uio_in}),
      .gpio_in       (ui_in[7:4]),
      .tx_data       (ui_in),
      .tx_push       (ui_in[2]),
      .rx_pop        (ui_in[3]),
      .tx_full       (tx_full),
      .rx_data       (rx_data),
      .rx_empty      (rx_empty),
      .imem_addr     (imem_addr),
      .gpio_out      (gpio_out),
      .gpio_oe       (gpio_oe)
  );

  assign uo_out  = imem_addr;
  // PROVISIONAL: uio[7:4] are inputs, but their output path is still a port, so folding the host-side
  // outputs into it keeps them in the netlist. The parity of each rx_data nibble depends on every bit.
  assign uio_out = {gpio_oe ^ {tx_full, rx_empty, ^rx_data[7:4], ^rx_data[3:0]}, gpio_out};
  assign uio_oe  = 8'b0000_1111;        // gpio_out drives uio[3:0]; the open-drain gpio_oe comes later

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, 1'b0};

endmodule
