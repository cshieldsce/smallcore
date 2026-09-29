# CAN stress: how far Protocol Engine v2 stretches with programs only

**Outcome (2026-09-28): a whole classical CAN node's data path fits, one
program per job; the node's judgement does not.** Every DLC, identifier,
payload and stuffing extreme tried goes through bit for bit. Back-to-back
frames, bus integration, arbitration loss with a retry, the ACK error, a stuff
error and a form error all work, the last two with an error flag. What does
not fit is on record: an ACK that depends on the CRC, bit monitoring, a loser
that also receives, remote frames beside the DLC tree, resynchronisation,
long bit times on the transmit side. Nothing in `isa/`, `model/cpu.py` or
`rtl/` changed. The programs are written by `experiments/can_stress/gen.py`
from parameters, and at n = 8, DLC 1 they are 6A and 6C word for word. The
evidence is `tests/model/test_can_stress.py` (57 tests) and
`tests/rtl/test_can_stress.py` (2 tests at the pins, the same as the model
clock for clock).

Classes: **1** works as-is, **2** works with a specialised or generated
program, **3** needs the host, **4** cannot be expressed on v2.

| requirement | class | result / evidence (test) | words | cycles/bit | host bandwidth |
|---|---|---|---|---|---|
| DLC 0..8, transmit | 2 | one program per DLC, one word apart: the body's REPEAT count (`test_one_transmitter_per_dlc_one_word_apart`) | 152 each, 9 programs | 8 | 3 + DLC bytes/frame |
| DLC 0..8, receive | 2 | **one program for every DLC**: a tree of SKIP cells on the DLC bits into a chain of 8-bit loops; DLC 9..15 read as 8 (`test_one_receiver_for_every_dlc`, `test_a_dlc_above_eight_is_eight_bytes`; at the pins, `can_receiver_follows_the_dlc_at_the_pins`) | 237 (6C: 35 for one DLC) | 8 | 34 + 8·DLC + 2 bytes/frame |
| remote frames (RTR) beside the DLC tree | 4 | one more tree cell and a 21-bit path: 272 words, refused; `can_rx_dlc.asm` reads a remote frame as data and does not ack it (`test_remote_frames_do_not_fit_beside_the_dlc_tree`) | 272 > 256 | 8 | |
| identifier and payload coverage | 1 | per DLC: all-0, all-1, 0x55, 0xAA, max-stuff and 4 random payloads × 4 identifiers, TX bit for bit, CRC right, acked (324 frames); RX 189 frames (`test_every_dlc_with_adversarial_and_random_payloads`) | as above | 8 | |
| stuffing extremes | 1 | the most-stuffed DLC 8 frame found, 21 stuff bits (bound 24); a stuff bit after CRC[0]; 3 stuff bits in the CRC field (`test_stuffing_extremes`) | 152 | 8, 16 on a stuffed bit's path | |
| back-to-back frames, 3-bit intermission | 2 | TX going round: 3 frames, 10 bits + 3 clocks from the ACK delimiter to the next SOF; RX going round is back at the SOF's WAIT by the 3rd intermission bit (6C's 10-bit gap would be 4 clocks late) (`test_back_to_back_frames_with_the_three_bit_intermission`, `test_a_looping_receiver_takes_back_to_back_frames`, `test_two_cores_on_one_bus`) | TX 151, RX 48 | 8 | |
| mixed DLCs back to back | 3 | the host restarts the TX under the next DLC's program when it halts (a restart at the ACK byte starts the next frame inside EOF); one RX follows (`test_mixed_dlcs_back_to_back_by_changing_programs`) | 152 per DLC | 8 | a restart + 2 poly + 3 + DLC bytes/frame |
| bus idle detection / joining a busy bus | 2 | eleven recessive samples, a run test of 8 and 3 single SKIPs; without it 6C syncs mid-frame and loses the next frame (`test_bus_integration_needs_eleven_recessive_bits`) | +12 | 8 | |
| arbitration, won | 2 | 6B as it is, identifier in the program (`test_can_combined.py`) | 206..228 | 8 | DLC + 1 bytes |
| arbitration, lost at every identifier bit, then retry | 2 | 0x7FF loses on each of its 11 bits, 5 more identifiers on each recessive bit; the program waits 11 recessive bits and retries from the byte still in shift_reg; both frames received, acked (`test_lose_on_every_recessive_identifier_bit_then_retry`) | 221..243, one per identifier and DLC | 8 | frame queued once, 2 bytes read |
| arbitration with a dynamic identifier | 4 | known: sent bit, 5-bit history and CRC are 3 streams for 2 places (`docs/can-combined.md`) | | | |
| the loser receives and acks the winner | 4 | counted: 6B + the DLC receiver − 6 shared words = 445 (`test_a_node_that_loses_cannot_also_receive_the_frame`) | 445 > 256 | | |
| late host, TX FIFO pressure | 3 | a host filling the 4-deep FIFO every P clocks: fine to 218 (27 bit times, no stuff bits), 242 for the most stuffed; a stall of 1 cycle at a PULL stretches the bit; a 75% receiver survives 5 cycles, not 6 (`test_transmitter_host_service_interval`, `test_one_late_cycle_at_a_pull_breaks_the_bit`) | | 8 | 1 byte / 8 bits: 125 kB/s at 1 Mbit/s, a visit ≤ 27 bit times |
| late host, RX FIFO pressure | 3 | the host empties the 4-deep FIFO every P clocks: fine to 32 (4 bit times), stalls and a wrong stream from 33 (`test_receiver_host_service_interval`) | | 8 | 1 byte / bit: **1 MB/s at 1 Mbit/s**, a visit ≤ 4 bit times |
| bad CRC, detected | 3 | the residue in the last two bytes, the host's to read, every DLC (`test_a_wrong_crc_is_the_hosts_to_see_and_is_acked_anyway`) | | 8 | 2 bytes |
| ACK only on a matching CRC | 4 | known, re-confirmed at DLC 0, 1, 8: acked anyway | | | |
| stuff error, detected and flagged | 2* | in the stuff path, "newest two equal": a JMP out of the REPEAT body to an error flag, 6 dominant bits, 0x00 to the host, rc drained, acc clear, next frame whole. *The assembler refuses the JMP; it is patched in and the hardware does it, at the pins too (`test_a_stuff_error_answered_with_an_error_flag`, `can_stuff_error_flag_and_rc_drain_at_the_pins`). Without the 2-word drain a late error loses the next frame (`test_without_the_rc_drain_a_late_error_loses_the_next_frame`) | 76 | 8, the check in the stuff bit's 8 | a 0x00 marker |
| form error (CRC delimiter), flagged | 2 | straight-line SKIP over a JMP, no cycle added (`test_a_form_error_in_the_crc_delimiter_answered_with_an_error_flag`) | +2 | 8 | 0x00 marker |
| missing ACK | 1 / 2 | 6A goes again (1); an error flag from the ACK delimiter, 11 recessive waited, 0xFF to the host (2) (`test_a_missing_ack_answered_with_an_error_flag`) | 152 / 170 | 8 | 1 byte |
| bit error while transmitting | 4 | **new hazard**: 6A takes CRC and stuffing from the bus, so a forced bit is sent with a CRC that covers it; the receiver acks a valid frame with the wrong byte (`test_a_transmitter_cannot_see_a_bit_error_and_its_crc_hides_it`) | | | |
| clock rates 125k..1M at 10/25/40/50 MHz | 2 / 4 | every pairing a whole n = 10..400 clocks a bit: fractional-bit error 0. RX fits all 16 (248 words at 400); TX fits n ≤ 133, 11 of 16: not 125k at 25/40/50 MHz, not 250k at 40/50 MHz (`test_words_against_the_bit_time`, `test_frames_at_realistic_bit_times`, `test_the_receiver_at_125k_on_50_mhz`) | TX 152..235, RX 55..248 | n ≥ 8, whole | |
| oscillator tolerance (no resynchronisation) | 1 / 4 | hard sync on the SOF only: a DLC 8 frame survives a transmitter +6500 / −2500 ppm off at n = 8, +7500 / −2250 at n = 25; crystals fine, a 0.5% resonator fails fast, CAN's 1.58% out of reach (`test_no_resynchronisation_bounds_the_clock_error`) | | | |
| program words | | TX 151..243, RX 35..248; 256 is the wall for RTR, loser-receives, TX at n > 133 | | | |
| cycles per bit | | 8 minimum everywhere; the TX's own sample at 37.5% (4th clock), the RX at 75% | | | |
| host bandwidth | 3 | TX 1 byte per 8 bits; RX 1 byte per bit plus 2, the third stream leaving through the FIFO | | | |

## Architectural pressures (generic terms)

Counted in independent CAN scenarios from the table.

1. **A third independent stream** (4): dynamic-identifier arbitration (sent
   bit, history, CRC); bit monitoring while transmitting, where the CRC
   taken from the bus even hides the error; RX data bytes beside the raw
   history and the CRC, which is why data leaves a bit a byte; the loser's
   receive path.
2. **Program words: 256 a program** (4): remote frames beside the DLC tree
   (272); a loser that also receives (445); the transmitter at long bit times
   (n > 133); one arbitration program per identifier and DLC.
3. **A count from the host or from data** (3): nine TX programs that differ
   in one REPEAT word; the RX's DLC paid as a 237-word tree and chain for
   35; per-identifier arbitration programs.
4. **A decision on accumulator state** (2): ACK only on a matching CRC; an
   error flag on a CRC error (CAN sends one after the ACK delimiter).
5. **An early exit from a counted loop, with its counter reset** (2): the
   stuff-error flag works only as a JMP the assembler forbids plus a
   program-side drain of a counter it cannot read; arbitration's lost exit
   is why 6B's header is unrolled.
6. **Sampling phase and edge-relative timing** (3): no resynchronisation,
   so the clock error is bounded by one sample's margin over a whole frame;
   a late host's stretched bit is not absorbed; no WAIT with a timeout to
   look for an edge that may not come.
7. **Host service latency against FIFO depth** (2): the RX at a byte a bit
   through 4 entries, a visit every 4 bit times; the TX at a visit every 27.
8. **Timing range, a delay of 32 clocks a word and no nested loop** (1):
   long bits paid in NOP words per cell path (5 of 16 rate pairings on TX).
9. **State width, a run test of 8** (1, cheap): eleven recessive bits need
   three more single SKIPs.

## Notes

- 17 tests in `test_skip_run.py`, `test_acc.py`, `test_can_candidates.py` and
  `test_crc_candidates.py` fail at the base commit `ad4ae62`, with or without
  this work. They assemble `programs/` under an older ISA that has no
  accumulator words.
- Files: `experiments/can_stress/gen.py` and the `.asm` files it writes,
  `can_rx_dlc_rtr.asm` (refused) and `can_rx_check_nodrain.asm` (fails) kept
  as the failures; `tests/model/test_can_stress.py`;
  `tests/rtl/can_stress_tb.py` and `tests/rtl/test_can_stress.py`, built in
  `build/rtl/can_stress/` so they do not share `test_top.py`'s build.
