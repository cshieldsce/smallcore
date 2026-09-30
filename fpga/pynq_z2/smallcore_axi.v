// SmallCore behind the AXI bridge: axi_host.v, the gated core clock and
// rtl/smallcore.v, unchanged. The pads stay split into gpio_in, gpio_out and
// gpio_oe for the board top (IOBUFs) and the simulation bench (a pad model).
// core_clk is aclk with one edge every CLKDIV cycles: a BUFGCE on the board;
// in simulation a latch on the low phase and an AND, the BUFGCE's behaviour.
//
// Simulation twin: tests/rtl/test_pynq_axi.py drives the AXI port from the
// same Python driver the board uses, fpga/pynq_z2/smallcore.py.
module smallcore_axi #(
    parameter STROBE_HIGH  = 6,
    parameter STROBE_LOW   = 4,
    parameter RESET_CLOCKS = 4,
    parameter CLKDIV_RESET = 4
) (
    input         aclk,
    input         aresetn,

    input  [5:0]  s_axi_awaddr,
    input  [2:0]  s_axi_awprot,
    input         s_axi_awvalid,
    output        s_axi_awready,
    input  [31:0] s_axi_wdata,
    input  [3:0]  s_axi_wstrb,
    input         s_axi_wvalid,
    output        s_axi_wready,
    output [1:0]  s_axi_bresp,
    output        s_axi_bvalid,
    input         s_axi_bready,
    input  [5:0]  s_axi_araddr,
    input  [2:0]  s_axi_arprot,
    input         s_axi_arvalid,
    output        s_axi_arready,
    output [31:0] s_axi_rdata,
    output [1:0]  s_axi_rresp,
    output        s_axi_rvalid,
    input         s_axi_rready,

    input  [3:0]  gpio_in,
    output [3:0]  gpio_out,
    output [3:0]  gpio_oe,

    // for the ILA and the LEDs
    output        core_clk,
    output        core_ce,
    output        core_reset,
    output [7:0]  host_wdata,
    output [1:0]  host_addr,
    output        host_we,
    output        host_re,
    output [7:0]  host_rdata
);

    axi_host #(
        .STROBE_HIGH  (STROBE_HIGH),
        .STROBE_LOW   (STROBE_LOW),
        .RESET_CLOCKS (RESET_CLOCKS),
        .CLKDIV_RESET (CLKDIV_RESET)
    ) axi_host_i (
        .aclk          (aclk),
        .aresetn       (aresetn),
        .s_axi_awaddr  (s_axi_awaddr),
        .s_axi_awprot  (s_axi_awprot),
        .s_axi_awvalid (s_axi_awvalid),
        .s_axi_awready (s_axi_awready),
        .s_axi_wdata   (s_axi_wdata),
        .s_axi_wstrb   (s_axi_wstrb),
        .s_axi_wvalid  (s_axi_wvalid),
        .s_axi_wready  (s_axi_wready),
        .s_axi_bresp   (s_axi_bresp),
        .s_axi_bvalid  (s_axi_bvalid),
        .s_axi_bready  (s_axi_bready),
        .s_axi_araddr  (s_axi_araddr),
        .s_axi_arprot  (s_axi_arprot),
        .s_axi_arvalid (s_axi_arvalid),
        .s_axi_arready (s_axi_arready),
        .s_axi_rdata   (s_axi_rdata),
        .s_axi_rresp   (s_axi_rresp),
        .s_axi_rvalid  (s_axi_rvalid),
        .s_axi_rready  (s_axi_rready),
        .core_ce       (core_ce),
        .core_reset    (core_reset),
        .host_wdata    (host_wdata),
        .host_addr     (host_addr),
        .host_we       (host_we),
        .host_re       (host_re),
        .host_rdata    (host_rdata),
        .gpio_in       (gpio_in),
        .gpio_out      (gpio_out),
        .gpio_oe       (gpio_oe)
    );

`ifdef VERILATOR
    reg ce_q = 1'b1;
    always @(negedge aclk) ce_q <= core_ce;
    assign core_clk = aclk & ce_q;
`else
    BUFGCE bufgce_i (.I(aclk), .CE(core_ce), .O(core_clk));
`endif

    smallcore smallcore_i (
        .clk        (core_clk),
        .reset      (core_reset),
        .host_wdata (host_wdata),
        .host_addr  (host_addr),
        .host_we    (host_we),
        .host_re    (host_re),
        .host_rdata (host_rdata),
        .gpio_in    (gpio_in),
        .gpio_out   (gpio_out),
        .gpio_oe    (gpio_oe)
    );

endmodule
