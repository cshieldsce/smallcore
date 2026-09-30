module ram (
    input         clk,
    input         we,
    input  [7:0]  waddr,
    input  [15:0] wdata,
    input  [7:0]  raddr,
    output [15:0] rdata
);

    reg [15:0] mem [0:255];

    always @(posedge clk) begin
        if (we) begin
            mem[waddr] <= wdata;   // Write data to memory
        end
    end

    assign rdata = mem[raddr];     // Read data from memory

endmodule