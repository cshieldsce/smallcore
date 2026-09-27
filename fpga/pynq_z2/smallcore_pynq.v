// PYNQ-Z2 smoke test wrapper for rtl/smallcore.v: the board is the host.
// 125 MHz sysclk divided by 4 -> 31.25 MHz core clock. Buttons, debounced,
// drive one bus transaction each while held; host.v's edge detect makes it
// exactly one. The LEDs show host_rdata for the idle address: RX_DATA, or
// STATUS with SW1 up. PMOD A pins 1..4 are the four pads; a jumper from pin 1
// (MOSI, gpio 0) to pin 4 (MISO, gpio 3) is the loopback.
//
//   BTN0  CONTROL <- 8 (spi_duplex_msb), or 7 (spi_duplex_lsb) with SW0 up
//   BTN1  TX_DATA <- 0x96
//   BTN2  pop RX_DATA
//   BTN3  hard reset (there is also a power-on reset)
//   LD0..3 host_rdata[3:0], LD4 r/g/b host_rdata[4..6], LD5 r host_rdata[7]
//
// Simulation twin: rtl_tests/test_pynq.py, DEBOUNCE_BITS 3, the jumper in the bench.
//
// Registers take their initial value from configuration, the FPGA idiom, so
// there is no reset input; Verilator's PROCASSINIT style warning is off for that.
/* verilator lint_off PROCASSINIT */
module smallcore_pynq #(
    parameter DEBOUNCE_BITS = 20  // 2^20 / 31.25 MHz = 34 ms; small in simulation
) (
    input        sysclk,
    input  [1:0] sw,
    input  [3:0] btn,
    output [3:0] led,
    output       led4_r, led4_g, led4_b,
    output       led5_r, led5_g, led5_b,
    inout  [3:0] ja
);

    // core clock: sysclk / 4
    reg [1:0] div = 2'd0;
    always @(posedge sysclk) div <= div + 2'd1;

    wire clk;
`ifdef VERILATOR
    assign clk = div[1];
`else
    BUFG bufg_i (.I(div[1]), .O(clk));
`endif

    // power-on reset: 16 core clocks after configuration, then BTN3
    reg [4:0] por = 5'd0;
    always @(posedge clk) begin
        if (!por[4]) por <= por + 5'd1;
    end

    // debounce: a button counts as changed once its synchronized level has held for 2^DEBOUNCE_BITS clocks
    reg  [3:0] btn_s0 = 4'd0;
    reg  [3:0] btn_s1 = 4'd0;
    wire [3:0] stable;
    always @(posedge clk) begin
        btn_s0 <= btn;
        btn_s1 <= btn_s0;
    end

    genvar g;
    generate
        for (g = 0; g < 4; g = g + 1) begin : debounce
            reg [DEBOUNCE_BITS-1:0] held = 0;
            reg                     level = 1'b0;
            always @(posedge clk) begin
                if (btn_s1[g] == level) begin
                    held <= 0;
                end
                else if (&held) begin
                    level <= btn_s1[g];
                    held  <= 0;
                end
                else begin
                    held <= held + 1'b1;
                end
            end
            assign stable[g] = level;
        end
    endgenerate

    wire run_btn, tx_btn, pop_btn, rst_btn;
    assign {rst_btn, pop_btn, tx_btn, run_btn} = stable;

    // the host: one transaction per button, the idle address on the LEDs
    wire       reset;
    wire       host_we;
    wire       host_re;
    wire [1:0] host_addr;
    wire [7:0] host_wdata;
    wire [7:0] host_rdata;
    wire [3:0] gpio_out;
    wire [3:0] gpio_oe;
    wire [3:0] gpio_in;

    assign reset      = rst_btn | !por[4];
    assign host_we    = run_btn | tx_btn;
    assign host_re    = pop_btn & !host_we;
    assign host_addr  = run_btn ? 2'd3 :            // CONTROL
                        tx_btn  ? 2'd0 :            // TX_DATA
                        pop_btn ? 2'd1 :            // RX_DATA, popped
                        sw[1]   ? 2'd2 : 2'd1;      // idle: STATUS or RX_DATA on the LEDs
    assign host_wdata = run_btn ? (sw[0] ? 8'd7 : 8'd8) : 8'h96;

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

    // the pads: PMOD A pins 1..4 = ja[3:0]
    generate
        for (g = 0; g < 4; g = g + 1) begin : pads
            assign ja[g] = gpio_oe[g] ? gpio_out[g] : 1'bz;
        end
    endgenerate
    assign gpio_in = ja;

    assign led = host_rdata[3:0];
    assign {led4_b, led4_g, led4_r} = host_rdata[6:4];
    assign led5_r = host_rdata[7];
    assign led5_g = 1'b0;
    assign led5_b = 1'b0;

endmodule
