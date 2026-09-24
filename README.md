# core

A mini PIO-style CPU simulator: a 16-bit ISA with `SET` / `SHIFT_OUT` / `PULL` / `JMP` and per-instruction delays, driving four output pins `gpio[3:0]`. `SET pin, value` drives one pin and leaves the others alone; `SHIFT_OUT` always drives `gpio[0]` from an 8-bit shift register. The shift register is filled by `PULL` from a TX FIFO fed from outside the core, so one program can transmit any data. `PULL` blocks while the FIFO is empty, and `JMP` (absolute 8-bit address, labels resolved by the assembler) lets a program loop back to its `PULL` and stream bytes for as long as the FIFO is fed.

```
isa.yaml      instruction set: encoding, opcodes, operand ranges
programs/     assembly programs (.asm)
sim/          simulator (cpu.py)
tests/        pytest test benches
docs/         Mermaid diagrams (.mmd) and rendered .svg, see Docs below
tools/        wavetrace.py (waveform helper), render_docs.py (docs/*.mmd -> .svg)
build/        generated: test waveforms, caches (safe to delete)
```

## Commands

```
python -m pip install -r requirements.txt
python -m pytest -v              # run tests, writes build/waves/<test bench>/<test>.svg
python sim/cpu.py                # run programs/uart_tx_0x55.asm, print listing + one trace per gpio pin
python sim/cpu.py programs/uart_tx_pull.asm 0xA3    # send a byte from the TX FIFO via PULL + SHIFT_OUT
python sim/cpu.py programs/uart_tx_loop.asm 0x55 0xA3   # stream bytes: PULL / frame / JMP loop until the FIFO is empty
python tools/render_docs.py      # re-render docs/*.svg (needs mermaid-cli)
```

## Docs

From the big picture down to what the Verilog will look like:

| diagram | shows |
|---|---|
| `docs/overview.svg` | the big picture: program and bytes go in, a UART frame comes out, and how a byte reaches the pin |
| `docs/isa_encoding.svg` | the 16-bit instruction word: opcode / delay / operand fields for each instruction |
| `docs/isa_execute.svg` | what each instruction does and how many cycles it takes, including the PULL stall |
| `docs/core.svg` | datapath at register level: every register with its reset value and enables, named as in the Verilog |
| `docs/control.svg` | the control block: its inputs, the equations it computes, the counter, and the enables it drives |
| `docs/states.svg` | the same control block as per-cycle states: Issue, Hold, Stall, Halt |

Diagrams only show hardware that exists in `sim/cpu.py` and passes the tests.
