module top (
    input             clk,
    input             reset,
    input             restart,   // resets the core only; the FIFOs keep their bytes

    input      [15:0] imem_word,
    input      [8:0]  program_words,
    input      [3:0]  gpio_in,

    input      [7:0]  tx_data,
    input             tx_push,
    output            tx_full,

    output     [7:0]  rx_data,
    input             rx_pop,
    output            rx_empty,

    output     [7:0]  imem_addr,
    output     [3:0]  gpio_out,
    output     [3:0]  gpio_oe,
    output            halted
);

    wire [7:0] core_tx_data;
    wire       tx_empty;
    wire       pull_en;

    fifo #(
        .DEPTH(4)
    ) tx_fifo (
        .clk       (clk),
        .reset     (reset),

        .push      (tx_push),
        .pop       (pull_en),
        .push_data (tx_data),

        .head_data (core_tx_data),
        .empty     (tx_empty),
        .full      (tx_full)
    );

    wire [7:0] core_rx_data;
    wire       rx_full;
    wire       push_en;

    fifo #(
        .DEPTH(4)
    ) rx_fifo (
        .clk       (clk),
        .reset     (reset),

        .push      (push_en),
        .pop       (rx_pop),
        .push_data (core_rx_data),

        .head_data (rx_data),
        .empty     (rx_empty),
        .full      (rx_full)
    );

    core core_i (
        .clk           (clk),
        .reset         (reset | restart),

        .tx_empty      (tx_empty),
        .rx_full       (rx_full),
        .halted        (halted),

        .imem_word     (imem_word),
        .program_words (program_words),
        .gpio_in       (gpio_in),

        .tx_data       (core_tx_data),
        .rx_data       (core_rx_data),

        .pull_en       (pull_en),
        .push_en       (push_en),

        .imem_addr     (imem_addr),
        .gpio_oe       (gpio_oe),
        .gpio_out      (gpio_out)
    );

endmodule
