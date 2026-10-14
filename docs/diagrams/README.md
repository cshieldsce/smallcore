# Diagrams


From the big picture down to what the Verilog will look like:

| diagram | shows |
|---|---|
| `diagrams/overview.svg` | program and bytes in, UART or SPI out, how a byte reaches the pins |
| `diagrams/isa_encoding.svg` | the 16-bit word: opcode / delay / side effect / own operands per instruction |
| `diagrams/isa_execute.svg` | what each instruction does, cycles, the PULL, PUSH and WAIT stalls |
| `diagrams/core_fetch.svg` | datapath at register level, named as in the Verilog: decode, pc, REPEAT's rc |
| `diagrams/core_out.svg` | the output side: TX FIFO, shift_reg, shift_dir, open_drain, gpio |
| `diagrams/core_in.svg` | the input side: in_shift_reg, the accumulator (acc, poly), the RX FIFO |
| `diagrams/smallcore.svg` | around the core: host registers, program ROM and RAM, the loader, the fetch mux |
| `diagrams/control.svg` | the control block: inputs, equations, counter, enables |
| `diagrams/states.svg` | the same block as per-cycle states: Issue, Hold, Stall, Halt |
| `diagrams/physical-results.md` | cells, area, utilization and timing per RTL milestone from the Tiny Tapeout CMOS5L flow in `asic/janestreet/` |
| `diagrams/repeat-candidates.md` | the repeat comparison that chose REPEAT: four candidate words for "again" against the SWD programs, on the model only; words, encoding, state, timing, stalls, restart, what each disturbs; the spec; the outcome |
| `diagrams/can-candidates.md`, "RX's evidence" and "the spec" | what the receive side said about A, Bc and C, the decision, and SKIP_RUN's spec: the word, the test, the rules, what pins it |
| `diagrams/can-combined.md` | the combined CAN programs, the payoff test for the run test and the accumulator: the whole frame unopposed in 152 words at 8 clocks a bit with the CRC the core's; arbitration only with the identifier in the program, 206 to 228 words; the receiver's three streams in two places and the ACK that cannot wait for the CRC |
| `diagrams/crc-candidates.md` | the CRC state candidates, the register widened, the input read without a slot, two lanes, an LFSR accumulator: CRC-15 against the oracle where it fits, the destuffing receiver handing the host bytes, words, cycles, state, encoding; on the model only |
| `diagrams/crc-baselines.md` | CRC-15 on the current ISA: the census of what every word writes and reads, the five questions and which fails, the host's CRC, CRC-4 as the widest the core computes, the CRC as data; no candidate |
| `diagrams/can-candidates.md` | the CAN comparison: a one-cycle branch, the sent bit exposed, a run test and a run counter, and their combinations, spliced into the arbitration and stuffing programs on the model only; words, cycles a bit, sample point, pins, REPEAT, state, encoding, what each disturbs; stuffing back from 16 cycles a bit to 8; the outcome after RX: C adopted, A, B, Bc and D rejected, REPEAT kept |

Diagrams show only hardware that exists in `model/cpu.py` and passes the tests.
