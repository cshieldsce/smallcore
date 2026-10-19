// SmallCore's four GPIO pads on the PYNQ-Z2, two ways, picked by `pad_sel` (smallcore_axi.v's CTRL[2]):
//
//   0  CAN, PMOD A, as smallcore_pynq_can.v: pin 1 CTX (the transceiver's TXD, low while the core
//      pulls pin 0 low), pin 2 CRX (its RXD). gpio 0 reads the wired-AND of CTX and CRX through
//      one flop, as an open-drain pad reads the bus; gpio 1..3 read PMOD A pins 3, 4 and 7 and
//      never drive them. PMOD B is released.
//   1  GPIO, PMOD B pins 1..4 = gpio 0..3, each a real bidirectional pad, read through one flop:
//      the SPI loopback is a jumper from pin 1 (MOSI) to pin 4 (MISO). CTX is held recessive.
//
// The flops are on the core clock; pad_sel only changes while the core is in reset.
module smallcore_pads (
    input        clk,
    input        pad_sel,
    input  [3:0] gpio_out,
    input  [3:0] gpio_oe,
    output [3:0] gpio_in,

    output       can_ctx,
    input        can_crx,
    input  [2:0] ja_gpio,
    inout  [3:0] jb
);

    reg       crx_s = 1'b1;
    reg [3:0] jb_s  = 4'hF;
    always @(posedge clk) begin
        crx_s <= can_crx;
        jb_s  <= jb;
    end

    wire can_drive = gpio_oe[0] ? gpio_out[0] : 1'b1;
    assign can_ctx = pad_sel ? 1'b1 : can_drive;

    genvar g;
    generate
        for (g = 0; g < 4; g = g + 1) begin : pad
            assign jb[g] = (pad_sel && gpio_oe[g]) ? gpio_out[g] : 1'bz;
        end
    endgenerate

    assign gpio_in = pad_sel ? jb_s : {ja_gpio, crx_s & can_drive};

endmodule
