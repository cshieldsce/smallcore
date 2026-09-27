module fifo #(
    parameter DEPTH = 4
) (
    input        clk, reset, push, pop,
    input  [7:0] push_data,
    output [7:0] head_data,
    output       empty, full
);

    // {do_push, do_pop} cases for count
    localparam COUNT_UP   = 2'b10;
    localparam COUNT_DOWN = 2'b01;

    // DEPTH entries with addresses 0..DEPTH-1
    localparam PTR_W = (DEPTH > 1) ? $clog2(DEPTH) : 1;

    // must represent 0..DEPTH
    localparam CNT_W = $clog2(DEPTH + 1);

    reg [7:0] mem [0:DEPTH-1];

    reg [PTR_W-1:0] rd_ptr;
    reg [PTR_W-1:0] wr_ptr;

    reg [CNT_W-1:0] count;

    // DEPTH sized to count, same width compare as LAST below
    localparam [31:0]      DEPTH_32  = DEPTH;
    localparam [CNT_W-1:0] COUNT_MAX = DEPTH_32[CNT_W-1:0];

    assign empty = (count == 0);
    assign full  = (count == COUNT_MAX);

    assign head_data = mem[rd_ptr];

    wire do_push;
    wire do_pop;

    assign do_push = push && (!full || pop);
    assign do_pop  = pop && !empty;

    // wrap at DEPTH-1 so non power of 2 depths work
    wire [PTR_W-1:0] wr_ptr_next;
    wire [PTR_W-1:0] rd_ptr_next;

    // last address, sized to the pointer so the compares below are same width
    localparam [31:0]      LAST_32 = DEPTH - 1;
    localparam [PTR_W-1:0] LAST    = LAST_32[PTR_W-1:0];

    assign wr_ptr_next = (wr_ptr == LAST) ? 0 : wr_ptr + 1'b1;
    assign rd_ptr_next = (rd_ptr == LAST) ? 0 : rd_ptr + 1'b1;

    always @(posedge clk) begin
        if (reset) begin
            rd_ptr <= 0;
            wr_ptr <= 0;
            count  <= 0;
        end
        else begin
            // Pointer logic
            if (do_push) begin
                mem[wr_ptr] <= push_data;
                wr_ptr <= wr_ptr_next;
            end

            if (do_pop) begin
                rd_ptr <= rd_ptr_next;
            end

            // Count
            case ({do_push, do_pop})
                COUNT_UP:   count <= count + 1'b1;
                COUNT_DOWN: count <= count - 1'b1;
                default:    count <= count;
            endcase
        end
    end

endmodule
