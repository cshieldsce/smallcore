// xsim bench for the ARM host path below the AXI clock converter: AXI4-Lite master tasks ->
// smallcore_axi.v (its host_engine) -> rtl/smallcore.v -> smallcore_pads.v -> the pins, on the
// core clock. The tasks use the registers the way the ARM driver does (arm/smallcore.c).
// Run by run_axi_sim.py, which writes params.txt (mode n rx_n ack_at limit) and the inputs:
//   0  registers: ID, VERSION, SCRATCH, CTRL, SLOT, RAW, staging full/flush, TX_COMMITTED, flags
//   1  SPI from ROM slot 8 on PMOD B with the jumper: tx.mem's n bytes, each run and read back
//   2  RAM load of prog.mem (n words, spi_duplex_msb), then rx_n bytes from tx.mem through it
//   3  CAN TX, ROM slot 13 on PMOD A: tx.mem's n host bytes; the other node ACKs from clock
//      ack_at after the SOF edge for 8 clocks; ctx.txt and bus.txt from RUN
//   4  CAN RX, ROM slot 15: rx.mem's rx_n bits, 8 clocks each, then the RX ring over RX_DATA
//   5  CAN RX, ROM slot 14 (can_rx_crc): the polynomial staged first, then as 4
// Self-checks print PASS/FAIL; RESULT lines carry what run_axi_sim.py checks.
`timescale 1ns / 1ps
module tb;
    reg clk = 1'b0;
    always #62.5 clk = ~clk;

    reg aresetn = 1'b0;

    reg  [7:0]  awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
    reg  [31:0] wdata = 0;
    reg  [3:0]  wstrb = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;

    wire       core_reset, pad_sel;
    wire [7:0] host_wdata, host_rdata;
    wire [1:0] host_addr;
    wire       host_we, host_re;
    wire [2:0] core_status;
    wire [3:0] gpio_out, gpio_oe, gpio_in;

    smallcore_axi #(.CORE_DIV(8), .TX_DEPTH_LOG2(10), .RX_LOG2(8)) axi (
        .aclk(clk), .aresetn(aresetn), .locked(1'b1),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .core_reset(core_reset), .pad_sel(pad_sel),
        .host_wdata(host_wdata), .host_addr(host_addr), .host_we(host_we), .host_re(host_re),
        .host_rdata(host_rdata), .core_status(core_status));

    smallcore dut (
        .clk(clk), .reset(core_reset),
        .host_wdata(host_wdata), .host_addr(host_addr), .host_we(host_we), .host_re(host_re),
        .host_rdata(host_rdata),
        .gpio_in(gpio_in), .gpio_out(gpio_out), .gpio_oe(gpio_oe));

    // the pins: PMOD B pulled up, the jumper from pin 1 to pin 4; the CAN bus the AND of CTX and
    // the other node, CRX the bus
    wire can_ctx;
    reg  ext = 1'b1;
    wire bus = can_ctx & ext;
    wire [3:0] jb;
    // the jumper: pad 3 follows pad 0 (the SPI programs release pad 3 before reading it; a weak
    // drive would lose to the pull-up, which is the stronger of the two)
    pullup (jb[0]); pullup (jb[1]); pullup (jb[2]);
    assign jb[3] = jb[0];

    smallcore_pads pads (
        .clk(clk), .pad_sel(pad_sel), .gpio_out(gpio_out), .gpio_oe(gpio_oe), .gpio_in(gpio_in),
        .can_ctx(can_ctx), .can_crx(bus), .ja_gpio(3'b111), .jb(jb));

    integer errors = 0;

    // ---------------------------------------------------------------- AXI4-Lite master
    // ordering monitor, every mode: a response only after its request transfer(s)
    reg aw_done = 0, w_done = 0, ar_done = 0;
    always @(posedge clk) begin
        if (bvalid && !(aw_done && w_done)) begin errors = errors + 1; $display("FAIL  B before its AW/W transfer"); end
        if (rvalid && !ar_done)             begin errors = errors + 1; $display("FAIL  R before its AR transfer"); end
        if (awvalid && awready) aw_done <= 1;
        if (wvalid && wready)   w_done  <= 1;
        if (arvalid && arready) ar_done <= 1;
        if (bvalid && bready)   begin aw_done <= 0; w_done <= 0; end
        if (rvalid && rready)   ar_done <= 0;
    end

    // a write whose W arrives `lag` clocks after AW, with byte strobes
    task axi_write_lag(input [7:0] a, input [31:0] d, input [3:0] s, input integer lag);
        begin
            @(negedge clk);
            awaddr = a; awvalid = 1;
            repeat (lag) @(negedge clk);
            if (awready) begin $display("FAIL  AW accepted without W"); errors = errors + 1; end
            wdata = d; wstrb = s; wvalid = 1;
            while (awvalid || wvalid) begin
                @(posedge clk);
                if (awvalid && awready) awvalid <= 0;
                if (wvalid && wready)   wvalid  <= 0;
                #1;
            end
            bready = 1;
            while (!bvalid) @(posedge clk);
            @(posedge clk); #1 bready = 0;
        end
    endtask

    task axi_write(input [7:0] a, input [31:0] d);
        integer t;
        begin
            @(negedge clk);
            awaddr = a; awvalid = 1; wdata = d; wstrb = 4'hF; wvalid = 1;
            t = 0;
            while (awvalid || wvalid) begin
                @(posedge clk);
                if (awvalid && awready) awvalid <= 0;
                if (wvalid && wready)   wvalid  <= 0;
                t = t + 1;
                if (t > 50) begin $display("FAIL  AXI write %02x stuck", a); errors = errors + 1; awvalid <= 0; wvalid <= 0; end
                #1;
            end
            bready = 1;
            while (!bvalid) @(posedge clk);
            @(posedge clk); #1 bready = 0;
        end
    endtask

    task axi_read(input [7:0] a, output [31:0] d);
        begin
            @(negedge clk);
            araddr = a; arvalid = 1;
            @(posedge clk);
            while (!arready) @(posedge clk);
            #1 arvalid = 0; rready = 1;
            while (!rvalid) @(posedge clk);
            d = rdata;
            @(posedge clk); #1 rready = 0;
        end
    endtask

    // ---------------------------------------------------------------- the register map
    localparam [7:0] ID = 8'h00, VERSION = 8'h04, SCRATCH = 8'h08, CTRL = 8'h0C, STATUS = 8'h10,
                     COMMAND = 8'h14, SLOT = 8'h18, TX_DATA = 8'h1C, TX_COUNT = 8'h20,
                     RX_DATA = 8'h24, RX_COUNT = 8'h28, RAW = 8'h2C, CORE_STATUS = 8'h30,
                     TX_COMMITTED = 8'h34;

    task check(input ok, input [8*96-1:0] what);
        begin
            if (ok) $display("PASS  %0s", what);
            else begin $display("FAIL  %0s", what); errors = errors + 1; end
        end
    endtask

    reg [31:0] v;
    reg [2:0]  ctrl_keep = 3'b000;      // CTRL[2:1], kept across resets

    // the driver's operations, as arm/smallcore.c does them
    task sc_reset;
        begin
            axi_write(CTRL, ctrl_keep | 32'h1);
            axi_write(CTRL, ctrl_keep);
        end
    endtask


    task wait_reg(input [7:0] a, input [31:0] mask, input [31:0] want, input integer tries);
        integer t;
        begin
            t = 0;
            axi_read(a, v);
            while ((v & mask) != want && t < tries) begin axi_read(a, v); t = t + 1; end
            if ((v & mask) != want) begin
                $display("FAIL  register %02x = %08x, waited for (& %08x) == %08x", a, v, mask, want);
                errors = errors + 1;
            end
        end
    endtask

    task wait_idle; wait_reg(STATUS, 32'h1, 32'h1, 20000); endtask

    // RUN, then until STATUS[6] clears: CONTROL written and STATUS read again after it
    task sc_run(input [7:0] s);
        begin
            axi_write(SLOT, s);
            axi_write(COMMAND, 32'h1);
            wait_reg(STATUS, 32'h40, 32'h0, 1000);
        end
    endtask


    // RUN once the prefill is the core's: TX_COMMITTED >= min(n, 4), and with n >= 4 tx_full
    task wait_prefill(input integer n);
        integer t, need;
        begin
            need = n < 4 ? n : 4;
            t = 0;
            axi_read(TX_COMMITTED, v);
            while (v < need && t < 1000) begin axi_read(TX_COMMITTED, v); t = t + 1; end
            check(v >= need, "prefill: TX_COMMITTED >= min(n, 4) before RUN");
            if (n >= 4) begin
                axi_read(CORE_STATUS, v);
                check(v[1], "prefill: CORE_STATUS tx_full before RUN");
            end
        end
    endtask

    task raw_op(input w, input [1:0] a, input [7:0] d, input p, output [7:0] r);
        begin
            axi_write(RAW, {14'd0, p, w, 6'd0, a, d});
            wait_reg(RAW, 32'h8000_0000, 32'h8000_0000, 1000);
            r = v[7:0];
            check(!v[30], "raw: not busy once done");
        end
    endtask

    task wait_halted; wait_reg(CORE_STATUS, 32'h4, 32'h4, 20000); endtask

    // ---------------------------------------------------------------- stimulus and traces
    reg [7:0]  txm [0:1023];
    reg        rxm [0:1023];
    reg [15:0] prog [0:255];
    integer mode, n, rx_n, ack_at, limit, cyc, sof, start, i, k, f, f_ctx, f_bus, count;
    reg [7:0] r;

    always @(posedge clk) cyc <= cyc + 1;

    always @(posedge clk) begin
        if (mode == 3 && sof < 0 && start > 0 && cyc > start && !bus) sof <= cyc;
        if (mode == 3 && ack_at > 0 && sof >= 0)
            ext <= !(cyc - sof >= ack_at && cyc - sof < ack_at + 8);
        if ((mode == 4 || mode == 5) && start > 0 && cyc >= start)
            ext <= ((cyc - start) / 8 < rx_n) ? rxm[(cyc - start) / 8] : 1'b1;
        if (start > 0 && (mode == 3 || mode == 4 || mode == 5)) begin
            $fwrite(f_ctx, "%0d", can_ctx);
            $fwrite(f_bus, "%0d", bus);
        end
    end

    initial begin
        cyc = 0; sof = -1; start = 0;
        f = $fopen("params.txt", "r");
        i = $fscanf(f, "%d %d %d %d %d", mode, n, rx_n, ack_at, limit);
        $fclose(f);
        if (mode != 0 && mode != 4) $readmemh("tx.mem", txm);
        if (mode == 2) $readmemh("prog.mem", prog);
        if (mode == 4 || mode == 5) $readmemb("rx.mem", rxm);
        f_ctx = $fopen("ctx.txt", "w");
        f_bus = $fopen("bus.txt", "w");

        repeat (20) @(posedge clk);
        aresetn = 1'b1;
        repeat (10) @(posedge clk);

        if (mode == 0) begin
            axi_read(ID, v);       check(v == 32'h53434F52, "ID = 0x53434F52");
            axi_read(VERSION, v);  check(v == 32'h00010A08, "VERSION = 0x00010A08 (ABI 1, staging 2^10, CORE_DIV 8)");
            axi_write(SCRATCH, 32'hA5A55A5A); axi_read(SCRATCH, v); check(v == 32'hA5A55A5A, "SCRATCH round trip");
            axi_write_lag(SCRATCH, 32'h12345678, 4'hF, 3); axi_read(SCRATCH, v); check(v == 32'h12345678, "SCRATCH, W 3 clocks after AW");
            axi_write_lag(SCRATCH, 32'hDEADBEEF, 4'b0101, 1); axi_read(SCRATCH, v); check(v == 32'h12AD56EF, "SCRATCH byte strobes 0101");
            axi_write(ID, 32'hFFFFFFFF); axi_read(ID, v); check(v == 32'h53434F52, "ID is read-only");
            axi_read(STATUS, v);   check(v[5] && v[0], "STATUS: locked, idle out of reset");
            axi_read(CORE_STATUS, v); check(v == 32'h5, "CORE_STATUS = 0x5 (halted, rx_empty) at slot 0");
            axi_write(CTRL, 32'h6); axi_read(CTRL, v); check(v == 32'h6, "CTRL reads back 0x6");
            axi_write(CTRL, 32'h0);
            axi_write(SLOT, 32'h2D); axi_read(SLOT, v); check(v == 32'h2D, "SLOT reads back 0x2D");

            raw_op(1'b0, 2'd2, 8'd0, 1'b0, r); check(r == 8'h05, "raw_read STATUS = 0x05");
            raw_op(1'b0, 2'd3, 8'd0, 1'b0, r); check(r == 8'h00, "raw_read CONTROL = 0x00");
            raw_op(1'b1, 2'd3, 8'h0D, 1'b0, r);
            raw_op(1'b0, 2'd3, 8'd0, 1'b0, r); check(r == 8'h0D, "raw_write CONTROL 0x0D, raw_read = 0x0D");
            sc_run(8'h07);
            axi_read(STATUS, v); check(!v[6], "RUN busy clear once sc_run returns");
            wait_idle;
            raw_op(1'b0, 2'd3, 8'd0, 1'b0, r); check(r == 8'h07, "RUN with SLOT 7: raw_read CONTROL = 0x07");
            axi_read(STATUS, v); check(v[3] && !v[4], "STATUS: raw done, not busy");

            // staging: 4 to the core's FIFO at the halted slot 0, 1024 staged, the rest dropped
            sc_reset;
            for (k = 0; k < 1030; k = k + 1) axi_write(TX_DATA, k & 8'hFF);
            repeat (200) @(posedge clk);
            axi_read(TX_COMMITTED, v); check(v == 4, "fill: TX_COMMITTED = 4");
            axi_read(CORE_STATUS, v);  check(v[1], "fill: CORE_STATUS tx_full");
            axi_read(TX_COUNT, v);     check(v == 1024, "fill: TX_COUNT = 1024");
            axi_read(STATUS, v);       check(v[1] && !v[0], "fill: STATUS staging full, not idle");
            axi_write(COMMAND, 32'h8);
            axi_read(TX_COMMITTED, v); check(v == 0, "COMMAND[3]: TX_COMMITTED cleared");
            axi_read(TX_COUNT, v);     check(v == 1024, "COMMAND[3]: staging kept");
            axi_write(COMMAND, 32'h4);
            axi_read(TX_COUNT, v);     check(v == 0, "COMMAND[2] flush: TX_COUNT = 0");
            axi_read(STATUS, v);       check(!v[1] && v[0], "flush: not full, idle");
            axi_write(TX_DATA, 32'h99);
            sc_reset;
            axi_read(TX_COUNT, v);     check(v == 0, "core reset empties staging");
            axi_read(TX_COMMITTED, v); check(v == 0, "core reset clears TX_COMMITTED");
            axi_read(CORE_STATUS, v);  check(v == 32'h5, "core reset empties the core's TX FIFO");
            axi_read(RX_DATA, v);      check(v == 0, "RX_DATA on an empty ring: valid 0");
            axi_read(RX_COUNT, v);     check(v == 0, "RX_COUNT = 0");
        end

        if (mode == 1) begin
            ctrl_keep = 3'b110;             // PMOD B, RX drain on
            for (k = 0; k < n; k = k + 1) begin
                sc_reset;
                axi_write(TX_DATA, txm[k]);
                wait_prefill(1);
                sc_run(8'h08);
                wait_halted;
                wait_reg(RX_COUNT, 32'hFFFF, 32'h1, 1000);
                axi_read(RX_DATA, v);
                $display("RESULT spi sent %02x got %03x", txm[k], v[8:0]);
                check(v[8:0] == {1'b1, txm[k]}, "SPI slot 8 over PMOD B: the byte back through the jumper");
            end
        end

        if (mode == 2) begin
            ctrl_keep = 3'b110;
            sc_reset;
            sc_run(8'h20);
            wait_idle;
            raw_op(1'b0, 2'd3, 8'd0, 1'b0, r); check(r == 8'h20, "load: CONTROL = 0x20 before the bytes");
            for (k = 0; k < n; k = k + 1) begin
                axi_write(TX_DATA, prog[k][7:0]);
                axi_write(TX_DATA, prog[k][15:8]);
            end
            wait_reg(TX_COMMITTED, 32'hFFFF, 2 * n, 20000);
            wait_idle;
            check(dut.host_i.prog_words == n, "load: host.v holds every word");
            axi_read(CORE_STATUS, v); check(!v[1], "load: the TX FIFO never filled");
            sc_run(8'h10);
            wait_idle;
            raw_op(1'b0, 2'd3, 8'd0, 1'b0, r); check(r == 8'h10, "load: CONTROL = 0x10 once run");
            for (k = 0; k < rx_n; k = k + 1) begin
                if (k > 0) sc_run(8'h10);
                axi_write(TX_DATA, txm[k]);
                wait_halted;
                wait_reg(RX_COUNT, 32'hFFFF, 32'h1, 1000);
                axi_read(RX_DATA, v);
                $display("RESULT ram sent %02x got %03x", txm[k], v[8:0]);
                check(v[8:0] == {1'b1, txm[k]}, "RAM-loaded SPI: the byte back through the jumper");
            end
        end

        if (mode == 3) begin
            ctrl_keep = 3'b010;             // PMOD A, RX drain on
            sc_reset;
            axi_write(COMMAND, 32'h2);
            for (k = 0; k < n; k = k + 1) axi_write(TX_DATA, txm[k]);
            wait_prefill(n);
            axi_read(TX_COMMITTED, v);
            $display("RESULT committed before RUN %0d", v);
            axi_read(CORE_STATUS, v);
            check(v[2], "before RUN: CORE_STATUS halted (slot 0)");
            axi_write(SLOT, 8'd13);
            @(negedge clk); start = cyc;
            axi_write(COMMAND, 32'h1);
            axi_read(STATUS, v);
            check(v[6], "RUN busy right after COMMAND RUN");
            wait_reg(STATUS, 32'h40, 32'h0, 1000);
            axi_read(CORE_STATUS, v);
            check(!v[2], "RUN busy clear: CORE_STATUS shows slot 13 running, not slot 0's halt");
            repeat (limit) @(posedge clk);
            axi_read(TX_COMMITTED, v); $display("RESULT committed after %0d", v);
            axi_read(CORE_STATUS, v);  $display("RESULT halted %0d", v[2]);
            axi_read(RX_COUNT, v); count = v;
            $write("RESULT rx");
            for (k = 0; k < count; k = k + 1) begin axi_read(RX_DATA, v); $write(" %02x", v[7:0]); end
            $write("\n");
        end

        if (mode == 4 || mode == 5) begin
            ctrl_keep = 3'b010;
            sc_reset;
            axi_write(COMMAND, 32'h2);
            if (mode == 5) begin
                for (k = 0; k < n; k = k + 1) axi_write(TX_DATA, txm[k]);
                wait_prefill(n);
            end
            sc_run(mode == 5 ? 8'd14 : 8'd15);
            wait_idle;
            @(negedge clk); start = cyc;
            repeat (limit) @(posedge clk);
            axi_read(CORE_STATUS, v);  $display("RESULT halted %0d", v[2]);
            $write("RESULT rx");
            axi_read(RX_DATA, v);
            while (v[8]) begin $write(" %02x", v[7:0]); axi_read(RX_DATA, v); end
            $write("\n");
        end

        $fclose(f_ctx);
        $fclose(f_bus);
        if (errors == 0) $display("RESULT PASS");
        else             $display("RESULT FAIL %0d", errors);
        $finish;
    end
endmodule
