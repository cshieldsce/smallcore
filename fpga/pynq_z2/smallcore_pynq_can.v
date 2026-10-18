// PYNQ-Z2 CAN wrapper for rtl/smallcore.v: the host is can_host_engine.v,
// itself driven by a VIO over JTAG; the CAN pad goes to an SN65HVD230 on PMOD A.
// 125 MHz sysclk -> MMCM -> the core clock, 8 MHz / CORE_DIV: the CAN programs
// take 8 clocks a bit, so 1 Mbit/s / CORE_DIV. The programs drive pin 0
// open-drain and read the bus back from the same pad; with a transceiver the
// pad splits in two:
//   PMOD A pin 1  CTX, the transceiver's TXD: low while the core pulls pin 0 low
//   PMOD A pin 2  CRX, the transceiver's RXD: the bus, own frames included
// gpio 1..3 read PMOD A pins 3, 4 and 7 but never drive them: the CAN
// programs use pin 0 alone, and a pad left driving high out of reset would
// fight anything wired there, the SPI loopback jumper on pins 1 and 4 included.
//
// The read of pad 0 is the wired-AND of CTX and CRX through one flop, as an
// open-drain pad reads the bus. The TX programs read their own bit back two
// or three clocks after driving it, for the CRC and the stuffing, so the
// transceiver's loop delay must stay under one core clock: CORE_DIV is the
// knob, not the core.
//
//   VIO (fpga/pynq_z2/can_host.tcl): the engine's commands and state, a manual bus, rst
//   ila_can:  the pads, the host bus, the engine, at 8 MHz (a 1 MHz ILA clock is too slow for the
//             debug hub to upload from): CORE_DIV samples a core clock
//   ila_loop: raw CTX and CRX on the 125 MHz clock, for the transceiver's loop delay
//   LD0 MMCM locked, LD1 bus dominant, LD2 halted, LD3 reset
//
// Registers take their initial value from configuration, as smallcore_pynq.v.
module smallcore_pynq_can #(
    parameter CORE_DIV = 1                 // 1, 2, 4, 8: 8, 4, 2, 1 MHz
) (
    input        sysclk,
    output [3:0] led,
    output       can_ctx,
    input        can_crx,
    input  [2:0] ja_gpio
);

    // clocks: sysclk on a BUFG for the MMCM, the debug hub and ila_loop;
    // VCO 1000 MHz, CLKOUT6 / 125 = 8 MHz cascaded into CLKOUT4 / CORE_DIV
    wire sysclk_bufg, clk_mmcm, clk, clk8_mmcm, clk8, fb, fb_bufg, locked;
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
    BUFG bufg_ila  (.I(clk8_mmcm), .O(clk8));   // ila_can: 8 MHz at every CORE_DIV, CORE_DIV samples a core clock

    // power-on reset: 16 core clocks after lock, then the VIO's rst
    reg [4:0] por = 5'd0;
    always @(posedge clk) begin
        if (!locked)      por <= 5'd0;
        else if (!por[4]) por <= por + 5'd1;
    end

    // VIO
    wire [7:0]   vo_wdata, vo_rxidx;
    wire [1:0]   vo_addr;
    wire         vo_we, vo_re, vo_rst, vo_manual, vo_txgo, vo_rungo, vo_rxen, vo_rxclr;
    wire [255:0] vo_txbuf;
    wire [5:0]   vo_txlen;
    wire [3:0]   vo_slot;

    wire [7:0] host_wdata, host_rdata;
    wire [1:0] host_addr;
    wire       host_we, host_re;
    wire [2:0] eng_status, eng_state;
    wire [5:0] eng_txidx;
    wire       eng_txactive, eng_rxovf;
    wire [8:0] eng_rxcount;
    wire [7:0] eng_rxbyte;

    vio_host vio_i (
        .clk         (clk),
        .probe_in0   (host_rdata),
        .probe_in1   (locked),
        .probe_in2   (eng_status),
        .probe_in3   (eng_state),
        .probe_in4   (eng_txidx),
        .probe_in5   (eng_txactive),
        .probe_in6   (eng_rxcount),
        .probe_in7   (eng_rxovf),
        .probe_in8   (eng_rxbyte),
        .probe_out0  (vo_wdata),
        .probe_out1  (vo_addr),
        .probe_out2  (vo_we),
        .probe_out3  (vo_re),
        .probe_out4  (vo_rst),
        .probe_out5  (vo_manual),
        .probe_out6  (vo_txbuf),
        .probe_out7  (vo_txlen),
        .probe_out8  (vo_txgo),
        .probe_out9  (vo_slot),
        .probe_out10 (vo_rungo),
        .probe_out11 (vo_rxen),
        .probe_out12 (vo_rxclr),
        .probe_out13 (vo_rxidx)
    );

    reg rst_s = 1'b0;
    always @(posedge clk) rst_s <= vo_rst;
    wire reset = rst_s | !por[4];

    can_host_engine engine_i (
        .clk        (clk),
        .reset      (reset),
        .manual     (vo_manual),
        .m_wdata    (vo_wdata),
        .m_addr     (vo_addr),
        .m_we       (vo_we),
        .m_re       (vo_re),
        .run_slot   (vo_slot),
        .run_go     (vo_rungo),
        .tx_buf     (vo_txbuf),
        .tx_len     (vo_txlen),
        .tx_go      (vo_txgo),
        .rx_en      (vo_rxen),
        .rx_clear   (vo_rxclr),
        .rx_rd_idx  (vo_rxidx),
        .status     (eng_status),
        .state      (eng_state),
        .tx_idx     (eng_txidx),
        .tx_active  (eng_txactive),
        .rx_count   (eng_rxcount),
        .rx_overflow(eng_rxovf),
        .rx_byte    (eng_rxbyte),
        .host_wdata (host_wdata),
        .host_addr  (host_addr),
        .host_we    (host_we),
        .host_re    (host_re),
        .host_rdata (host_rdata)
    );

    // the pads
    wire [3:0] gpio_out, gpio_oe, gpio_in;
    reg crx_s = 1'b1;
    always @(posedge clk) crx_s <= can_crx;

    assign can_ctx    = gpio_oe[0] ? gpio_out[0] : 1'b1;
    assign gpio_in[0] = crx_s & can_ctx;
    assign gpio_in[3:1] = ja_gpio;

    smallcore smallcore_i (
        .clk        (clk),
        .reset      (reset),
        .host_wdata (host_wdata),
        .host_addr  (host_addr),
        .host_we    (host_we),
        .host_re    (host_re),
        .host_rdata (host_rdata),
        .gpio_in    (gpio_in),
        .gpio_out   (gpio_out),
        .gpio_oe    (gpio_oe)
    );

    ila_can ila_i (
        .clk     (clk8),
        .probe0  (can_ctx),
        .probe1  (crx_s),
        .probe2  (gpio_out),
        .probe3  (gpio_oe),
        .probe4  (host_rdata),
        .probe5  (host_we),
        .probe6  (host_re),
        .probe7  (reset),
        .probe8  (eng_state),
        .probe9  (eng_status),
        .probe10 (eng_txidx),
        .probe11 (eng_rxcount),
        .probe12 (host_addr)
    );

    // the transceiver's loop delay at 8 ns: CTX as it leaves, CRX as it arrives
    reg ctx_f = 1'b1, crx_f = 1'b1;
    always @(posedge sysclk_bufg) begin
        ctx_f <= can_ctx;
        crx_f <= can_crx;
    end
    ila_loop ila_loop_i (
        .clk    (sysclk_bufg),
        .probe0 (ctx_f),
        .probe1 (crx_f)
    );

    assign led = {reset, eng_status[2], !crx_s, locked};

endmodule
