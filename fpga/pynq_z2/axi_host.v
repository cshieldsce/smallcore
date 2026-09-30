// AXI4-Lite to SmallCore host bus: the Zynq's ARM becomes the host. A
// register write from Linux turns into one host bus transaction with the
// timing rtl/host.v asks for, counted in core clocks; SmallCore and its
// host protocol are untouched, this only replaces buttons with registers.
//
// Everything is on aclk (FCLK_CLK0). SmallCore runs on a gated copy of it,
// one edge every CLKDIV aclk cycles: core_ce is registered here and gates
// the clock outside (BUFGCE on the board, a latch and an AND in
// simulation), so the edge happens on the aclk edge after core_ce is set,
// and this block sees core_ce high on exactly the aclk edges that are also
// core edges. That is how it counts strobes in core clocks.
//
//   offset  name    access
//   0x00    ID      R   0x534D4331, "SMC1"
//   0x04    CTRL    W   bit 0: hard reset of SmallCore (core, FIFOs, slot 0), RESET_CLOCKS core clocks
//                   R   {30'b0, core_reset, busy}
//   0x08    CLKDIV  RW  aclk cycles per core clock, >= 1 (0 reads back as 1); CLKDIV_RESET out of reset
//   0x0C    CMD     W   one host transaction: [7:0] wdata, [9:8] addr, [16] we, [17] re; exactly one
//                       of we, re, or the write does nothing. The AXI write stalls while the previous
//                       transaction is in flight, so software never polls and never loses one.
//   0x10    LAST    R   [7:0] host_rdata as the last strobe rose: the popped byte after an RX_DATA re.
//                       Stalls while a transaction is in flight, so it is always the last CMD's.
//   0x14    PADS    R   {gpio_in, gpio_oe, gpio_out} in [11:8], [7:4], [3:0]; gpio_in synchronized
//   0x20    PEEK0   R   host_rdata with host_addr = 0..3, no strobe: 0x24 RX_DATA head, 0x28 STATUS,
//   ..0x2C              0x2C CONTROL. Stalls while a transaction is in flight.
//
// A transaction: host_addr and host_wdata are set, the strobe rises on the
// next core edge, stays high STROBE_HIGH core clocks, falls, and addr and
// wdata hold through STROBE_LOW more. After a reset the bus rests low
// STROBE_LOW core clocks before the first strobe. host.v wants 4, 3 and 3.
module axi_host #(
    parameter STROBE_HIGH  = 6,
    parameter STROBE_LOW   = 4,
    parameter RESET_CLOCKS = 4,
    parameter CLKDIV_RESET = 4
) (
    input             aclk,
    input             aresetn,

    input      [5:0]  s_axi_awaddr,
    input      [2:0]  s_axi_awprot,
    input             s_axi_awvalid,
    output            s_axi_awready,
    input      [31:0] s_axi_wdata,
    input      [3:0]  s_axi_wstrb,
    input             s_axi_wvalid,
    output            s_axi_wready,
    output     [1:0]  s_axi_bresp,
    output reg        s_axi_bvalid,
    input             s_axi_bready,
    input      [5:0]  s_axi_araddr,
    input      [2:0]  s_axi_arprot,
    input             s_axi_arvalid,
    output            s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output     [1:0]  s_axi_rresp,
    output reg        s_axi_rvalid,
    input             s_axi_rready,

    output reg        core_ce,
    output reg        core_reset,
    output reg [7:0]  host_wdata,
    output reg [1:0]  host_addr,
    output reg        host_we,
    output reg        host_re,
    input      [7:0]  host_rdata,
    input      [3:0]  gpio_in,
    input      [3:0]  gpio_out,
    input      [3:0]  gpio_oe
);
    localparam [31:0] ID = 32'h534D4331;

    localparam [3:0] A_ID = 4'h0, A_CTRL = 4'h1, A_CLKDIV = 4'h2, A_CMD = 4'h3, A_LAST = 4'h4, A_PADS = 4'h5;

    localparam [2:0] IDLE = 3'd0, SETUP = 3'd1, HIGH = 3'd2, LOW = 3'd3, RESET = 3'd4, PEEK = 3'd5;

    reg [2:0]  state;
    reg [7:0]  count;      // core clocks in this state
    reg [31:0] clkdiv;
    reg [31:0] div_count;
    reg        cmd_we, cmd_re;
    reg [7:0]  last;
    reg [3:0]  pads_s0, pads_s1;

    // one write (AW and W together) or one read at a time; every write, and a
    // PEEK or LAST read, waits for IDLE
    wire [3:0] waddr = s_axi_awaddr[5:2];
    wire [3:0] raddr = s_axi_araddr[5:2];
    wire       idle  = (state == IDLE);
    wire       peek  = raddr[3];
    wire       wait_idle = peek || raddr == A_LAST;  // a CMD write is answered before its strobe: these see it done
    wire       do_write = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && idle;
    wire       do_read  = s_axi_arvalid && !s_axi_rvalid && !do_write && (idle || !wait_idle);
    wire       tick  = core_ce;  // this aclk edge is a core edge

    assign s_axi_awready = do_write;
    assign s_axi_wready  = do_write;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_arready = do_read;
    assign s_axi_rresp   = 2'b00;

    // the core clock enable
    always @(posedge aclk) begin
        if (!aresetn) begin
            div_count <= 32'd0;
            core_ce   <= 1'b1;
        end
        else if (div_count + 32'd1 >= clkdiv) begin
            div_count <= 32'd0;
            core_ce   <= 1'b1;
        end
        else begin
            div_count <= div_count + 32'd1;
            core_ce   <= 1'b0;
        end
    end

    always @(posedge aclk) begin
        pads_s0 <= gpio_in;
        pads_s1 <= pads_s0;
    end

    always @(posedge aclk) begin
        if (!aresetn) begin
            state        <= RESET;
            count        <= 8'd0;
            clkdiv       <= CLKDIV_RESET;
            core_reset   <= 1'b1;
            host_we      <= 1'b0;
            host_re      <= 1'b0;
            host_addr    <= 2'd2;
            host_wdata   <= 8'd0;
            cmd_we       <= 1'b0;
            cmd_re       <= 1'b0;
            last         <= 8'd0;
            s_axi_bvalid <= 1'b0;
            s_axi_rvalid <= 1'b0;
            s_axi_rdata  <= 32'd0;
        end
        else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;

            if (do_write) begin
                s_axi_bvalid <= 1'b1;
                case (waddr)
                    A_CTRL: if (s_axi_wdata[0]) begin
                        state      <= RESET;
                        count      <= 8'd0;
                        core_reset <= 1'b1;
                    end
                    A_CLKDIV: clkdiv <= (s_axi_wdata == 32'd0) ? 32'd1 : s_axi_wdata;
                    A_CMD: if (s_axi_wdata[16] != s_axi_wdata[17]) begin
                        host_wdata <= s_axi_wdata[7:0];
                        host_addr  <= s_axi_wdata[9:8];
                        cmd_we     <= s_axi_wdata[16];
                        cmd_re     <= s_axi_wdata[17];
                        state      <= SETUP;
                    end
                    default: ;
                endcase
            end

            if (do_read && peek) begin  // answered from PEEK, next edge
                host_addr <= raddr[1:0];
                state     <= PEEK;
            end
            else if (do_read) begin
                s_axi_rvalid <= 1'b1;
                case (raddr)
                    A_ID:     s_axi_rdata <= ID;
                    A_CTRL:   s_axi_rdata <= {30'd0, core_reset, !idle};
                    A_CLKDIV: s_axi_rdata <= clkdiv;
                    A_LAST:   s_axi_rdata <= {24'd0, last};
                    A_PADS:   s_axi_rdata <= {20'd0, pads_s1, gpio_oe, gpio_out};
                    default:  s_axi_rdata <= 32'd0;
                endcase
            end

            case (state)
                PEEK: begin  // host_addr moved last edge; host_rdata is combinational on it
                    s_axi_rdata  <= {24'd0, host_rdata};
                    s_axi_rvalid <= 1'b1;
                    state        <= IDLE;
                end
                SETUP: if (tick) begin  // addr and wdata were on the bus for this core edge
                    last    <= host_rdata;
                    host_we <= cmd_we;
                    host_re <= cmd_re;
                    count   <= 8'd0;
                    state   <= HIGH;
                end
                HIGH: if (tick) begin
                    if (count == STROBE_HIGH - 1) begin
                        host_we <= 1'b0;
                        host_re <= 1'b0;
                        count   <= 8'd0;
                        state   <= LOW;
                    end
                    else count <= count + 8'd1;
                end
                LOW: if (tick) begin
                    if (count == STROBE_LOW - 1) state <= IDLE;
                    else count <= count + 8'd1;
                end
                RESET: if (tick) begin
                    if (count == RESET_CLOCKS - 1) begin
                        core_reset <= 1'b0;
                        count      <= 8'd0;
                        state      <= LOW;
                    end
                    else count <= count + 8'd1;
                end
                default: ;
            endcase
        end
    end

endmodule
