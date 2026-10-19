// xsim bench for host_engine's own interface (can_host_engine.v), the one smallcore_axi.v
// drives, against rtl/smallcore.v: CONTROL by value, raw requests, a staged TX stream with
// its completed-transaction count, the RX ring with pop and peek, and the priority between
// them. The pads are SPI's with a jumper from pad 0 (MOSI) to pad 3 (MISO), as the board's
// loopback. prog.mem holds spi_duplex_msb.asm, written by run_engine_sim.py, for the RAM load.
// Every check prints PASS or FAIL; the last line is RESULT PASS or RESULT FAIL <n>.
`timescale 1ns / 1ps
module tb;
    reg clk = 1'b0;
    always #62.5 clk = ~clk;

    reg        reset = 1'b1;
    reg  [7:0] ctrl_value = 8'd0;
    reg        ctrl_go = 1'b0;
    reg        raw_go = 1'b0, raw_write = 1'b0, raw_pop = 1'b0;
    reg  [1:0] raw_addr = 2'd0;
    reg  [7:0] raw_wdata = 8'd0;
    reg        rx_en = 1'b0, rx_clear = 1'b0, rx_pop = 1'b0;
    reg  [7:0] rx_rd_idx = 8'd0;

    wire [2:0] status, state;
    wire       tx_pop, tx_commit, idle, idle_tick, raw_busy, raw_done, rx_overflow;
    wire [7:0] raw_rdata, rx_byte, rx_head;
    wire [8:0] rx_count;
    wire [7:0] host_wdata, host_rdata;
    wire [1:0] host_addr;
    wire       host_we, host_re;
    wire [3:0] gpio_out, gpio_oe, gpio_in;

    // TX staging: the FIFO smallcore_axi.v puts in front of the engine
    reg [7:0] stg [0:1023];
    integer   stg_wr = 0, stg_rd = 0;
    wire      tx_valid = stg_rd != stg_wr;
    wire [7:0] tx_data = stg[stg_rd % 1024];
    always @(posedge clk) if (tx_pop) stg_rd <= stg_rd + 1;

    // the completed-transaction count smallcore_axi.v exposes as TX_COMMITTED
    integer committed = 0;
    always @(posedge clk) if (tx_commit) committed <= committed + 1;

    host_engine #(.RX_LOG2(8)) eng (
        .clk(clk), .reset(reset),
        .manual(1'b0), .m_wdata(8'd0), .m_addr(2'd0), .m_we(1'b0), .m_re(1'b0),
        .ctrl_value(ctrl_value), .ctrl_go(ctrl_go),
        .raw_go(raw_go), .raw_write(raw_write), .raw_addr(raw_addr), .raw_wdata(raw_wdata), .raw_pop(raw_pop),
        .tx_valid(tx_valid), .tx_data(tx_data),
        .rx_en(rx_en), .rx_clear(rx_clear), .rx_pop(rx_pop), .rx_rd_idx(rx_rd_idx),
        .status(status), .state(state), .tx_pop(tx_pop), .tx_commit(tx_commit),
        .idle(idle), .idle_tick(idle_tick),
        .raw_busy(raw_busy), .raw_done(raw_done), .raw_rdata(raw_rdata),
        .rx_count(rx_count), .rx_overflow(rx_overflow), .rx_byte(rx_byte), .rx_head(rx_head),
        .host_wdata(host_wdata), .host_addr(host_addr), .host_we(host_we), .host_re(host_re),
        .host_rdata(host_rdata));

    smallcore dut (
        .clk(clk), .reset(reset),
        .host_wdata(host_wdata), .host_addr(host_addr), .host_we(host_we), .host_re(host_re),
        .host_rdata(host_rdata),
        .gpio_in(gpio_in), .gpio_out(gpio_out), .gpio_oe(gpio_oe));

    // pads: each driven or pulled up; the jumper joins pad 0 and pad 3
    wire [3:0] pad_drv = (gpio_oe & gpio_out) | ~gpio_oe;
    wire       jumper  = pad_drv[0] & pad_drv[3];
    assign gpio_in = {jumper, pad_drv[2:1], jumper};

    // host bus monitor: every transaction's rising strobe, oldest first
    reg [15:0] mon [0:4095];             // {we, re, 2'b0, addr[1:0], 2'b0, wdata}
    integer    nmon = 0;
    reg        we_d = 1'b0, re_d = 1'b0;
    always @(posedge clk) begin
        we_d <= host_we;
        re_d <= host_re;
        if ((host_we && !we_d) || (host_re && !re_d)) begin
            mon[nmon % 4096] <= {host_we, host_re, 2'b00, host_addr, 2'b00, host_wdata};
            nmon <= nmon + 1;
        end
    end

    // host.v's timing rules on the strobes the engine makes: >= 4 high, >= 3 low between
    integer hi = 0, lo = 100, rule_errors = 0;
    always @(posedge clk) begin
        if (host_we || host_re) begin
            if (hi == 0 && lo < 3) begin rule_errors = rule_errors + 1; $display("FAIL strobe rose after %0d low clocks", lo); end
            hi = hi + 1; lo = 0;
        end
        else begin
            if (hi != 0 && hi < 4) begin rule_errors = rule_errors + 1; $display("FAIL strobe high only %0d clocks", hi); end
            hi = 0; lo = lo + 1;
        end
        if (reset) lo = 0;
    end

    integer errors = 0;
    task check(input ok, input [8*96-1:0] what);
        begin
            if (ok) $display("PASS  %0s", what);
            else begin $display("FAIL  %0s", what); errors = errors + 1; end
        end
    endtask

    task clocks(input integer n); repeat (n) @(posedge clk); endtask

    task wait_idle;
        integer t;
        begin
            clocks(2);
            t = 0;
            while (!idle && t < 100000) begin @(posedge clk); t = t + 1; end
            if (!idle) begin $display("FAIL  engine never idle"); errors = errors + 1; end
        end
    endtask

    task ctrl(input [7:0] v);
        begin
            @(negedge clk); ctrl_value = v; ctrl_go = 1'b1;
            @(negedge clk); ctrl_go = 1'b0;
            wait_idle;
        end
    endtask

    task raw(input w, input [1:0] a, input [7:0] d, input p, output [7:0] r);
        integer t;
        begin
            @(negedge clk); raw_write = w; raw_addr = a; raw_wdata = d; raw_pop = p; raw_go = 1'b1;
            @(negedge clk); raw_go = 1'b0;
            if (!raw_busy) begin $display("FAIL  raw_busy not set the clock after raw_go"); errors = errors + 1; end
            t = 0;
            while (!raw_done && t < 10000) begin @(posedge clk); #1; t = t + 1; end
            r = raw_rdata;
            @(negedge clk);
        end
    endtask

    task stage(input [7:0] b); begin stg[stg_wr % 1024] = b; stg_wr = stg_wr + 1; end endtask

    task core_reset;
        begin
            @(negedge clk); reset = 1'b1; clocks(4); @(negedge clk); reset = 1'b0;
            committed = 0; stg_rd = stg_wr;
            clocks(10);
        end
    endtask

    task wait_halted;
        integer t; reg [7:0] r;
        begin
            t = 0; r = 0;
            while (!r[2] && t < 200) begin raw(1'b0, 2'd2, 8'd0, 1'b0, r); t = t + 1; end
            check(r[2], "core halted");
        end
    endtask

    reg [15:0] prog [0:255];
    integer    words, i, k, f, first;
    reg [7:0]  r, r2;

    initial begin
        f = $fopen("params.txt", "r");
        i = $fscanf(f, "%d", words);
        $fclose(f);
        $readmemh("prog.mem", prog);

        clocks(40);
        reset = 1'b0;
        clocks(10);

        // 1. raw reads of STATUS and CONTROL out of reset: slot 0 halts at once
        raw(1'b0, 2'd2, 8'd0, 1'b0, r);
        check(r == 8'h05, "raw_read STATUS after reset = 0x05 (halted, rx_empty)");
        check(status == r[2:0], "engine status agrees with raw STATUS");
        raw(1'b0, 2'd3, 8'd0, 1'b0, r);
        check(r == 8'h00, "raw_read CONTROL after reset = 0x00");

        // 2. CONTROL by value through ctrl_go, and by raw write
        ctrl(8'h08);
        raw(1'b0, 2'd3, 8'd0, 1'b0, r);
        check(r == 8'h08, "ctrl 0x08 then raw_read CONTROL = 0x08");
        raw(1'b1, 2'd3, 8'h0D, 1'b0, r);
        raw(1'b0, 2'd3, 8'd0, 1'b0, r);
        check(r == 8'h0D, "raw_write CONTROL 0x0D then raw_read CONTROL = 0x0D");

        // 3. prefill: 6 bytes staged at the halted slot 0 commit exactly 4, the core's FIFO full
        core_reset;
        for (k = 0; k < 6; k = k + 1) stage(8'h10 + k);
        clocks(400);
        raw(1'b0, 2'd2, 8'd0, 1'b0, r);
        check(committed == 4, "prefill: committed = 4 of 6 staged");
        check(r[1] == 1'b1, "prefill: raw STATUS tx_full = 1");
        check(status[1] == 1'b1, "prefill: engine status tx_full = 1 (CORE_STATUS)");
        check(stg_wr - stg_rd == 2, "prefill: 2 bytes still staged");
        check(!idle, "prefill: engine not idle with bytes staged");
        clocks(400);
        check(committed == 4, "prefill: still 4 after 400 more clocks");

        // 4. CONTROL jumps ahead of the waiting bytes; then raw ahead of TX, when both are pending
        @(negedge clk); ctrl_value = 8'h00; ctrl_go = 1'b1; raw_write = 1'b0; raw_addr = 2'd3; raw_pop = 1'b0; raw_go = 1'b1;
        @(negedge clk); ctrl_go = 1'b0; raw_go = 1'b0;
        first = nmon;
        while (!raw_done) @(posedge clk);
        clocks(2);
        check(nmon > first && mon[first % 4096][15] && mon[first % 4096][11:10] == 2'd3,
              "priority: the first transaction is the CONTROL write");
        check(raw_rdata == 8'h00, "priority: the raw read follows it (CONTROL reads 0x00)");
        check(committed == 4, "priority: no TX byte went ahead of CONTROL or raw");

        // 5. RAM load: CONTROL 0x20, the program's bytes low then high, no prefill limit
        core_reset;
        ctrl(8'h20);
        raw(1'b0, 2'd3, 8'd0, 1'b0, r);
        check(r == 8'h20, "load: CONTROL reads 0x20");
        for (k = 0; k < words; k = k + 1) begin
            stage(prog[k][7:0]);
            stage(prog[k][15:8]);
        end
        wait_idle;
        check(committed == 2 * words, "load: committed = every program byte (2 x words)");
        check(stg_wr == stg_rd, "load: staging empty");
        check(dut.host_i.prog_words == words, "load: host.v counted every word");
        raw(1'b0, 2'd2, 8'd0, 1'b0, r);
        check(r[1] == 1'b0, "load: the TX FIFO never filled (bytes went to the loader)");
        ctrl(8'h10);
        raw(1'b0, 2'd3, 8'd0, 1'b0, r);
        check(r == 8'h10, "load: CONTROL reads 0x10 once run");

        // 6. the RAM program (spi_duplex_msb) round-trips a byte through the jumper into the RX ring
        @(negedge clk); rx_en = 1'b1;
        stage(8'h96);
        wait_halted;
        clocks(40);
        check(rx_count == 1 && rx_head == 8'h96, "RAM SPI: RX ring holds 0x96");
        ctrl(8'h10); stage(8'h3C); wait_halted; clocks(40);
        ctrl(8'h10); stage(8'hA5); wait_halted; clocks(40);
        check(rx_count == 3, "RX ring: 3 bytes");
        @(negedge clk); rx_rd_idx = 8'd2; clocks(2);
        check(rx_byte == 8'hA5, "RX ring: peek index 2 = 0xA5");
        @(negedge clk); rx_rd_idx = 8'd0; rx_pop = 1'b1; @(negedge clk); rx_pop = 1'b0; clocks(2);
        check(rx_count == 2 && rx_head == 8'h3C && rx_byte == 8'h3C, "RX ring: pop leaves 0x3C at the head");
        @(negedge clk); rx_clear = 1'b1; @(negedge clk); rx_clear = 1'b0; clocks(2);
        check(rx_count == 0, "RX ring: clear empties it");

        // 7. raw RX_DATA read with pop, the drain off
        @(negedge clk); rx_en = 1'b0;
        ctrl(8'h10); stage(8'h5A); wait_halted; clocks(40);
        raw(1'b0, 2'd2, 8'd0, 1'b0, r);
        check(r[0] == 1'b0, "raw: STATUS not rx_empty with the drain off");
        raw(1'b0, 2'd1, 8'd0, 1'b0, r);
        raw(1'b0, 2'd1, 8'd0, 1'b0, r2);
        check(r == 8'h5A && r2 == 8'h5A, "raw: RX_DATA read without pop twice = 0x5A");
        raw(1'b0, 2'd1, 8'd0, 1'b1, r);
        check(r == 8'h5A, "raw: RX_DATA read with pop = 0x5A");
        raw(1'b0, 2'd2, 8'd0, 1'b0, r);
        check(r[0] == 1'b1, "raw: STATUS rx_empty after the pop");
        check(rx_count == 0, "raw: the popped byte never reached the ring");

        // 8. the same program from ROM slot 8 gives the same byte: the RAM copy is faithful
        @(negedge clk); rx_en = 1'b1;
        ctrl(8'h08); stage(8'hC3); wait_halted; clocks(40);
        check(rx_count == 1 && rx_head == 8'hC3, "ROM slot 8 SPI: RX ring holds 0xC3");

        // 9. a raw request dropped by reset still finishes
        @(negedge clk); raw_write = 1'b0; raw_addr = 2'd2; raw_pop = 1'b0; raw_go = 1'b1; reset = 1'b1;
        @(negedge clk); raw_go = 1'b0;
        clocks(3);
        check(!raw_busy, "raw: a request during reset leaves no busy");
        @(negedge clk); reset = 1'b0; clocks(10);

        check(rule_errors == 0, "host.v strobe rules held on every transaction");
        if (errors == 0) $display("RESULT PASS");
        else             $display("RESULT FAIL %0d", errors);
        $finish;
    end
endmodule
