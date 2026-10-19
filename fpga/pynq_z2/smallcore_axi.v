// The ARM-facing SmallCore peripheral: an AXI4-Lite slave on the SmallCore
// clock, in front of host_engine (can_host_engine.v), which makes every host.v
// transaction to its timing. The PS's AXI reaches it through an AXI clock
// converter in the block design (build_axi.tcl), so every handshake here is
// already in this domain; no AXI signal reaches host_we/host_re, only the
// engine's requests do. smallcore.v itself is outside, in smallcore_pynq_axi.v.
//
// The register map is the permanent ARM ABI, v1; offsets are bytes, registers 32 bits:
//
//   0x00 ID            RO  0x53434F52 "SCOR"
//   0x04 VERSION       RO  [31:16] ABI version 1, [15:8] TX staging depth log2, [7:0] CORE_DIV
//   0x08 SCRATCH       RW
//   0x0C CTRL          RW  [0] core reset, held while 1 (also empties TX staging and clears
//                          TX_COMMITTED); [1] RX enable: the engine drains SmallCore's RX FIFO
//                          into the RX ring; [2] pads: 0 CAN on PMOD A, 1 GPIO on PMOD B
//   0x10 STATUS        RO  [0] idle: nothing staged, no CONTROL or raw request pending, no
//                          transaction in flight but the RX drain; [1] TX staging full;
//                          [2] RX ring overflowed (bytes dropped); [3] raw done; [4] raw busy;
//                          [5] MMCM locked; [6] RUN busy: from COMMAND RUN until CONTROL is
//                          written and SmallCore's STATUS read again, after which CORE_STATUS
//                          describes the program RUN started; [10:8] the engine's state
//   0x14 COMMAND       WO  write 1s: [0] RUN, write SLOT to SmallCore's CONTROL, ahead of any
//                          staged bytes; [1] RX ring clear; [2] TX staging flush (and
//                          TX_COMMITTED clear); [3] TX_COMMITTED clear
//   0x18 SLOT          RW  [7:0] what RUN writes: 0..15 ROM slot, 0x10 run RAM, 0x20 load RAM
//   0x1C TX_DATA       WO  [7:0] stage a byte for SmallCore's TX_DATA; dropped while staging is full
//   0x20 TX_COUNT      RO  [15:0] bytes staged, not yet taken by the engine
//   0x24 RX_DATA       RO  pops the RX ring: [7:0] the byte, [8] valid (0: the ring was empty,
//                          nothing popped)
//   0x28 RX_COUNT      RO  [15:0] bytes in the RX ring
//   0x2C RAW           RW  write: one host.v transaction, [7:0] wdata, [9:8] addr, [16] 1 write /
//                          0 read, [17] with a read of RX_DATA, pop it; ignored while one is busy.
//                          read: [7:0] the read's result, [30] busy, [31] done since the request
//   0x30 CORE_STATUS   RO  SmallCore's STATUS as the engine last read it: [2] halted, [1] tx_full,
//                          [0] rx_empty
//   0x34 TX_COMMITTED  RO  [15:0] staged bytes whose TX_DATA transaction has completed, the
//                          strobe's last high clock after host.v acted on it: a TX FIFO push
//                          in a protocol program, a program byte with CONTROL 0x20. Raw writes
//                          are not counted. Wraps at 2^16; cleared by core reset, flush and
//                          COMMAND[3].
//
// A write takes AW and W together; a read answers the clock after its AR transfer.
module smallcore_axi #(
    parameter CORE_DIV      = 8,
    parameter TX_DEPTH_LOG2 = 10,
    parameter RX_LOG2       = 8
) (
    input             aclk,
    input             aresetn,
    input             locked,

    input      [7:0]  s_axi_awaddr,
    input             s_axi_awvalid,
    output reg        s_axi_awready,
    input      [31:0] s_axi_wdata,
    input      [3:0]  s_axi_wstrb,
    input             s_axi_wvalid,
    output reg        s_axi_wready,
    output     [1:0]  s_axi_bresp,
    output reg        s_axi_bvalid,
    input             s_axi_bready,
    input      [7:0]  s_axi_araddr,
    input             s_axi_arvalid,
    output reg        s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output     [1:0]  s_axi_rresp,
    output reg        s_axi_rvalid,
    input             s_axi_rready,

    // SmallCore: its reset, its host bus, the pad select
    output            core_reset,
    output            pad_sel,
    output     [7:0]  host_wdata,
    output     [1:0]  host_addr,
    output            host_we, host_re,
    input      [7:0]  host_rdata,
    output     [2:0]  core_status
);

    localparam [31:0] ID      = 32'h53434F52;
    localparam [15:0] ABI     = 16'h0001;
    localparam [31:0] VERSION = {ABI, TX_DEPTH_LOG2[7:0], CORE_DIV[7:0]};
    localparam TX_DEPTH = 1 << TX_DEPTH_LOG2;

    localparam [7:0] A_ID = 8'h00, A_VERSION = 8'h04, A_SCRATCH = 8'h08, A_CTRL = 8'h0C,
                     A_STATUS = 8'h10, A_COMMAND = 8'h14, A_SLOT = 8'h18, A_TX_DATA = 8'h1C,
                     A_TX_COUNT = 8'h20, A_RX_DATA = 8'h24, A_RX_COUNT = 8'h28, A_RAW = 8'h2C,
                     A_CORE_STATUS = 8'h30, A_TX_COMMITTED = 8'h34;

    reg [31:0] scratch = 32'd0;
    reg [2:0]  ctrl    = 3'd0;
    reg [7:0]  slot    = 8'd0;

    // single-clock command pulses to the engine, which takes their rising edges
    reg        run_p = 1'b0, rx_clear_p = 1'b0, raw_p = 1'b0;
    reg [17:0] raw_req = 18'd0;
    reg        raw_done_q = 1'b0;

    assign core_reset = !aresetn || ctrl[0];
    assign pad_sel    = ctrl[2];

    // TX staging: a first-word-fall-through FIFO, read combinationally by the engine. Kept in
    // distributed RAM: left to itself Vivado puts it in a block RAM with the read pointer as
    // the RAM's address register, enabled only when the pointer moves, so a byte written into
    // an empty FIFO (the address being read) never reached the engine: the CRC polynomial of
    // a CAN frame and every RAM-load byte read stale on the board, though not in simulation.
    (* ram_style = "distributed" *)
    reg  [7:0]             stg [0:TX_DEPTH-1];
    reg  [TX_DEPTH_LOG2:0] stg_wr = 0, stg_rd = 0;
    wire [TX_DEPTH_LOG2:0] stg_count = stg_wr - stg_rd;
    wire                   stg_full  = stg_count == TX_DEPTH;
    wire                   tx_valid  = stg_count != 0;
    wire [7:0]             tx_data   = stg[stg_rd[TX_DEPTH_LOG2-1:0]];
    reg  [15:0]            committed = 16'd0;

    wire [2:0]       status, state;
    wire             tx_pop, tx_commit, idle, ctrl_busy, raw_busy, raw_done, rx_overflow;
    wire [7:0]       raw_rdata, rx_head;
    wire [RX_LOG2:0] rx_count;

    assign s_axi_bresp = 2'b00;
    assign s_axi_rresp = 2'b00;

    // ready for one clock once both are valid; the transfer is the clock ready meets valid,
    // and the response follows it
    wire wr_accept = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !s_axi_awready;
    wire rd_accept = s_axi_arvalid && !s_axi_rvalid && !s_axi_arready;
    wire wr = s_axi_awready && s_axi_awvalid && s_axi_wvalid;
    wire rd = s_axi_arready && s_axi_arvalid;

    wire [7:0] wa = {s_axi_awaddr[7:2], 2'b00};
    wire [7:0] ra = {s_axi_araddr[7:2], 2'b00};
    wire [31:0] wd = s_axi_wdata;

    // a register write takes the bytes its strobes select
    function [31:0] merge(input [31:0] old, input [31:0] d, input [3:0] s);
        integer b;
        begin
            for (b = 0; b < 4; b = b + 1) merge[8*b +: 8] = s[b] ? d[8*b +: 8] : old[8*b +: 8];
        end
    endfunction

    wire stage    = wr && wa == A_TX_DATA && s_axi_wstrb[0] && !stg_full;
    wire command  = wr && wa == A_COMMAND && s_axi_wstrb[0];
    wire flush    = core_reset || (command && wd[2]);
    wire rx_pop   = rd && ra == A_RX_DATA && rx_count != 0;
    wire raw_busy_any = raw_p || raw_busy;
    wire run_busy     = run_p || ctrl_busy;

    host_engine #(.RX_LOG2(RX_LOG2)) engine (
        .clk         (aclk),
        .reset       (core_reset),
        .manual      (1'b0),
        .m_wdata     (8'd0),
        .m_addr      (2'd0),
        .m_we        (1'b0),
        .m_re        (1'b0),
        .ctrl_value  (slot),
        .ctrl_go     (run_p),
        .raw_go      (raw_p),
        .raw_write   (raw_req[16]),
        .raw_addr    (raw_req[9:8]),
        .raw_wdata   (raw_req[7:0]),
        .raw_pop     (raw_req[17]),
        .tx_valid    (tx_valid),
        .tx_data     (tx_data),
        .rx_en       (ctrl[1]),
        .rx_clear    (rx_clear_p),
        .rx_pop      (rx_pop),
        .rx_rd_idx   ({RX_LOG2{1'b0}}),
        .status      (status),
        .state       (state),
        .tx_pop      (tx_pop),
        .tx_commit   (tx_commit),
        .idle        (idle),
        .idle_tick   (),
        .ctrl_busy   (ctrl_busy),
        .raw_busy    (raw_busy),
        .raw_done    (raw_done),
        .raw_rdata   (raw_rdata),
        .rx_count    (rx_count),
        .rx_overflow (rx_overflow),
        .rx_byte     (),
        .rx_head     (rx_head),
        .host_wdata  (host_wdata),
        .host_addr   (host_addr),
        .host_we     (host_we),
        .host_re     (host_re),
        .host_rdata  (host_rdata)
    );

    assign core_status = status;

    // the staging FIFO and the committed count
    always @(posedge aclk) begin
        if (stage) stg[stg_wr[TX_DEPTH_LOG2-1:0]] <= wd[7:0];
        if (flush) begin
            stg_rd <= stg_wr + stage;
            if (stage) stg_wr <= stg_wr + 1'b1;
        end
        else begin
            if (stage)  stg_wr <= stg_wr + 1'b1;
            if (tx_pop) stg_rd <= stg_rd + 1'b1;
        end
        if (flush || (command && wd[3])) committed <= 16'd0;
        else if (tx_commit)              committed <= committed + 16'd1;
    end

    always @(posedge aclk) begin
        run_p      <= 1'b0;
        rx_clear_p <= 1'b0;
        raw_p      <= 1'b0;
        if (raw_done) raw_done_q <= 1'b1;

        if (!aresetn) begin
            s_axi_awready <= 1'b0;
            s_axi_wready  <= 1'b0;
            s_axi_bvalid  <= 1'b0;
            s_axi_arready <= 1'b0;
            s_axi_rvalid  <= 1'b0;
            s_axi_rdata   <= 32'd0;
            scratch       <= 32'd0;
            ctrl          <= 3'd0;
            slot          <= 8'd0;
            raw_req       <= 18'd0;
            raw_done_q    <= 1'b0;
        end
        else begin
            s_axi_awready <= wr_accept;
            s_axi_wready  <= wr_accept;
            if (wr) begin
                s_axi_bvalid <= 1'b1;
                case (wa)
                    A_SCRATCH: scratch <= merge(scratch, wd, s_axi_wstrb);
                    A_CTRL:    if (s_axi_wstrb[0]) ctrl <= wd[2:0];
                    A_SLOT:    if (s_axi_wstrb[0]) slot <= wd[7:0];
                    A_COMMAND: if (s_axi_wstrb[0]) begin
                        run_p      <= wd[0];
                        rx_clear_p <= wd[1];
                    end
                    A_RAW: if (!raw_busy_any) begin
                        raw_req    <= merge({14'd0, raw_req}, wd, s_axi_wstrb);
                        raw_p      <= 1'b1;
                        raw_done_q <= 1'b0;
                    end
                    default: ;
                endcase
            end
            else if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;

            s_axi_arready <= rd_accept;
            if (rd) begin
                s_axi_rvalid <= 1'b1;
                case (ra)
                    A_ID:           s_axi_rdata <= ID;
                    A_VERSION:      s_axi_rdata <= VERSION;
                    A_SCRATCH:      s_axi_rdata <= scratch;
                    A_CTRL:         s_axi_rdata <= {29'd0, ctrl};
                    A_STATUS:       s_axi_rdata <= {21'd0, state, 1'b0, run_busy, locked, raw_busy_any,
                                                    raw_done_q, rx_overflow, stg_full,
                                                    idle && !run_p && !raw_p && !rx_clear_p};
                    A_SLOT:         s_axi_rdata <= {24'd0, slot};
                    A_TX_COUNT:     s_axi_rdata <= {{(31 - TX_DEPTH_LOG2){1'b0}}, stg_count};
                    A_RX_DATA:      s_axi_rdata <= {23'd0, rx_count != 0, rx_count != 0 ? rx_head : 8'd0};
                    A_RX_COUNT:     s_axi_rdata <= {{(31 - RX_LOG2){1'b0}}, rx_count};
                    A_RAW:          s_axi_rdata <= {raw_done_q, raw_busy_any, 22'd0, raw_rdata};
                    A_CORE_STATUS:  s_axi_rdata <= {29'd0, status};
                    A_TX_COMMITTED: s_axi_rdata <= {16'd0, committed};
                    default:        s_axi_rdata <= 32'd0;
                endcase
            end
            else if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
        end
    end

endmodule
