# CAN transmitter, stage 6A: stage 5A's data frame with the run test and
# the accumulator, 8 clocks a bit. Unopposed, the pad on the bus. The CRC is
# the core's: every data bit goes onto the pad and back into ACC_CRC on the
# third clock of its bit, the level through the second, and the fifteen CRC bits leave from acc by ACC_OUT,
# stuffed as every bit, so the host writes no CRC. Every checked bit is one
# cell: the bit and the words that ride before the sample on clocks 1 to 3,
# the sample on the 4th (the level through the 3rd, 37.5%), the run test both
# ways, the stuff bit on the 9th. The body is stage 5A's, eight cells with
# the PULL in the first, run 2 + DLC times, the last data bit a cell of its
# own, then the CRC a one-cell body run fifteen times. The host writes the
# polynomial, 0x32 then 0x8B, once, then per frame {SOF, ID[10], ID[9],
# 00000}, ID[8:1], {ID[0], RTR, IDE, r0, DLC[3:0]} and the data: 3 + DLC
# bytes. After the CRC, stage 5A's fixed form at 8 clocks a bit. Acked, the
# program halts; not acked, it goes round for the host's next frame, the
# polynomial kept. 152 words, 64 distinct.

CONFIG open_drain01, 1          # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
CONFIG shift_dir, 1             # MSB first
PULL                            # the polynomial's low byte, 0x32
ACC_LOAD
PULL                            # its high byte, 0x8B
ACC_LOAD                        # poly = 0x4599 left-aligned
frame: SHIFT_IN 0               # the idle bus, recessive: the register below the SOF holds a 1
PULL                            # {SOF, ID[10], ID[9], 00000} (stalls while the FIFO is empty: between frames, the bus idle)
lead: SHIFT_OUT [1]             # the SOF and ID[10]: b1 to b2
ACC_CRC 0                       # b3
SHIFT_IN 0 [3]                  # b4 to b7: no run of five can end here
REPEAT 2, lead                  # b8
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
end: REPEAT 3, b0               # 2 + DLC runs: ID[9] to the last data byte's bit 1
tail: SHIFT_OUT [1]             # b1: the bit onto the pad, held to b2
ACC_CRC 0                       # b3: the pad into the CRC, the level through the second clock
SHIFT_IN 0                      # b4: the level through the third clock
SKIP_NORUN 5, 1                 # b5: not five recessive? step over
JMP taild [2]                   # five recessive: a dominant stuff bit on b9
SKIP_NORUN 5, 0                 # b6: not five dominant? step over
JMP tailr [1]                   # five dominant: a recessive stuff bit on b9
JMP crc [1]                     # no run: the next bit on b9
taild: SET 0, 0 [2]             # the stuff bit, dominant, driven
SHIFT_IN 0 [3]                  # sampled on its fourth clock
JMP crc                         # the next bit on b17
tailr: SET 0, 1 [2]             # the stuff bit, recessive, let go
SHIFT_IN 0 [4]                  # sampled on its fourth clock; the next bit on b17
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
