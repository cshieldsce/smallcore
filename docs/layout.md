# Old repository layout

Layout notes carried over from the previous README; see the top-level README for the current layout.


```
isa/          isa.yaml: instruction set, encoding, opcodes, operand ranges
model/        cpu.py: the golden Python model and assembler
rtl/          Verilog-2001: core.v, fifo.v, top.v (the core with its TX and RX FIFOs), host.v (the register bus),
              rom.v (GENERATED from programs/ by make rom), smallcore.v (host + rom + top: the chip)
programs/     assembly programs (.asm) in uart/, spi/, i2c/, swd/ and can/; manifest.txt gives each ROM program its permanent slot
tests/        model/: pytest benches for the model and assembler
              rtl/: cocotb benches for rtl/ under Verilator, checked against model/cpu.py; top_tb.py runs the protocols end to end,
              smallcore_tb.py runs them from the ROM through the host bus, pynq_tb.py the board wrapper
experiments/  candidate ISA words for CAN, CRC and REPEAT (acc/, can/, combined/, crc/, repeat/), each with the programs and models measured; tests/model/ pins them
asic/         janestreet/: Tiny Tapeout IHP CMOS5L packaging, 6x4 tiles; src/*.v are staged from rtl/ by make tapeout-sync
fpga/         pynq_z2/: the FPGA smoke test, buttons for a host, LEDs for read data, a PMOD jumper for the wire
docs/         Mermaid diagrams (.mmd) and rendered .svg, design write-ups and physical results, see Docs below
tools/        gen_rom.py (programs/manifest.txt -> rtl/rom.v), wavetrace.py (waveform helper), render_docs.py (docs/*.mmd -> .svg)
build/        generated: test waveforms, caches (safe to delete)
```

