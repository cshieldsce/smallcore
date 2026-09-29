# 10BASE-T on Protocol Engine v2, programs only

**Outcome (2026-09-28): the transmitter works at 40 MHz, but only because the
host does the Manchester encoding. A receiver that tracks the edges works
from 90 MHz up. Every fixed-timing receiver loses a long frame.** This is an
experiment on the frozen v2 core. The ISA, the model, the RTL and the ROM
are unchanged. The programs are written by `experiments/ethernet/gen.py`
and pinned on the model by `tests/model/test_ethernet.py`, 114 tests. One
pin-level RTL test, `ethernet_tx_40_frame_at_the_pins` in
`tests/rtl/top_tb.py`, sends a frame out of `top.v` from eth_tx_40.

The question was how far v2 stretches for 10BASE-T when all we may write is
programs. Transmitting is a matter of timing, and the core's timing is
exact. Receiving an asynchronous stream is a matter of tracking a phase.
The core can track one only by re-arming a WAIT on every mid-bit edge. The
two-way branch in front of that WAIT costs a clock more on one side than
the other, and that clock sets the minimum core clock. At 9 clocks per bit
(90 MHz) both margins are positive. At 8 clocks one of them is zero, and a
long frame loses lock. This is also above what the hardened v2 closes at in
its slow corner: the worst path is 12.9 ns, about 77 MHz
(`docs/physical-results.md`).

Assumptions about the line. The core drives TD, a single-ended Manchester
line, plus TX_EN, the enable of an external driver: "idle" (no differential
voltage) means TX_EN low. It listens on RD, the output of a squelched
receive comparator, which reads 0 while the wire is quiet. Complementary
TD+ and TD- cannot come from the core, because SHIFT_OUT drives only gpio 0.
IEEE 802.3 Manchester is used and checked at the pin: a 0 is sent high then
low, a 1 low then high, so the second half of each bit is the bit.

| requirement | result | evidence (test / program) |
|---|---|---|
| Manchester TX | **works**. The waveform is exact at the pin: 2 clocks per half-bit at 40 MHz, IEEE polarity, LSB first. It is exact at the pins of `top.v` too. | `test_a_fixed_byte_is_ieee_manchester_at_the_pin`, `eth_tx_fixed.asm` (20 words); RTL `ethernet_tx_40_frame_at_the_pins` |
| clock choice | **20 MHz fails**: PULL and JMP leave no free clock, so 8 half-bits take 10 clocks. **40 MHz is the minimum** for the host-encoded transmitter. It needs one free clock between half-bits, and every one of the 16 clocks per host byte is used. **50 MHz**: halves of 3 and 2 clocks put each bit boundary 10 ns off the grid (60/40 duty). **60, 80 and 100 MHz** are exact. Manchester encoded on the core from raw bytes needs 33 clocks per byte: it **fails at 40 MHz** (one 75 ns half-bit per byte), works at 50 MHz with the 10 ns error, and is exact from 60 MHz. A fixed-timing receiver works at 40 MHz and above when the clocks agree. A tracking receiver works **from 90 MHz**. | `test_the_host_encoded_transmitter_at_each_clock`, `test_at_20_mhz_the_pull_and_the_jmp_have_no_clock`, `test_manchester_from_raw_bytes_*`, `test_re_aligning_on_every_edge_needs_9_clocks_a_bit`; `eth_tx_{20,40,50,60,80,100}.asm`, `eth_txr_{40,50,60,80}.asm` |
| preamble + SFD | **works**. From the program alone it takes 10 words: one REPEAT of a two-word pair covers the 62 alternating bits. In the streaming transmitter the host sends the preamble and SFD as data. | `test_preamble_and_sfd_from_the_program`, `eth_tx_preamble.asm` |
| stream long frame (64 / 1518 B) | **works at 40 MHz**. Both lengths go out whole with no gap: the PULL takes the one free clock after the 8th half-bit, and the loop's JMP fits in a free clock mid-byte. If the host is late the PULL stalls, and the frame breaks. | `test_a_whole_frame_streams_without_a_gap[64,1518]`, `test_the_host_may_sleep_63_clocks_inside_a_frame`; `eth_tx_40.asm` |
| end of frame / link pulses | **TP_IDL works with the host's help.** The host follows the FCS with 0xFF. Its first cell is high-high, which no data bit is. The program reads TD back through its own pad and catches that cell with a run test inside the free clocks. It then holds TD high for 300 ns, drops TX_EN and pushes a status byte. The on-core encoder cannot end a frame: every byte value is data, no count goes past 32, and the last PULL stalls in the middle of a bit. **NLP works idle-only.** 51 words, 100 ns pulses every 15.99 ms, using a Johnson counter kept in `in_shift_reg`. One REPEAT can wait at most 6.5 ms at 40 MHz, below the 8 ms minimum. A program cannot both send link pulses and wait for the host: a PULL on an empty FIFO stalls, and nothing can test the FIFO without stalling. The inter-frame gap (IFG) is the host's to keep. | `test_the_end_marker_is_tp_idl_then_idle`, `test_back_to_back_frames_…`, `test_normal_link_pulses_every_16_ms_while_idle`, `test_one_repeat_waits_at_most_6_5_ms_at_40_mhz`, `test_an_idle_transmitter_is_a_stalled_pull_…`; `eth_nlp.asm` |
| CRC-32 | **host-assisted, and it fits.** The host appends zlib's CRC-32. To the program it is 4 more data bytes, so the timing is untouched. The receiver checks the residue. The core cannot compute it. A program can both write and read only 24 bits of state (`in_shift_reg` 8 + `acc` 16), and CRC-32 needs 32. **2×16 is measured and fails.** CRC-32's feedback taps both halves (0x04C1 and 0x1DB7), and the high half shifts in r[15]. `ACC_CRC` with either half computes a true CRC-16 that is neither half of CRC-32. There is also no clock to spare: the 40 MHz loop issues a word every clock, and a CRC wants one per data bit. | `test_the_fcs_is_the_hosts_…`, `test_crc32_needs_32_bits_of_state_the_core_has_24`, `test_neither_half_of_crc32_is_a_16_bit_crc`, `test_the_40_mhz_loop_has_no_clock_for_a_crc` |
| idealized RX (known phase) | **works.** One WAIT finds a preamble rise, which is the mid-bit of a 1. After that each bit is sampled one clock past its expected edge, and `SKIP_RUN 2, 1` finds the SFD. A 64-byte frame comes through at all 16 phases at 40, 50, 60, 80 and 100 MHz. The program is 12 words. | `test_fixed_sampling_receives_a_frame_at_every_phase_…`; `eth_rx_fixed_*.asm` |
| unknown-phase RX | **fixed sampling fails**, and **tracking fails below 90 MHz**. The WAIT can only re-arm on a level, not on an edge. So each bit costs: sample the first half (the complement of the bit), SKIP, a JMP on one path, then a WAIT that must be up before the mid-bit edge. The sample must fall after the bit boundary (margin a − C/2 clocks). The WAIT must be up before the edge (margin C − a − 3). **50 MHz** works at 7 of 16 phases. **60 MHz** has both margins at zero: it works only phase-locked. **80 MHz** leaves one margin at zero whichever way `a` is chosen. **90 and 100 MHz** have both margins positive. | `test_re_aligning_at_50_mhz_works_at_7_phases_in_16`, `test_re_aligning_on_every_edge_needs_9_clocks_a_bit`; `eth_rx_track_{50,60,80,80_a5,90,100}.asm` |
| frequency drift ±100 ppm | **fixed sampling loses every 1518-byte frame at every clock.** 100 ppm over 12 208 bits is 1.2 bit times of drift, against a quarter-bit of margin. It gets 11 to 617 bytes through, depending on phase, clock and sign. Even 64 bytes at 40 MHz and +100 ppm lose 3 of 16 phases. **Tracking at 90 and 100 MHz holds 1518 bytes** at ±100 and ±200 ppm. The exploratory sweep covered 8 phases with a random payload and 4 phases with 1500 zero bytes. The tests pin 2 phases for each payload. **Tracking at 60 and 80 MHz loses lock** when the phase drifts onto a zero margin. At 80 MHz with a = 4, a slow transmitter pushes the sample onto the boundary (304 bytes). With a = 5, a fast transmitter's early falls find the WAIT late in a run of zeros (460 bytes), while a random payload survives. | `test_fixed_sampling_loses_a_1518_byte_frame_…`, `test_fixed_sampling_at_40_mhz_has_a_phase_window_…`, `test_re_aligning_at_90_and_100_mhz_holds_a_1518_byte_frame`, `test_re_aligning_at_60_and_80_mhz_loses_lock_on_a_zero_margin` |
| collision detection | **works during TX at 40 MHz.** Two RD samples, 4 clocks apart, sit in the free clocks of each host byte. During the other station's preamble they always catch it: a period of 8 clocks sampled half a period apart. Detection takes at most 19 clocks (0.48 µs) after RD first goes high. The program then sends a 32-bit jam and TP_IDL, reports status bit 7 set, and drains the rest of the frame through the end marker. **Carrier sense works**: 4 samples, one half-bit apart, before the first half-bit. A first version put them 3 clocks apart; a 4-clock low run can hold two such samples, and the bench caught it. Backoff is the host's (the MAC's). | `test_a_collision_is_seen_jammed_reported_and_drained[*]`, `test_carrier_sense_defers_while_rd_is_busy` |
| program words | TX: 48 (carrier sense, stream, end, TP_IDL, collision, jam, drain). On-core encoder: 94. Fixed RX: 12. Tracking RX: 58. NLP: 51. Preamble: 10. Nothing comes near 256, so program size is not a pressure here. | `test_ethernet_by_the_numbers` |
| cycles per bit | TX: 4 (40 MHz), with every clock used. On-core encoder: 4 + 1/8, so 5 in practice. Fixed RX: 4. Tracking RX: 9 with margins, 6 phase-locked. | as above |
| host bandwidth requirement | **TX: 2.5 MB/s of writes**, 2 host bytes per data byte, one every 16 clocks (400 ns). That is 44% of the bus's peak push rate at 40 MHz (a push takes 7 clocks). A 4-deep FIFO lets the host stop for up to 63 clocks (1.575 µs, about 15 bit times); one clock more breaks the frame. The on-core encoder halves the rate to 1.25 MB/s but cannot end a frame. **RX: 1.25 MB/s of pops.** The host may stop for 128 clocks at 40 MHz (3.2 µs) or 222 clocks at 90 MHz (2.5 µs). The host also inverts each byte from the tracking receiver, handles frame ends and restarts, keeps the IFG, times the NLPs and runs the backoff. | `test_a_whole_frame_streams_without_a_gap`, `test_the_host_may_sleep_63_clocks_…`, `test_the_receiving_host_may_sleep_about_three_bytes` |
| architectural pressure found | **Phase tracking:** re-arming on an edge of unknown direction costs a data-dependent branch per bit, so RX needs 9 clocks per bit. **The end of a frame is the absence of edges:** it needs a wait with a timeout, and nothing provides one (`test_the_receiver_does_not_see_the_frame_end`). **Waiting on either of two events** (the host or time): needed for NLPs while idle, and for the frame end. **Width of the CRC state.** **Long time counts.** | below |

## Architectural pressures, in generic terms, compared with CAN's

- **Three simultaneous independent streams (CAN RX: raw history,
  destuffed data, CRC). Ethernet: different, and not needed.** Ethernet
  has no stuffing. The tracking receiver uses one stream: the first-half
  samples, which are the data inverted. The CRC could be a second stream,
  but it is 32 bits, which is a separate pressure. The transmitter uses a
  pad read-back as a second, one-bit stream (TD read back to find the end
  marker, RD for collisions), inside the free clocks.
- **A decision on the accumulator's state (CAN ACK after CRC). Ethernet:
  doesn't care on the core.** Nothing on the wire depends on the CRC in
  time: no ACK slot. The FCS check can wait for the host.
- **CRC state width (CAN: 15 bits needed, 8 available before v2). Ethernet:
  the same pressure, larger.** CRC-32 needs 32 bits. The core has 24 bits a
  program can both write and read, and the 16-bit accumulator does not
  split in two. With a host-supplied FCS the pressure disappears for TX.
- **Program words, 256 (CAN full frame 233 before v2). Ethernet: doesn't
  care.** The largest program is 94 words. Ethernet has no per-bit control
  like stuffing or arbitration, and its bytes are uniform, so one loop or
  8 unrolled cells covers any length.
- **A two-way branch that lands on the next edge from either side (CAN
  candidate A, rejected 2026-09-28). Ethernet: the same pressure, now with
  a measured cost.** The tracking receiver's fall path pays a JMP that its
  rise path does not. That one clock is part of the reason RX needs 9 clocks
  per bit: by the inequality, equal paths would need 7 (computed, not built).
  CAN's receiver never felt it because CAN re-synchronises rarely and has
  slack after each sample. Manchester needs every edge.
- **New: phase tracking / edge-relative timing.** Every clock rate below 90
  MHz fails because the only phase reference is a level-WAIT. The WAIT must
  be re-armed with the right level before each edge. Oversampling (sampling
  every clock and deciding on the samples) costs one SHIFT_IN per clock and
  leaves nothing for the decision at C ≤ 8. It was analysed, not built.
  CAN's hard sync on the SOF followed by fixed sampling survives because a
  CAN frame has a resync edge every 5 bits at most and a tolerance of
  several time quanta. 10BASE-T drifts 1.2 bit times over one maximum frame.
- **New: wait with a timeout / on either of two events.** The frame end
  (carrier gone), the NLP timer against the host FIFO, and the IFG all
  ask "whichever comes first". The core has one kind of wait (PULL, PUSH or
  WAIT), and each waits for exactly one thing. CAN finds its frame end by
  counting from the DLC, which is its own pressure: a count from received
  data. Ethernet's frame end is not in the data.
- **New, minor: long time counts.** 16 ms is 640 000 clocks. REPEAT counts
  to 32 and does not nest, so the program keeps a Johnson counter in
  `in_shift_reg` through a pad read-back. It is expressible (51 words), but
  it uses up the only register a program both reads and writes. CAN doesn't
  care.
- **A stall inside a frame is a broken frame (CAN, since stage 1).
  Ethernet: the same, and tighter.** The TX host has 63 clocks of slack at
  2.5 MB/s. The RX host has about 3 bytes.

## Failures kept (each one teaches something)

| program | fails because | test |
|---|---|---|
| `eth_tx_20.asm` | one clock per half-bit leaves no clock for PULL and JMP: 10 clocks per 8 half-bits | `test_at_20_mhz_the_pull_and_the_jmp_have_no_clock` |
| `eth_txr_40.asm` | the on-core encoder needs 33 clocks per byte and 40 MHz gives 32 | `test_manchester_from_raw_bytes_at_40_mhz_is_one_clock_a_byte_short` |
| `eth_txr_50/60/80.asm` | no frame end: the last PULL stalls in the middle of a bit with TX_EN high | `test_manchester_from_raw_bytes_on_the_core` |
| `eth_rx_fixed_*.asm` | no re-alignment: 1.2 bit times of drift at 100 ppm over 1518 bytes | `test_fixed_sampling_loses_a_1518_byte_frame_…` |
| `eth_rx_track_50.asm` | the sample falls after the boundary at only 7 of 16 phases | `test_re_aligning_at_50_mhz_works_at_7_phases_in_16` |
| `eth_rx_track_60.asm`, `_80.asm`, `_80_a5.asm` | a margin of zero, which the drifting phase eventually reaches | `test_re_aligning_at_60_and_80_mhz_loses_lock_on_a_zero_margin` |
| `eth_rx_fixed_40`, `eth_rx_track_90` | the frame end is not seen, so the next frame is garbage | `test_the_receiver_does_not_see_the_frame_end` |
| `eth_tx_*` carrier sense, first version | samples 3 clocks apart can both sit in one 4-clock low run (found and fixed; the sample spacing is now a half-bit) | `test_a_collision_…[20,50]` failed before the fix |
