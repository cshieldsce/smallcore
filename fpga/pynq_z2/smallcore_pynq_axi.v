// PYNQ-Z2 wrapper where the Zynq's ARM is the SmallCore host: PS7 M_AXI_GP0
// -> AXI3 to AXI4-Lite -> AXI clock converter -> smallcore_axi.v -> its
// host_engine -> rtl/smallcore.v, unchanged -> smallcore_pads.v. The PS and the
// converters are the block design sc_ps (build_axi.tcl); everything from the
// peripheral on runs on the SmallCore clock. The clock converter is the only
// crossing between the PS's FCLK0 and the core clock.
//
// The core clock comes from the 125 MHz sysclk as in smallcore_pynq_can.v:
// MMCM VCO 1000 MHz, CLKOUT6 / 125 = 8 MHz cascaded into CLKOUT4 / CORE_DIV.
//
// Pads (smallcore_pads.v, CTRL[2]): CAN on PMOD A (pin 1 CTX, pin 2 CRX, pins 3, 4, 7 inputs),
// or the four GPIOs on PMOD B pins 1..4.
//
//   LD0 MMCM locked, LD1 bus dominant, LD2 halted, LD3 core reset
module smallcore_pynq_axi #(
    parameter CORE_DIV = 8                 // 1, 2, 4, 8: 8, 4, 2, 1 MHz
) (
    input         sysclk,
    output [3:0]  led,
    output        can_ctx,
    input         can_crx,
    input  [2:0]  ja_gpio,
    inout  [3:0]  jb,

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
    inout         FIXED_IO_ps_srstb
);

    // clocks: sysclk on a BUFG for the MMCM; CLKOUT4 is the core clock
    wire sysclk_bufg, clk_mmcm, clk, clk8_mmcm, fb, fb_bufg, locked;
    BUFG bufg_sys (.I(sysclk), .O(sysclk_bufg));

    MMCME2_BASE #(
        .CLKIN1_PERIOD    (8.0),
        .DIVCLK_DIVIDE    (1),
        .CLKFBOUT_MULT_F  (8.0),
        .CLKOUT6_DIVIDE   (125),
        .CLKOUT4_CASCADE  ("TRUE"),
        .CLKOUT4_DIVIDE   (CORE_DIV)
    ) mmcm_i (
        .CLKIN1   (sysclk_bufg),
        .CLKFBIN  (fb_bufg),
        .CLKFBOUT (fb),
        .CLKOUT4  (clk_mmcm),
        .CLKOUT6  (clk8_mmcm),
        .LOCKED   (locked),
        .RST      (1'b0),
        .PWRDWN   (1'b0),
        .CLKFBOUTB(), .CLKOUT0(), .CLKOUT0B(), .CLKOUT1(), .CLKOUT1B(), .CLKOUT2(), .CLKOUT2B(),
        .CLKOUT3(), .CLKOUT3B(), .CLKOUT5()
    );
    BUFG bufg_fb   (.I(fb),       .O(fb_bufg));
    BUFG bufg_core (.I(clk_mmcm), .O(clk));

    // the PS and the AXI path; aresetn is synchronous to clk, held while the MMCM is unlocked
    wire        aresetn;
    wire [31:0] awaddr, wdata, araddr, rdata;
    wire [3:0]  wstrb;
    wire [1:0]  bresp, rresp;
    wire        awvalid, awready, wvalid, wready, bvalid, bready;
    wire        arvalid, arready, rvalid, rready;

    sc_ps sc_ps_i (
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
        .core_clk          (clk),
        .core_locked       (locked),
        .core_aresetn      (aresetn),
        .M_AXI_SC_awaddr   (awaddr),
        .M_AXI_SC_awprot   (),
        .M_AXI_SC_awvalid  (awvalid),
        .M_AXI_SC_awready  (awready),
        .M_AXI_SC_wdata    (wdata),
        .M_AXI_SC_wstrb    (wstrb),
        .M_AXI_SC_wvalid   (wvalid),
        .M_AXI_SC_wready   (wready),
        .M_AXI_SC_bresp    (bresp),
        .M_AXI_SC_bvalid   (bvalid),
        .M_AXI_SC_bready   (bready),
        .M_AXI_SC_araddr   (araddr),
        .M_AXI_SC_arprot   (),
        .M_AXI_SC_arvalid  (arvalid),
        .M_AXI_SC_arready  (arready),
        .M_AXI_SC_rdata    (rdata),
        .M_AXI_SC_rresp    (rresp),
        .M_AXI_SC_rvalid   (rvalid),
        .M_AXI_SC_rready   (rready)
    );

    wire       core_reset, pad_sel;
    wire [7:0] host_wdata, host_rdata;
    wire [1:0] host_addr;
    wire       host_we, host_re;
    wire [2:0] core_status;

    smallcore_axi #(
        .CORE_DIV (CORE_DIV)
    ) axi_i (
        .aclk          (clk),
        .aresetn       (aresetn),
        .locked        (locked),
        .s_axi_awaddr  (awaddr[7:0]),
        .s_axi_awvalid (awvalid),
        .s_axi_awready (awready),
        .s_axi_wdata   (wdata),
        .s_axi_wstrb   (wstrb),
        .s_axi_wvalid  (wvalid),
        .s_axi_wready  (wready),
        .s_axi_bresp   (bresp),
        .s_axi_bvalid  (bvalid),
        .s_axi_bready  (bready),
        .s_axi_araddr  (araddr[7:0]),
        .s_axi_arvalid (arvalid),
        .s_axi_arready (arready),
        .s_axi_rdata   (rdata),
        .s_axi_rresp   (rresp),
        .s_axi_rvalid  (rvalid),
        .s_axi_rready  (rready),
        .core_reset    (core_reset),
        .pad_sel       (pad_sel),
        .host_wdata    (host_wdata),
        .host_addr     (host_addr),
        .host_we       (host_we),
        .host_re       (host_re),
        .host_rdata    (host_rdata),
        .core_status   (core_status)
    );

    wire [3:0] gpio_out, gpio_oe, gpio_in;

    smallcore smallcore_i (
        .clk        (clk),
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

    smallcore_pads pads_i (
        .clk      (clk),
        .pad_sel  (pad_sel),
        .gpio_out (gpio_out),
        .gpio_oe  (gpio_oe),
        .gpio_in  (gpio_in),
        .can_ctx  (can_ctx),
        .can_crx  (can_crx),
        .ja_gpio  (ja_gpio),
        .jb       (jb)
    );

    assign led = {core_reset, core_status[2], !pad_sel && !gpio_in[0], locked};

endmodule
