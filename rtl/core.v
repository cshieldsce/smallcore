module core(
    input             clk, reset,
    input             tx_empty, rx_full,
    input      [15:0] imem_word,
    input      [8:0]  program_words,
    input      [3:0]  gpio_in,
    output     [7:0]  imem_addr,
    output     [3:0]  gpio_oe,
    output reg [3:0]  gpio_out
);
    // opcodes
    localparam [2:0] OP_NOP_SET = 3'b000;
    localparam [2:0] OP_SHIFT   = 3'b001;
    localparam [2:0] OP_FIFO    = 3'b010;
    localparam [2:0] OP_JMP     = 3'b011;
    localparam [2:0] OP_CONFIG  = 3'b100;
    localparam [2:0] OP_WAIT    = 3'b101;
    localparam [2:0] OP_SKIP    = 3'b110;

    // config
    localparam [1:0] CFG_SHIFT_DIR = 2'd0;
    localparam [1:0] CFG_OD_01     = 2'd1;
    localparam [1:0] CFG_OD_23     = 2'd2;
    
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

    // own decode
    wire       shift_select;
    wire       fifo_select;
    wire [1:0] config_field;
    wire [1:0] config_value;
    wire [1:0] input_pin;
    wire [2:0] skip_bit;
    wire       level;

    assign shift_select = own[1];
    assign fifo_select  = own[0];
    assign config_field = own[3:2];
    assign config_value = own[1:0];
    assign input_pin    = own[3:2];
    assign skip_bit     = own[3:1];
    assign level        = own[0];

    wire halted;
    wire issue;
    wire stall;
    wire last;

    assign halted = (pc >= program_words);
    assign issue  = !halted && (delay_counter == 5'd0);

    assign stall =
        issue &&
        (
            (is_fifo && (fifo_select ? rx_full : tx_empty)) ||
            (is_wait && (gpio_in[input_pin] != level))
        );

    assign last = issue ? (delay == 5'd0) : (delay_counter == 5'd1);

    wire pc_en;
    assign pc_en = last && !stall;

    wire gpio_en;
    assign gpio_en = issue && !stall && side && !is_jmp;

    reg       shift_dir;
    reg [3:0] open_drain;
    wire      cfg_en;

    assign cfg_en = issue && is_config;

    assign gpio_oe = ~(open_drain & gpio_out);

    always @(posedge clk) begin
        if (reset) begin            
            // Reset sets PC=0, Counter=0, GPIO=1111 
            pc            <= 9'd0;
            delay_counter <= 5'd0;
            gpio_out      <= 4'b1111;
            shift_dir     <= 1'b0;
            open_drain    <= 4'b0000;
        end
        else begin
            // Counter
            if (issue && !stall) begin
                delay_counter <= delay;
            end
            else if (delay_counter > 5'd0) begin
                delay_counter <= delay_counter - 5'd1;
            end

            // PC
            if (pc_en && (is_nop_set || is_config)) begin
                pc <= pc + 9'd1;
            end

            // GPIO
            if (gpio_en) begin
                gpio_out[side_pin] <= side_val;
            end 

            // Config
            if (cfg_en) begin
                case (config_field)
                    CFG_SHIFT_DIR : begin
                        shift_dir <= config_value[0];
                    end
                    CFG_OD_01 : begin
                        open_drain[1:0] <= config_value;
                    end
                    CFG_OD_23 : begin
                        open_drain[3:2] <= config_value;
                    end
                    default: begin
                    end
                endcase
            end
        end
    end

endmodule