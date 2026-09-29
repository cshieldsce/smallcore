/*
 * Tiny Tapeout wrapper for SmallCore, rtl/smallcore.v: the host register
 * bus on ui/uo and uio[7:4], the four protocol pads on uio[3:0].
 * SPDX-License-Identifier: Apache-2.0
 *
 *   ui[7:0]   host_wdata         uo[7:0]  host_rdata
 *   uio[5:4]  host_addr (in)     uio[6]   host_we (in)     uio[7]  host_re (in)
 *   uio[3:0]  gpio 3..0: out = gpio_out, oe = gpio_oe, in = gpio_in
 *
 * Registers, on host_addr: 0 TX_DATA (write pushes), 1 RX_DATA (read; re pops),
 * 2 STATUS {halted, tx_full, rx_empty}, 3 CONTROL (write selects a program slot
 * and restarts the core). See rtl/host.v and the repository README.
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

  wire [3:0] gpio_out;
  wire [3:0] gpio_oe;

  smallcore smallcore_i (
      .clk        (clk),
      .reset      (!rst_n),      // TT reset is active low, smallcore's is active high
      .host_wdata (ui_in),
      .host_addr  (uio_in[5:4]),
      .host_we    (uio_in[6]),
      .host_re    (uio_in[7]),
      .host_rdata (uo_out),
      .gpio_in    (uio_in[3:0]),
      .gpio_out   (gpio_out),
      .gpio_oe    (gpio_oe)
  );

  assign uio_out = {4'b0000, gpio_out};
  assign uio_oe  = {4'b0000, gpio_oe};  // uio[7:4] stay inputs: the host's addr and strobes

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, 1'b0};

endmodule
