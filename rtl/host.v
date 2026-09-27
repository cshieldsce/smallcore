// Host register block: the developer's side of the chip. Four registers on
// a 2-bit address, a write strobe and a read strobe, both taken as rising
// edges so a host on GPIO that holds a line for a few clocks makes exactly
// one transaction. Timing rules: a strobe is held >= 3 clocks high and >= 3
// low between strobes, and low for >= 3 clocks after reset before the first
// one; wdata and addr are set before it rises and held until it falls. rdata
// is combinational on addr.
//
//   addr  write (we rises)                      read (rdata)
//   0     TX_DATA: push wdata, dropped if full    0
//   1     RX_DATA: -                              RX head; re rising pops it
//   2     STATUS:  -                              {5'b0, halted, tx_full, rx_empty}
//   3     CONTROL: sel <= wdata[3:0], restart     {4'b0, sel}
module host (
    input            clk, reset,
    input      [7:0] wdata,
    input      [1:0] addr,
    input            we, re,
    input            tx_full, rx_empty, halted,
    input      [7:0] rx_data,
    output reg [7:0] rdata,
    output           tx_push, rx_pop, restart,
    output reg [3:0] sel
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

    assign we_rise = we_sync[1] & ~we_sync[2];
    assign re_rise = re_sync[1] & ~re_sync[2];

    // CONTROL takes wdata[3:0], the slot; the upper bits are for later
    wire _unused_wdata;
    assign _unused_wdata = &{wdata[7:4], 1'b0};

    assign tx_push = we_rise && (addr == TX_DATA);
    assign restart = we_rise && (addr == CONTROL);
    assign rx_pop  = re_rise && (addr == RX_DATA);

    always @* begin
        case (addr)
            TX_DATA: rdata = 8'h00;
            RX_DATA: rdata = rx_data;
            STATUS:  rdata = {5'b0, halted, tx_full, rx_empty};
            CONTROL: rdata = {4'b0, sel};
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            we_sync <= 3'b111;
            re_sync <= 3'b111;
            sel     <= 4'd0;
        end
        else begin
            we_sync <= {we_sync[1:0], we};
            re_sync <= {re_sync[1:0], re};
            if (restart) begin
                sel <= wdata[3:0];
            end
        end
    end

endmodule
