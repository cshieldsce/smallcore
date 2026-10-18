// FPGA-side host for smallcore.v's register bus, for hosts too slow for the
// 4-deep FIFOs (a VIO over JTAG writes every few milliseconds; a CAN program
// takes a byte every 8 us at 1 Mbit/s). It owns the bus unless `manual`:
//
//   run_go rising   writes CONTROL = run_slot (a restart keeps queued TX bytes)
//   tx_go rising    pushes tx_buf bytes 0..tx_len-1 into TX_DATA as space allows
//   rx_en           pops RX_DATA into rx_buf whenever STATUS says non-empty
//   rx_clear rising empties rx_buf
//
// A transaction is 7 clocks, host.v's minimum: the strobe 4 high, then 3
// low in which the engine reads STATUS (addr 2), decides, and sets addr and
// wdata a clock before the next rise; addr only moves after the fall. 7 beats
// can_rx_crc.asm's PUSH every data bit, 8 clocks. `status` holds {halted,
// tx_full, rx_empty} from the last low phase. Priority: CONTROL, TX, RX.
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
    output reg [2:0]             status,      // {halted, tx_full, rx_empty}
    output reg [2:0]             state,
    output reg [5:0]             tx_idx,
    output reg                   tx_active,
    output reg [8:0]             rx_count,
    output reg                   rx_overflow,
    output reg [7:0]             rx_byte,

    // smallcore's host bus
    output     [7:0]             host_wdata,
    output     [1:0]             host_addr,
    output                       host_we, host_re,
    input      [7:0]             host_rdata
);

    localparam [2:0] S_LOW0 = 3'd0, S_STAT = 3'd1, S_SETUP = 3'd2, S_HIGH = 3'd3;

    reg [7:0] e_wdata = 8'd0;
    reg [1:0] e_addr  = 2'd2;
    reg       e_we    = 1'b0;
    reg       e_re    = 1'b0;
    reg       e_read  = 1'b0;         // the transaction in flight is an RX pop
    reg [2:0] count   = 3'd0;

    reg run_go_d = 1'b0, tx_go_d = 1'b0, rx_clear_d = 1'b0;
    reg run_pending = 1'b0;

    reg [7:0] rx_buf [0:255];

    assign host_wdata = manual ? m_wdata : e_wdata;
    assign host_addr  = manual ? m_addr  : e_addr;
    assign host_we    = manual ? m_we    : e_we;
    assign host_re    = manual ? m_re    : e_re;

    initial begin
        status      = 3'b101;
        state       = S_LOW0;
        tx_idx      = 6'd0;
        tx_active   = 1'b0;
        rx_count    = 9'd0;
        rx_overflow = 1'b0;
        rx_byte     = 8'd0;
    end

    always @(posedge clk) rx_byte <= rx_buf[rx_rd_idx];

    always @(posedge clk) begin
        run_go_d   <= run_go;
        tx_go_d    <= tx_go;
        rx_clear_d <= rx_clear;

        if (run_go && !run_go_d) run_pending <= 1'b1;
        if (tx_go && !tx_go_d) begin
            tx_active <= 1'b1;
            tx_idx    <= 6'd0;
        end
        if (rx_clear && !rx_clear_d) begin
            rx_count    <= 9'd0;
            rx_overflow <= 1'b0;
        end

        if (reset || manual) begin
            // hold the strobes low; reset keeps the >= 3 clocks low host.v wants after it
            e_we   <= 1'b0;
            e_re   <= 1'b0;
            e_addr <= 2'd2;
            count  <= 3'd0;
            state  <= S_LOW0;
        end
        else begin
            case (state)
                S_LOW0: begin             // the strobe fell last clock: addr may move now
                    e_addr <= 2'd2;
                    state  <= S_STAT;
                end
                S_STAT: begin             // STATUS has been on rdata a clock
                    status <= host_rdata[2:0];
                    e_read <= 1'b0;
                    state  <= S_SETUP;
                    if (run_pending) begin
                        run_pending <= 1'b0;
                        e_addr  <= 2'd3;
                        e_wdata <= {4'd0, run_slot};
                    end
                    else if (tx_active && tx_idx < tx_len && !host_rdata[1]) begin
                        e_addr  <= 2'd0;
                        e_wdata <= tx_buf[8*tx_idx +: 8];
                        tx_idx  <= tx_idx + 6'd1;
                    end
                    else if (rx_en && !host_rdata[0]) begin
                        e_addr <= 2'd1;
                        e_read <= 1'b1;
                    end
                    else begin
                        if (tx_active && tx_idx >= tx_len) tx_active <= 1'b0;
                        state <= S_STAT;  // nothing to do: keep reading STATUS
                    end
                end
                S_SETUP: begin            // addr/wdata stable a clock: raise the strobe
                    if (e_read) begin     // RX_DATA is the FIFO head, combinational on addr
                        if (rx_count < 9'd256) begin
                            rx_buf[rx_count[7:0]] <= host_rdata;
                            rx_count <= rx_count + 9'd1;
                        end
                        else rx_overflow <= 1'b1;
                        e_re <= 1'b1;
                    end
                    else e_we <= 1'b1;
                    count <= 3'd0;
                    state <= S_HIGH;
                end
                S_HIGH: begin             // 4 clocks high
                    count <= count + 3'd1;
                    if (count == 3'd3) begin
                        e_we  <= 1'b0;
                        e_re  <= 1'b0;
                        state <= S_LOW0;
                    end
                end
                default: state <= S_LOW0;
            endcase
        end
    end

endmodule
