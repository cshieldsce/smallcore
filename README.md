# core

A mini PIO-style CPU simulator: a 16-bit ISA with `SET` / `SHIFT_OUT` / `PULL` and per-instruction delays, driving one output pin from either the instruction or an 8-bit shift register. The shift register is filled by `PULL` from a TX FIFO fed from outside the core, so one program can transmit any data. `PULL` blocks while the FIFO is empty.

```
isa.yaml      instruction set: encoding, opcodes, operand ranges
programs/     assembly programs (.asm)
sim/          simulator (cpu.py)
tests/        pytest test benches
docs/         Mermaid diagrams (.mmd) and rendered .svg
tools/        wavetrace.py (waveform helper), render_docs.py (docs/*.mmd -> .svg)
build/        generated: test waveforms, caches (safe to delete)
```

## Commands

```
python -m pip install -r requirements.txt
python -m pytest -v              # run tests, writes build/waves/*.svg
python sim/cpu.py                # run programs/uart_tx_0x55.asm, print listing + trace
python sim/cpu.py programs/uart_tx_pull.asm 0xA3    # send a byte from the TX FIFO via PULL + SHIFT_OUT
python tools/render_docs.py      # re-render docs/*.svg (needs mermaid-cli)
```
