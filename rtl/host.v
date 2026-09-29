// Host register block: the developer's side of the chip. Four registers on
// a 2-bit address, a write strobe and a read strobe, both taken as rising
// edges so a host on GPIO that holds a line for a few clocks makes exactly
// one transaction. Timing rules: a strobe is held >= 4 clocks high and >= 3
// low between strobes, and low for >= 3 clocks after reset before the first
// one; wdata and addr are set before it rises and held until it falls. The
// transaction decodes addr and wdata straight from the pins on the second
// clock after the strobe is first captured, so a strobe that rose just after
// an edge and lasted 3 clocks would fall on that very clock: 4 leaves one.
// rdata is combinational on addr.
//
//   addr  write (we rises)                      read (rdata)
//   0     TX_DATA: push wdata, dropped if full    0
//   1     RX_DATA: -                              RX head, 0 while empty; re rising pops it
//   2     STATUS:  -                              {5'b0, halted, tx_full, rx_empty}
//   3     CONTROL: sel <= wdata[3:0], restart     {4'b0, sel}
module host (
    input             clk, reset,
    input      [7:0]  wdata,
    input      [1:0]  addr,
    input             we, re,
    input             tx_full, rx_empty, halted,
    input      [7:0]  rx_data,
    output reg [7:0]  rdata,
    output            tx_push, rx_pop, restart,
    output reg [3:0]  sel,
    output reg        load_mode,
    output reg        ram_select, 
    output            prog_we,
    output reg [7:0]  prog_addr,
    output     [15:0] prog_wdata,
    output reg [8:0]  prog_words
);
    localparam [1:0] TX_DATA = 2'd0;
    localparam [1:0] RX_DATA = 2'd1;
    localparam [1:0] STATUS  = 2'd2;
    localparam [1:0] CONTROL = 2'd3;

    // [0] <- pin, [1] synchronized, [2] the clock before: a rise is [1] & ~[2].
    // Reset to all ones, as if the strobe had always been high, so a strobe
    // held high through reset makes no edge until it really drops and rises.
    reg [2:0] we_sync;
    reg [2:0] re_sync;

    wire we_rise;
    wire re_rise;

    assign we_rise = we_sync[1] & ~we_sync[2]; // did a host write occur?
    assign re_rise = re_sync[1] & ~re_sync[2]; // did a host read occur?

    wire rom_cmd;
    wire run_ram_cmd;
    wire load_cmd;

    assign rom_cmd     = (wdata[7:4] == 4'd0);
    assign run_ram_cmd = (wdata == 8'h10);
    assign load_cmd    = (wdata == 8'h20);

    reg [7:0] prog_low;
    reg       byte_phase;
    wire      control_write;
    wire      prog_byte;

    assign control_write = we_rise && (addr == CONTROL);
    assign prog_byte     = we_rise && (addr == TX_DATA) && load_mode; 
    assign tx_push       = we_rise && (addr == TX_DATA) && !load_mode;
    assign rx_pop        = re_rise && (addr == RX_DATA);
    assign restart       = control_write && (rom_cmd || run_ram_cmd || load_cmd);
    
    assign prog_wdata = { wdata, prog_low };
    assign prog_we    = prog_byte && byte_phase && (prog_words < 9'd256);

    always @(*) begin
        case (addr)
            TX_DATA: rdata = 8'h00;
            RX_DATA: rdata = rx_empty ? 8'h00 : rx_data;  // never the FIFO's memory: 0 while empty
            STATUS:  rdata = {5'b0, halted, tx_full, rx_empty};
            CONTROL: rdata = {4'b0, sel};
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            we_sync    <= 3'b111;
            re_sync    <= 3'b111;
            sel        <= 4'd0;
            load_mode  <= 1'd0;
            ram_select <= 1'd0;
            prog_addr  <= 8'd0;
            prog_words <= 9'd0;
            prog_low   <= 8'd0;
            byte_phase <= 1'd0;
        end
        else begin
            // Edge detector for read and writes
            we_sync <= {we_sync[1:0], we};
            re_sync <= {re_sync[1:0], re};
            
            if (control_write) begin
                //ROM
                if (rom_cmd) begin
                    ram_select <= 1'd0;
                    load_mode  <= 1'd0;
                    byte_phase <= 1'd0;
                    // select program in ROM
                    sel <= wdata[3:0];
                end
                
                // RAM
                else if (run_ram_cmd) begin
                    load_mode  <= 1'd0;
                    ram_select <= 1'd1;
                    byte_phase <= 1'd0;
                end 

                // Loading
                else if (load_cmd) begin
                    load_mode  <= 1'd1;
                    ram_select <= 1'd1;

                    prog_addr  <= 8'd0;
                    prog_words <= 9'd0;
                    byte_phase <= 1'd0;
                    prog_low   <= 8'd0;
                end
            end
            else if (prog_byte && prog_words < 9'd256) begin
                if (byte_phase == 1'd0) begin
                    // wdata is on LOW byte
                    prog_low   <= wdata;
                    byte_phase <= ~byte_phase;
                end
                else begin
                    // wdata is on HIGH byte
                    byte_phase <= ~byte_phase;
                    prog_words <= prog_words + 9'd1;
                    prog_addr  <=  prog_addr + 8'd1;
                end
            end
        end
    end

endmodule
