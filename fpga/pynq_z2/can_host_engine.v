// FPGA-side host for smallcore.v's register bus, for hosts too slow for the
// 4-deep FIFOs (a VIO over JTAG writes every few milliseconds; a CAN program
// takes a byte every 8 us at 1 Mbit/s; the ARM's loads cross a clock
// converter). host_engine owns the bus unless `manual`:
//
//   ctrl_go rising   writes CONTROL = ctrl_value (a restart keeps queued TX bytes);
//                    ctrl_busy until the write is done and STATUS read again after it, so
//                    `status` describes what the write started
//   raw_go rising    one transaction from the raw request: a write of raw_wdata to
//                    raw_addr, or a read of raw_addr into raw_rdata, with an RX_DATA
//                    pop when raw_pop; raw_busy until it is done, raw_done a clock after
//   tx_valid         a staged byte on tx_data: written to TX_DATA once STATUS has
//                    room, tx_pop the clock it is taken; tx_commit the clock its
//                    transaction completes (the strobe's last high clock, after
//                    host.v has acted on it: TX FIFO push, or program loader byte)
//   rx_en            pops RX_DATA into the RX ring whenever STATUS says non-empty
//   rx_clear rising  empties the ring; rx_pop drops its head; rx_byte is the byte
//                    rx_rd_idx after the head, a clock late; rx_head the head itself
//
// A transaction is 7 clocks, host.v's minimum: the strobe 4 high, then 3
// low in which the engine reads STATUS (addr 2), decides, and sets addr and
// wdata a clock before the next rise; addr only moves after the fall. 7 beats
// can_rx_crc.asm's PUSH every data bit, 8 clocks. A raw read with no pop has no
// strobe: rdata is combinational on addr. `status` holds {halted, tx_full,
// rx_empty} from the last low phase. Priority: CONTROL, raw, TX, RX.
//
// can_host_engine, below, is the interface smallcore_pynq_can.v's VIO and
// sim/tb_can_engine.v drive: a 4-bit slot and a TX byte vector.
module host_engine #(
    parameter RX_LOG2 = 8                  // the RX ring, 2^RX_LOG2 bytes
) (
    input                        clk,
    input                        reset,

    // commands
    input                        manual,
    input  [7:0]                 m_wdata,
    input  [1:0]                 m_addr,
    input                        m_we, m_re,
    input  [7:0]                 ctrl_value,
    input                        ctrl_go,
    input                        raw_go,
    input                        raw_write,
    input  [1:0]                 raw_addr,
    input  [7:0]                 raw_wdata,
    input                        raw_pop,
    input                        tx_valid,
    input  [7:0]                 tx_data,
    input                        rx_en,
    input                        rx_clear,
    input                        rx_pop,
    input  [RX_LOG2-1:0]         rx_rd_idx,

    // state
    output reg [2:0]             status,      // {halted, tx_full, rx_empty}
    output reg [2:0]             state,
    output                       tx_pop,
    output                       tx_commit,
    output                       idle,        // nothing pending or in flight but the RX drain
    output                       idle_tick,   // the clock it finds nothing at all to do
    output                       ctrl_busy,
    output                       raw_busy,
    output reg                   raw_done,
    output reg [7:0]             raw_rdata,
    output reg [RX_LOG2:0]       rx_count,
    output reg                   rx_overflow,
    output reg [7:0]             rx_byte,
    output     [7:0]             rx_head,

    // smallcore's host bus
    output     [7:0]             host_wdata,
    output     [1:0]             host_addr,
    output                       host_we, host_re,
    input      [7:0]             host_rdata
);

    localparam [2:0] S_LOW0 = 3'd0, S_STAT = 3'd1, S_SETUP = 3'd2, S_HIGH = 3'd3;
    localparam RX_SIZE = 1 << RX_LOG2;

    reg [7:0] e_wdata = 8'd0;
    reg [1:0] e_addr  = 2'd2;
    reg       e_we    = 1'b0;
    reg       e_re    = 1'b0;
    reg       e_read  = 1'b0;         // the transaction in flight is an RX pop
    reg       e_tx    = 1'b0;         // ... a staged TX byte
    reg       e_raw   = 1'b0;         // ... the raw request
    reg [2:0] count   = 3'd0;

    reg ctrl_go_d = 1'b0, raw_go_d = 1'b0, rx_clear_d = 1'b0;
    reg ctrl_pending = 1'b0;
    reg ctrl_flight  = 1'b0;          // the CONTROL write made, STATUS not yet read after it
    reg raw_pending  = 1'b0;
    reg       raw_write_q = 1'b0, raw_pop_q = 1'b0;
    reg [1:0] raw_addr_q  = 2'd0;
    reg [7:0] raw_wdata_q = 8'd0;

    reg [7:0]         rx_buf [0:RX_SIZE-1];
    reg [RX_LOG2-1:0] rx_wr = 0, rx_rd = 0;

    assign host_wdata = manual ? m_wdata : e_wdata;
    assign host_addr  = manual ? m_addr  : e_addr;
    assign host_we    = manual ? m_we    : e_we;
    assign host_re    = manual ? m_re    : e_re;

    // the S_STAT decision, in priority order
    wire deciding  = !reset && !manual && state == S_STAT;
    wire take_ctrl = deciding && ctrl_pending;
    wire take_raw  = deciding && !ctrl_pending && raw_pending;
    wire take_tx   = deciding && !ctrl_pending && !raw_pending && tx_valid && !host_rdata[1];
    wire take_rx   = deciding && !ctrl_pending && !raw_pending && !(tx_valid && !host_rdata[1])
                     && rx_en && !host_rdata[0];

    assign tx_pop    = take_tx;
    assign idle_tick = deciding && !take_ctrl && !take_raw && !take_tx && !take_rx;
    assign idle      = !reset && !manual && state == S_STAT && !ctrl_pending && !raw_pending && !tx_valid;
    assign tx_commit = !reset && !manual && state == S_HIGH && count == 3'd3 && e_tx;
    assign rx_head   = rx_buf[rx_rd];
    assign ctrl_busy = ctrl_pending || ctrl_flight;

    initial begin
        status      = 3'b101;
        state       = S_LOW0;
        raw_done    = 1'b0;
        raw_rdata   = 8'd0;
        rx_count    = 0;
        rx_overflow = 1'b0;
        rx_byte     = 8'd0;
    end

    always @(posedge clk) rx_byte <= rx_buf[rx_rd + rx_rd_idx];

    always @(posedge clk) begin
        ctrl_go_d  <= ctrl_go;
        raw_go_d   <= raw_go;
        rx_clear_d <= rx_clear;
        raw_done   <= 1'b0;

        if (ctrl_go && !ctrl_go_d) ctrl_pending <= 1'b1;
        if (raw_go && !raw_go_d && !raw_pending) begin
            raw_pending <= 1'b1;
            raw_write_q <= raw_write;
            raw_addr_q  <= raw_addr;
            raw_wdata_q <= raw_wdata;
            raw_pop_q   <= raw_pop;
        end
        if (rx_pop && rx_count != 0) begin
            rx_rd    <= rx_rd + 1'b1;
            rx_count <= rx_count - 1'b1;
        end
        if (rx_clear && !rx_clear_d) begin
            rx_wr       <= 0;
            rx_rd       <= 0;
            rx_count    <= 0;
            rx_overflow <= 1'b0;
        end

        if (reset || manual) begin
            // hold the strobes low; reset keeps the >= 3 clocks low host.v wants after it
            e_we   <= 1'b0;
            e_re   <= 1'b0;
            e_addr <= 2'd2;
            e_tx   <= 1'b0;
            e_raw  <= 1'b0;
            count  <= 3'd0;
            state  <= S_LOW0;
            ctrl_flight <= 1'b0;
            if (reset && raw_pending) begin   // a raw request dropped by reset still finishes
                raw_pending <= 1'b0;
                raw_done    <= 1'b1;
            end
        end
        else begin
            case (state)
                S_LOW0: begin             // the strobe fell last clock: addr may move now
                    e_addr <= 2'd2;
                    state  <= S_STAT;
                end
                S_STAT: begin             // STATUS has been on rdata a clock
                    status <= host_rdata[2:0];
                    ctrl_flight <= take_ctrl;
                    e_read <= 1'b0;
                    e_tx   <= 1'b0;
                    e_raw  <= 1'b0;
                    state  <= S_SETUP;
                    if (take_ctrl) begin
                        ctrl_pending <= 1'b0;
                        e_addr  <= 2'd3;
                        e_wdata <= ctrl_value;
                    end
                    else if (take_raw) begin
                        e_raw   <= 1'b1;
                        e_addr  <= raw_addr_q;
                        e_wdata <= raw_wdata_q;
                    end
                    else if (take_tx) begin
                        e_tx    <= 1'b1;
                        e_addr  <= 2'd0;
                        e_wdata <= tx_data;
                    end
                    else if (take_rx) begin
                        e_addr <= 2'd1;
                        e_read <= 1'b1;
                    end
                    else state <= S_STAT; // nothing to do: keep reading STATUS
                end
                S_SETUP: begin            // addr/wdata stable a clock: raise the strobe
                    count <= 3'd0;
                    state <= S_HIGH;
                    if (e_raw && !raw_write_q) begin
                        raw_rdata <= host_rdata;
                        if (raw_pop_q) e_re <= 1'b1;
                        else begin        // a read is rdata alone: no strobe
                            raw_pending <= 1'b0;
                            raw_done    <= 1'b1;
                            state       <= S_LOW0;
                        end
                    end
                    else if (e_read) begin // RX_DATA is the FIFO head, combinational on addr
                        if (rx_count < RX_SIZE) begin
                            rx_buf[rx_wr] <= host_rdata;
                            rx_wr    <= rx_wr + 1'b1;
                            rx_count <= rx_count + 1'b1 - (rx_pop && rx_count != 0);
                        end
                        else rx_overflow <= 1'b1;
                        e_re <= 1'b1;
                    end
                    else e_we <= 1'b1;
                end
                S_HIGH: begin             // 4 clocks high
                    count <= count + 3'd1;
                    if (count == 3'd3) begin
                        e_we  <= 1'b0;
                        e_re  <= 1'b0;
                        state <= S_LOW0;
                        if (e_raw) begin
                            raw_pending <= 1'b0;
                            raw_done    <= 1'b1;
                        end
                    end
                end
                default: state <= S_LOW0;
            endcase
        end
    end

    assign raw_busy = raw_pending;

endmodule


// The VIO's interface to host_engine: CONTROL = run_slot on run_go, and tx_go
// pushing tx_buf bytes 0..tx_len-1 as space allows (tx_idx counts them out,
// tx_active until the engine next finds nothing to do with all of them gone).
// No raw requests, no RX pops: rx_rd_idx reads the ring from its start.
module can_host_engine #(
    parameter TX_BYTES = 32
) (
    input                        clk,
    input                        reset,

    // commands
    input                        manual,
    input  [7:0]                 m_wdata,
    input  [1:0]                 m_addr,
    input                        m_we, m_re,
    input  [3:0]                 run_slot,
    input                        run_go,
    input  [8*TX_BYTES-1:0]      tx_buf,
    input  [5:0]                 tx_len,
    input                        tx_go,
    input                        rx_en,
    input                        rx_clear,
    input  [7:0]                 rx_rd_idx,

    // state
    output     [2:0]             status,      // {halted, tx_full, rx_empty}
    output     [2:0]             state,
    output reg [5:0]             tx_idx,
    output reg                   tx_active,
    output     [8:0]             rx_count,
    output                       rx_overflow,
    output     [7:0]             rx_byte,

    // smallcore's host bus
    output     [7:0]             host_wdata,
    output     [1:0]             host_addr,
    output                       host_we, host_re,
    input      [7:0]             host_rdata
);

    reg  tx_go_d = 1'b0;
    wire tx_pop, idle_tick;

    initial begin
        tx_idx    = 6'd0;
        tx_active = 1'b0;
    end

    always @(posedge clk) begin
        tx_go_d <= tx_go;
        if (tx_go && !tx_go_d) begin
            tx_active <= 1'b1;
            tx_idx    <= 6'd0;
        end
        if (tx_pop) tx_idx <= tx_idx + 6'd1;
        if (idle_tick && tx_active && tx_idx >= tx_len) tx_active <= 1'b0;
    end

    host_engine #(.RX_LOG2(8)) core (
        .clk         (clk),
        .reset       (reset),
        .manual      (manual),
        .m_wdata     (m_wdata),
        .m_addr      (m_addr),
        .m_we        (m_we),
        .m_re        (m_re),
        .ctrl_value  ({4'd0, run_slot}),
        .ctrl_go     (run_go),
        .raw_go      (1'b0),
        .raw_write   (1'b0),
        .raw_addr    (2'd0),
        .raw_wdata   (8'd0),
        .raw_pop     (1'b0),
        .tx_valid    (tx_active && tx_idx < tx_len),
        .tx_data     (tx_buf[8*tx_idx +: 8]),
        .rx_en       (rx_en),
        .rx_clear    (rx_clear),
        .rx_pop      (1'b0),
        .rx_rd_idx   (rx_rd_idx),
        .status      (status),
        .state       (state),
        .tx_pop      (tx_pop),
        .tx_commit   (),
        .idle        (),
        .idle_tick   (idle_tick),
        .ctrl_busy   (),
        .raw_busy    (),
        .raw_done    (),
        .raw_rdata   (),
        .rx_count    (rx_count),
        .rx_overflow (rx_overflow),
        .rx_byte     (rx_byte),
        .rx_head     (),
        .host_wdata  (host_wdata),
        .host_addr   (host_addr),
        .host_we     (host_we),
        .host_re     (host_re),
        .host_rdata  (host_rdata)
    );

endmodule
