// xsim bench for can_host_engine.v driving rtl/smallcore.v the way smallcore_pynq_can.v does:
// CTX = pad 0 open-drain, the bus = CTX AND another node, CRX = the bus `+delay` clocks late
// (the transceiver loop) through one flop, gpio_in[0] = CRX AND CTX.
// Run by run_sim.py, which writes the inputs and checks the outputs.
// params.txt holds mode_rx slot tx_len rx_n ack_at delay limit:
//   TX  tx.mem's tx_len bytes, the slot; the other node ACKs from clock ack_at after the
//       SOF edge for 8 clocks when ack_at > 0
//   RX  rx.mem's rx_n bits, 8 clocks each, driven by the other node; tx.mem's tx_len
//       bytes queued first (the polynomial for slot 14)
// Writes ctx.txt and bus.txt, a character a clock, and prints RESULT lines.
`timescale 1ns / 1ps
module tb;
    reg clk = 1'b0;
    always #62.5 clk = ~clk;              // 8 MHz

    reg         reset = 1'b1;
    reg  [3:0]  run_slot = 4'd0;
    reg         run_go = 1'b0, tx_go = 1'b0, rx_en = 1'b0;
    reg  [5:0]  tx_len = 6'd0;
    reg  [255:0] tx_buf = 256'd0;

    wire [2:0] status, state;
    wire [5:0] tx_idx;
    wire       tx_active, rx_overflow;
    wire [8:0] rx_count;
    wire [7:0] rx_byte;
    wire [7:0] host_wdata, host_rdata;
    wire [1:0] host_addr;
    wire       host_we, host_re;
    wire [3:0] gpio_out, gpio_oe, gpio_in;

    can_host_engine engine (
        .clk(clk), .reset(reset),
        .manual(1'b0), .m_wdata(8'd0), .m_addr(2'd0), .m_we(1'b0), .m_re(1'b0),
        .run_slot(run_slot), .run_go(run_go),
        .tx_buf(tx_buf), .tx_len(tx_len), .tx_go(tx_go),
        .rx_en(rx_en), .rx_clear(1'b0), .rx_rd_idx(8'd0),
        .status(status), .state(state), .tx_idx(tx_idx), .tx_active(tx_active),
        .rx_count(rx_count), .rx_overflow(rx_overflow), .rx_byte(rx_byte),
        .host_wdata(host_wdata), .host_addr(host_addr), .host_we(host_we), .host_re(host_re),
        .host_rdata(host_rdata));

    smallcore dut (
        .clk(clk), .reset(reset),
        .host_wdata(host_wdata), .host_addr(host_addr), .host_we(host_we), .host_re(host_re),
        .host_rdata(host_rdata),
        .gpio_in(gpio_in), .gpio_out(gpio_out), .gpio_oe(gpio_oe));

    // the pads and the bus
    reg  ext = 1'b1;
    wire ctx = gpio_oe[0] ? gpio_out[0] : 1'b1;
    wire bus = ctx & ext;
    reg  [15:0] hist = 16'hFFFF;
    reg  crx_s = 1'b1;
    integer delay;
    always @(posedge clk) begin
        hist  <= {hist[14:0], bus};
        crx_s <= (delay <= 0) ? bus : hist[delay-1];
    end
    // delay < 0: the pad read straight off the bus, as the repository's own benches do
    assign gpio_in = {3'b111, (delay < 0) ? bus : (crx_s & ctx)};

    // stimulus
    reg [7:0] txm [0:31];
    reg       rxm [0:511];
    integer mode_rx, slot, n, rx_n, ack_at, cyc, sof, start, i, f_ctx, f_bus, limit;

    always @(posedge clk) cyc <= cyc + 1;

    always @(posedge clk) begin
        if (!mode_rx && sof < 0 && start > 0 && cyc > start && !bus) sof <= cyc;
        if (!mode_rx && ack_at > 0 && sof >= 0)
            ext <= !(cyc - sof >= ack_at && cyc - sof < ack_at + 8);
        if (mode_rx && start > 0 && cyc >= start) begin
            ext <= ((cyc - start) / 8 < rx_n) ? rxm[(cyc - start) / 8] : 1'b1;
        end
        if (start > 0) begin
            $fwrite(f_ctx, "%0d", ctx);
            $fwrite(f_bus, "%0d", bus);
        end
    end

    initial begin
        cyc = 0; sof = -1; start = 0;
        // params.txt: mode_rx slot tx_len rx_n ack_at delay limit (Windows .bat wrappers mangle plusargs)
        f_ctx = $fopen("params.txt", "r");
        i = $fscanf(f_ctx, "%d %d %d %d %d %d %d", mode_rx, slot, n, rx_n, ack_at, delay, limit);
        $fclose(f_ctx);
        if (n > 0) $readmemh("tx.mem", txm);
        if (rx_n > 0) $readmemb("rx.mem", rxm);
        for (i = 0; i < n; i = i + 1) tx_buf[8*i +: 8] = txm[i];
        tx_len = n;
        f_ctx = $fopen("ctx.txt", "w");
        f_bus = $fopen("bus.txt", "w");

        repeat (40) @(posedge clk);
        reset = 1'b0;
        repeat (10) @(posedge clk);
        rx_en = 1'b1;
        if (n > 0) tx_go = 1'b1;           // pre-fill before RUN
        repeat (60) @(posedge clk);
        $display("RESULT prefill tx_idx=%0d status=%b", tx_idx, status);
        run_slot = slot;
        run_go = 1'b1;
        start = cyc;                       // traces and the RX stimulus count from RUN
        repeat (limit) @(posedge clk);
        repeat (40) @(posedge clk);       // the engine's last pops

        $display("RESULT sof=%0d tx_idx=%0d tx_active=%0d status=%b rx_count=%0d overflow=%0d",
                 sof < 0 ? -1 : sof - start, tx_idx, tx_active, status, rx_count, rx_overflow);
        $write("RESULT rx");
        for (i = 0; i < rx_count && i < 256; i = i + 1) $write(" %02x", engine.core.rx_buf[i]);
        $write("\n");
        $fclose(f_ctx);
        $fclose(f_bus);
        $finish;
    end
endmodule
