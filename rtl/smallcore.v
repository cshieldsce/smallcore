// SmallCore as a peripheral: the host register block, the program ROM and
// top (the core with its FIFOs). Ports are the pad-level signals; a pad
// wrapper (Tiny Tapeout, FPGA) maps them one for one and collapses each
// gpio_out/gpio_oe/gpio_in triple onto one bidirectional pin. Hard reset
// clears everything; a CONTROL write restarts the core only.
module smallcore (
    input        clk, reset,

    input  [7:0] host_wdata,
    input  [1:0] host_addr,
    input        host_we, host_re,
    output [7:0] host_rdata,

    input  [3:0] gpio_in,
    output [3:0] gpio_out,
    output [3:0] gpio_oe
);

    wire [3:0]  sel;
    wire        restart;
    wire        tx_push;
    wire        rx_pop;
    wire        tx_full;
    wire        rx_empty;
    wire        halted;
    wire [7:0]  rx_data;
    wire [7:0]  imem_addr;
    wire [15:0] imem_word;
    wire [8:0]  program_words;
    wire [15:0] rom_word;
    wire [8:0]  rom_words;

    wire        load_mode;
    wire        ram_select;

    wire        prog_we;
    wire [7:0]  prog_addr;
    wire [15:0] prog_wdata;
    wire [8:0]  prog_words;

    wire [15:0] ram_word;

    host host_i (
        .clk      (clk),
        .reset    (reset),

        .wdata    (host_wdata),
        .addr     (host_addr),
        .we       (host_we),
        .re       (host_re),
        .rdata    (host_rdata),

        .tx_full  (tx_full),
        .rx_empty (rx_empty),
        .halted   (halted),
        .rx_data  (rx_data),

        .tx_push  (tx_push),
        .rx_pop   (rx_pop),
        .restart  (restart),
        .sel      (sel),

        .load_mode  (load_mode),
        .ram_select (ram_select), 
        .prog_we    (prog_we),
        .prog_addr  (prog_addr),
        .prog_wdata (prog_wdata),
        .prog_words (prog_words)

    );

    rom rom_i (
        .sel   (sel),
        .addr  (imem_addr),
        .word  (rom_word),
        .words (rom_words)
    );

    ram ram_i (
        .clk   (clk),
        .we    (prog_we),
        .waddr (prog_addr),
        .wdata (prog_wdata),
        .raddr (imem_addr),
        .rdata (ram_word)
    );

    assign imem_word = ram_select ? ram_word : rom_word;
    assign program_words = load_mode ? 9'd0 : ram_select ? prog_words : rom_words;

    top top_i (
        .clk           (clk),
        .reset         (reset),
        .restart       (restart),

        .imem_word     (imem_word),
        .program_words (program_words),
        .gpio_in       (gpio_in),

        .tx_data       (host_wdata),
        .tx_push       (tx_push),
        .tx_full       (tx_full),

        .rx_data       (rx_data),
        .rx_pop        (rx_pop),
        .rx_empty      (rx_empty),

        .imem_addr     (imem_addr),
        .gpio_out      (gpio_out),
        .gpio_oe       (gpio_oe),
        .halted        (halted)
    );

endmodule
