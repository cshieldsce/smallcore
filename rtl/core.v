module core(
    input  clk, reset,
    input  [15:0] imem_word,
    output [7:0]  imem_addr,
    output reg [3:0]  gpio
);
    // op codes
    localparam OP_NOP_SET = 3'b000;
    localparam OP_SHIFT   = 3'b001;
    localparam OP_FIFO    = 3'b010;
    localparam OP_JMP     = 3'b011;
    localparam OP_CONFIG  = 3'b100;
    localparam OP_WAIT    = 3'b101;
    localparam OP_SKIP    = 3'b110;

    reg  [8:0] pc;
    reg  [4:0] delay_counter;

    wire [2:0] opcode;
    wire [4:0] delay;
    wire [7:0] operand;

    assign opcode    = imem_word[15:13];
    assign delay     = imem_word[12:8];
    assign operand   = imem_word[7:0];

    assign imem_addr = pc[7:0];

    // operand fields
    wire       side;
    wire [1:0] side_pin;
    wire       side_val;
    wire [3:0] own;

    assign side     = operand[7];
    assign side_pin = operand[6:5];
    assign side_val = operand[4];
    assign own      = operand[3:0];

    // instruction wires
    wire is_nop_set;
    wire is_shift;
    wire is_fifo;
    wire is_jmp;
    wire is_config;
    wire is_wait;
    wire is_skip;

    assign is_nop_set = (opcode == OP_NOP_SET);
    assign is_shift   = (opcode == OP_SHIFT);
    assign is_fifo    = (opcode == OP_FIFO);
    assign is_jmp     = (opcode == OP_JMP);
    assign is_config  = (opcode == OP_CONFIG);
    assign is_wait    = (opcode == OP_WAIT);
    assign is_skip    = (opcode == OP_SKIP);

    always @(posedge clk) begin
        if (reset) begin            
            // Reset sets PC=0, Counter=0, GPIO=1111 
            pc            <= 9'd0;
            delay_counter <= 5'd0;
            gpio          <= 4'b1111;
        end
    end

endmodule