# 6B for 0x5A3 with the retry in the program after a loss.
# 229 words, 74 distinct.

CONFIG open_drain01, 1          # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
CONFIG shift_dir, 1             # MSB first
PULL                            # the polynomial's low byte, 0x32
ACC_LOAD
PULL                            # its high byte, 0x8B
ACC_LOAD                        # poly = 0x4599 left-aligned
frame: SHIFT_IN 0               # the idle bus, recessive: the register below the SOF holds a 1
PULL                            # {d0[7], 0000000} (stalls while the FIFO is empty: between frames, the bus idle)
retry: NOP
h0: SET 0, 0 [1]                # b1: header bit 0, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h1: SET 0, 1 [1]                # b1: header bit 1, recessive, let go
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
h2: SET 0, 0 [1]                # b1: header bit 2, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h3: SET 0, 1 [1]                # b1: header bit 3, recessive, let go
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
h4: SET 0, 1 [1]                # b1: header bit 4, recessive, let go
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
h5: SET 0, 0 [1]                # b1: header bit 5, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h6: SET 0, 1 [1]                # b1: header bit 6, recessive, let go
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
h7: SET 0, 0 [1]                # b1: header bit 7, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h8: SET 0, 0 [1]                # b1: header bit 8, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h9: SET 0, 0 [1]                # b1: header bit 9, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h10: SET 0, 1 [1]               # b1: header bit 10, recessive, let go
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
h11: SET 0, 1 [1]               # b1: header bit 11, recessive, let go
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
h12: SET 0, 0 [1]               # b1: header bit 12, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h13: SET 0, 0 [1]               # b1: header bit 13, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h14: SET 0, 0 [1]               # b1: header bit 14, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h15: SET 0, 0 [1]               # b1: header bit 15, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h16: SET 0, 0 [1]               # b1: header bit 16, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h17: SET 0, 1 [2]               # b1: header stuff 17, recessive, let go
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
h18: SET 0, 0 [1]               # b1: header bit 18, dominant, driven
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0 [4]                  # b4: the bus, held to b8
h19: SET 0, 1 [1]               # b1: header bit 19, recessive, let go
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the bus
SKIP 0, 1 [3]                   # recessive as sent? step over the JMP on b9: the next bit
JMP lost                        # dominant: lost
b0: SHIFT_OUT                   # b1: the bit onto the pad, the byte's last
PULL                            # b2: the next byte (stalls while the FIFO is empty: the bit stretches)
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b0d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b0r [1]                     # five dominant: a recessive stuff bit on b9
JMP b1 [1]                      # no run: the next bit on b9
b0d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP b1                          # the next bit on b17
b0r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
b1: SHIFT_OUT [1]               # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b1d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b1r [1]                     # five dominant: a recessive stuff bit on b9
JMP b2 [1]                      # no run: the next bit on b9
b1d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP b2                          # the next bit on b17
b1r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
b2: SHIFT_OUT [1]               # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b2d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b2r [1]                     # five dominant: a recessive stuff bit on b9
JMP b3 [1]                      # no run: the next bit on b9
b2d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP b3                          # the next bit on b17
b2r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
b3: SHIFT_OUT [1]               # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b3d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b3r [1]                     # five dominant: a recessive stuff bit on b9
JMP b4 [1]                      # no run: the next bit on b9
b3d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP b4                          # the next bit on b17
b3r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
b4: SHIFT_OUT [1]               # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b4d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b4r [1]                     # five dominant: a recessive stuff bit on b9
JMP b5 [1]                      # no run: the next bit on b9
b4d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP b5                          # the next bit on b17
b4r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
b5: SHIFT_OUT [1]               # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b5d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b5r [1]                     # five dominant: a recessive stuff bit on b9
JMP b6 [1]                      # no run: the next bit on b9
b5d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP b6                          # the next bit on b17
b5r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
b6: SHIFT_OUT [1]               # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b6d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b6r [1]                     # five dominant: a recessive stuff bit on b9
JMP b7 [1]                      # no run: the next bit on b9
b6d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP b7                          # the next bit on b17
b6r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
b7: SHIFT_OUT [1]               # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP b7d [2]                     # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP b7r [1]                     # five dominant: a recessive stuff bit on b9
JMP end                         # no run: the REPEAT on b8
b7d: SET 0, 0 [2]               # the stuff bit, dominant, driven
SHIFT_IN 0 [2]                  # sampled on its fourth clock
JMP end                         # the REPEAT on b16
b7r: SET 0, 1 [2]               # the stuff bit, recessive, let go
SHIFT_IN 0 [3]                  # sampled on its fourth clock; the REPEAT on b16
end: REPEAT 1, b0               # DLC runs: every data bit, the PULL in each run's first cell taking the next byte
crc: ACC_OUT 0 [2]              # b1: the CRC's next bit onto the pad from acc[15], held to b3
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP crcd [2]                    # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP crcr [1]                    # five dominant: a recessive stuff bit on b9
JMP crc_end                     # no run: the REPEAT on b8
crcd: SET 0, 0 [2]              # the stuff bit, dominant, driven
SHIFT_IN 0 [2]                  # sampled on its fourth clock
JMP crc_end                     # the REPEAT on b16
crcr: SET 0, 1 [2]              # the stuff bit, recessive, let go
SHIFT_IN 0 [3]                  # sampled on its fourth clock; the REPEAT on b16
crc_end: REPEAT 15, crc         # the CRC, CRC[14] first; acc clear after the fifteenth
SET 0, 1 [7]                    # the CRC delimiter: recessive, let go, a full bit
NOP [2]                         # the ACK slot: let go still, and
SHIFT_IN 0 [4]                  # sampled on its fourth clock: a receiver that took the frame pulls it dominant
PUSH [7]                        # the ACK delimiter: {the last seven samples, ACK} to the host
gap: NOP [6]                    # EOF and the intermission: ten recessive bits
REPEAT 10, gap
SKIP 0, 0                       # acked? step over the JMP: halted, the bus idle
JMP frame                       # not acked: the frame again, from the host's next bytes
JMP done                        # halted
lost: PUSH
clr: ACC_OUT 3
REPEAT 16, clr
listen: SHIFT_IN 0 [5]
SKIP_RUN 8, 1
JMP listen
SHIFT_IN 0 [6]
SKIP 0, 1
JMP listen
SHIFT_IN 0 [6]
SKIP 0, 1
JMP listen
SHIFT_IN 0 [6]
SKIP 0, 1
JMP listen
JMP retry
done: NOP
