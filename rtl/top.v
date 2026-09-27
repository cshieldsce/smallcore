module top (
    input             clk,
    input             reset,

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
    output     [3:0]  gpio_oe
);

endmodule