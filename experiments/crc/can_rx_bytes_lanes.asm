# The destuffing receiver with a second lane: can_rx_bits_C.asm's cell, the raw
# history in in_shift_reg for the run test, the data bit into both lanes by one sample, SHIFT_IN01, a stuff bit into the raw
# history alone, and after every eight data bits lane 1 to the host: destuffed
# bytes at 8 clocks a bit. A body of eight cells with the push in the
# eighth, run five times, the SOF to bit 39; bits 40 and 41, the CRC's last
# two, written out with a push after; then the CRC delimiter, the ACK slot,
# the gap. For DLC 1, as the other receivers. 82 words, 46 distinct.
# Written by gen.py.

CONFIG open_drain01, 1          # CAN_RX open-drain, the reset 1 let go: listening
CONFIG shift_dir, 1             # MSB first: a sample enters at bit 0
SHIFT_IN 0                      # the idle bus, recessive: the register below the SOF holds a 1
WAIT 0, 0 [4]                   # the SOF's edge, held through its fifth clock
c0: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c0s [5]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c0s [4]                     # five dominant
JMP c1 [4]                      # no run
c0s: SHIFT_IN 0 [7]             # the stuff bit into the raw history alone
c1: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c1s [5]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c1s [4]                     # five dominant
JMP c2 [4]                      # no run
c1s: SHIFT_IN 0 [7]             # the stuff bit into the raw history alone
c2: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c2s [5]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c2s [4]                     # five dominant
JMP c3 [4]                      # no run
c2s: SHIFT_IN 0 [7]             # the stuff bit into the raw history alone
c3: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c3s [5]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c3s [4]                     # five dominant
JMP c4 [4]                      # no run
c3s: SHIFT_IN 0 [7]             # the stuff bit into the raw history alone
c4: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c4s [5]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c4s [4]                     # five dominant
JMP c5 [4]                      # no run
c4s: SHIFT_IN 0 [7]             # the stuff bit into the raw history alone
c5: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c5s [5]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c5s [4]                     # five dominant
JMP c6 [4]                      # no run
c5s: SHIFT_IN 0 [7]             # the stuff bit into the raw history alone
c6: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c6s [5]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c6s [4]                     # five dominant
JMP c7 [4]                      # no run
c6s: SHIFT_IN 0 [7]             # the stuff bit into the raw history alone
c7: SHIFT_IN01 0                # b1: the seventh clock, the level through the sixth
PUSH1                           # b2
SKIP_NORUN 5, 1                 # b3: not five recessive? step over
JMP c7s [4]                     # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b4: not five dominant? step over
JMP c7s [3]                     # five dominant
JMP e [2]                       # no run
c7s: SHIFT_IN 0 [6]             # the stuff bit into the raw history alone
e: REPEAT 5, c0                 # b8, or b16 after a stuff bit: five bytes, the SOF to bit 39
c40: SHIFT_IN01 0               # b1: the seventh clock, the level through the sixth
SKIP_NORUN 5, 1                 # b2: not five recessive? step over
JMP c40s [5]                    # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b3: not five dominant? step over
JMP c40s [4]                    # five dominant
JMP c41 [4]                     # no run
c40s: SHIFT_IN 0 [7]            # the stuff bit into the raw history alone
c41: SHIFT_IN01 0               # b1: the seventh clock, the level through the sixth
PUSH1                           # b2
SKIP_NORUN 5, 1                 # b3: not five recessive? step over
JMP c41s [4]                    # five recessive: the stuff bit at b9
SKIP_NORUN 5, 0                 # b4: not five dominant? step over
JMP c41s [3]                    # five dominant
JMP d [3]                       # no run
c41s: SHIFT_IN 0 [7]            # the stuff bit after the CRC's last, if any
d: SHIFT_IN 0 [1]               # the CRC delimiter, sampled; the slot's edge two clocks on
SET 0, 0 [7]                    # the ACK slot: pulled dominant for the bit
SET 0, 1 [7]                    # the ACK delimiter: let go
gap: NOP [6]                    # EOF and the intermission
REPEAT 10, gap                  # halted
