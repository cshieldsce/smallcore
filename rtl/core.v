module core(
    input  clk, reset,
    input  [15:0] mem_word,
    output [7:0]  imem_addr,
    output reg [3:0]  gpio
);

    reg  [8:0] pc;
    reg  [4:0] delay_counter;

    wire [2:0] opcode;
    wire [4:0] delay;
    wire [7:0] operand;

    assign opcode  = imem_word[15:13];
    assign delay   = imem_word[12:8];
    assign operand = imem_word[7:0];

    assign imem_addr = pc[7:0];

endmodule