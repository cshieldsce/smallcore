// PYNQ-Z2 top for SmallCore with the Zynq's ARM as its host. The block
// design `system` (create_project_axi.tcl) is the PS7, FCLK_CLK0 at 100 MHz,
// its reset and a SmartConnect out to the M_AXI port; everything else is
// here in RTL: the bridge and SmallCore (smallcore_axi.v), the pads, the
// LEDs and an ILA on the pads and the host bus.
//
//   PMOD A pins 1..4  gpio 0..3, IOBUFs; PULLUP in the XDC so an open-drain
//                     line (I2C) rests high with nothing on it
//   LD0..LD3          the pad levels, gpio_in: what the core drives, or what
//                     the outside does to a pin it has let go
//   LD4 green         SmallCore out of reset; LD4 blue: a transaction on the host bus
//   LD5 red           aclk heartbeat, about 1.5 Hz: the PL is clocked
//   ILA               ila_smallcore on aclk, 8192 samples: pads, gpio_out,
//                     gpio_oe, the host bus, core_ce, core_reset
//
// The Linux side: fpga/pynq_z2/smallcore.py, base address 0x43C00000.
module smallcore_pynq_axi (
    inout  [14:0] DDR_addr,
    inout  [2:0]  DDR_ba,
    inout         DDR_cas_n,
    inout         DDR_ck_n,
    inout         DDR_ck_p,
    inout         DDR_cke,
    inout         DDR_cs_n,
    inout  [3:0]  DDR_dm,
    inout  [31:0] DDR_dq,
    inout  [3:0]  DDR_dqs_n,
    inout  [3:0]  DDR_dqs_p,
    inout         DDR_odt,
    inout         DDR_ras_n,
    inout         DDR_reset_n,
    inout         DDR_we_n,
    inout         FIXED_IO_ddr_vrn,
    inout         FIXED_IO_ddr_vrp,
    inout  [53:0] FIXED_IO_mio,
    inout         FIXED_IO_ps_clk,
    inout         FIXED_IO_ps_porb,
    inout         FIXED_IO_ps_srstb,

    output [3:0]  led,
    output        led4_r, led4_g, led4_b,
    output        led5_r, led5_g, led5_b,
    inout  [3:0]  ja
);

    wire        aclk;
    wire [0:0]  aresetn;

    wire [31:0] awaddr, araddr, wdata, rdata;
    wire [2:0]  awprot, arprot;
    wire [3:0]  wstrb;
    wire [1:0]  bresp, rresp;
    wire        awvalid, awready, wvalid, wready, bvalid, bready;
    wire        arvalid, arready, rvalid, rready;

    system_wrapper system_i (
        .DDR_addr          (DDR_addr),
        .DDR_ba            (DDR_ba),
        .DDR_cas_n         (DDR_cas_n),
        .DDR_ck_n          (DDR_ck_n),
        .DDR_ck_p          (DDR_ck_p),
        .DDR_cke           (DDR_cke),
        .DDR_cs_n          (DDR_cs_n),
        .DDR_dm            (DDR_dm),
        .DDR_dq            (DDR_dq),
        .DDR_dqs_n         (DDR_dqs_n),
        .DDR_dqs_p         (DDR_dqs_p),
        .DDR_odt           (DDR_odt),
        .DDR_ras_n         (DDR_ras_n),
        .DDR_reset_n       (DDR_reset_n),
        .DDR_we_n          (DDR_we_n),
        .FIXED_IO_ddr_vrn  (FIXED_IO_ddr_vrn),
        .FIXED_IO_ddr_vrp  (FIXED_IO_ddr_vrp),
        .FIXED_IO_mio      (FIXED_IO_mio),
        .FIXED_IO_ps_clk   (FIXED_IO_ps_clk),
        .FIXED_IO_ps_porb  (FIXED_IO_ps_porb),
        .FIXED_IO_ps_srstb (FIXED_IO_ps_srstb),
        .aclk              (aclk),
        .aresetn           (aresetn),
        .M_AXI_araddr      (araddr),
        .M_AXI_arprot      (arprot),
        .M_AXI_arready     (arready),
        .M_AXI_arvalid     (arvalid),
        .M_AXI_awaddr      (awaddr),
        .M_AXI_awprot      (awprot),
        .M_AXI_awready     (awready),
        .M_AXI_awvalid     (awvalid),
        .M_AXI_bready      (bready),
        .M_AXI_bresp       (bresp),
        .M_AXI_bvalid      (bvalid),
        .M_AXI_rdata       (rdata),
        .M_AXI_rready      (rready),
        .M_AXI_rresp       (rresp),
        .M_AXI_rvalid      (rvalid),
        .M_AXI_wdata       (wdata),
        .M_AXI_wready      (wready),
        .M_AXI_wstrb       (wstrb),
        .M_AXI_wvalid      (wvalid)
    );

    wire [3:0] gpio_in, gpio_out, gpio_oe;
    wire       core_clk, core_ce, core_reset;
    wire [7:0] host_wdata, host_rdata;
    wire [1:0] host_addr;
    wire       host_we, host_re;

    smallcore_axi smallcore_axi_i (
        .aclk          (aclk),
        .aresetn       (aresetn[0]),
        .s_axi_awaddr  (awaddr[5:0]),
        .s_axi_awprot  (awprot),
        .s_axi_awvalid (awvalid),
        .s_axi_awready (awready),
        .s_axi_wdata   (wdata),
        .s_axi_wstrb   (wstrb),
        .s_axi_wvalid  (wvalid),
        .s_axi_wready  (wready),
        .s_axi_bresp   (bresp),
        .s_axi_bvalid  (bvalid),
        .s_axi_bready  (bready),
        .s_axi_araddr  (araddr[5:0]),
        .s_axi_arprot  (arprot),
        .s_axi_arvalid (arvalid),
        .s_axi_arready (arready),
        .s_axi_rdata   (rdata),
        .s_axi_rresp   (rresp),
        .s_axi_rvalid  (rvalid),
        .s_axi_rready  (rready),
        .gpio_in       (gpio_in),
        .gpio_out      (gpio_out),
        .gpio_oe       (gpio_oe),
        .core_clk      (core_clk),
        .core_ce       (core_ce),
        .core_reset    (core_reset),
        .host_wdata    (host_wdata),
        .host_addr     (host_addr),
        .host_we       (host_we),
        .host_re       (host_re),
        .host_rdata    (host_rdata)
    );

    // the pads: PMOD A pins 1..4 = ja[3:0]; T is active low enable
    genvar g;
    generate
        for (g = 0; g < 4; g = g + 1) begin : pads
            IOBUF iobuf_i (.I(gpio_out[g]), .T(!gpio_oe[g]), .O(gpio_in[g]), .IO(ja[g]));
        end
    endgenerate

    reg [25:0] heartbeat = 26'd0;
    always @(posedge aclk) heartbeat <= heartbeat + 26'd1;

    assign led    = gpio_in;
    assign led4_r = 1'b0;
    assign led4_g = !core_reset;
    assign led4_b = host_we | host_re;
    assign led5_r = heartbeat[25];
    assign led5_g = 1'b0;
    assign led5_b = 1'b0;

    ila_smallcore ila_i (
        .clk    (aclk),
        .probe0 (gpio_in),     // 4: the pads as the wire has them: MOSI SCLK CS MISO, or SDA SCL
        .probe1 (gpio_out),    // 4
        .probe2 (gpio_oe),     // 4
        .probe3 (host_addr),   // 2
        .probe4 (host_we),     // 1
        .probe5 (host_re),     // 1
        .probe6 (host_wdata),  // 8
        .probe7 (host_rdata),  // 8
        .probe8 (core_ce),     // 1: the aclk edges that are core edges
        .probe9 (core_reset)   // 1
    );

endmodule
