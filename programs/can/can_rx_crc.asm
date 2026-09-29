# CAN receiver, stage 6C: three streams, two places. The raw history for the
# run test in in_shift_reg; the CRC in the accumulator, ACC_CRC on the pad
# the clock after every data sample, stuff bits left out; and the data, which
# has nowhere left to go, through the RX FIFO one bit a byte as in
# can_rx_bits_C.asm: a PUSH of in_shift_reg after every data sample, the
# data bit its bit 0. 8 clocks a bit, the sample on the 7th clock (the level
# through the 6th), the CRC's on the 8th. The CRC runs over the whole
# destuffed stream, the frame's CRC included, so what is left is 0 when the
# CRC matched: after the intermission two ACC_PUSHes hand the host that
# residue, low byte first. The ACK is pulled whatever the CRC said: the
# residue is in acc, and nothing but a pin and a sample takes a bit of acc to
# the pc, fifteen of them, where the CRC delimiter leaves eight clocks. For
# DLC 1, as the other receivers. The host writes the polynomial, 0x32 then
# 0x8B, and pops 42 + 2 bytes a frame. 35 words, 25 distinct.

CONFIG open_drain01, 1          # CAN_RX open-drain, the reset 1 let go: listening
CONFIG shift_dir, 1             # MSB first: a sample enters at bit 0
PULL                            # the polynomial's low byte, 0x32
ACC_LOAD
PULL                            # its high byte, 0x8B
ACC_LOAD                        # poly = 0x4599 left-aligned
SHIFT_IN 0                      # the idle bus, recessive: the register below the SOF holds a 1
WAIT 0, 0 [4]                   # the SOF's edge, held through its fifth clock
bit: SHIFT_IN 0                 # b1: the seventh clock of a data bit, the level through the sixth
ACC_CRC 0                       # b2: the level through the seventh into the CRC
PUSH                            # b3: the register to the host, the data bit its bit 0
SKIP_NORUN 5, 1                 # b4: not five recessive? step over the JMP
JMP bits [3]                    # b5 to b8: five recessive: the stuff bit on b9
SKIP_NORUN 5, 0                 # b5: not five dominant? step over the JMP
JMP bits [2]                    # b6 to b8: five dominant
JMP bite [1]                    # b6 to b7: no run: the REPEAT on b8
bits: SHIFT_IN 0 [6]            # b9 to b15: the stuff bit into the raw history, not the CRC, no PUSH
bite: REPEAT 32, bit            # the SOF to bit 31
bit2: SHIFT_IN 0                # b1: the seventh clock of a data bit, the level through the sixth
ACC_CRC 0                       # b2: the level through the seventh into the CRC
PUSH                            # b3: the register to the host, the data bit its bit 0
SKIP_NORUN 5, 1                 # b4: not five recessive? step over the JMP
JMP bit2s [3]                   # b5 to b8: five recessive: the stuff bit on b9
SKIP_NORUN 5, 0                 # b5: not five dominant? step over the JMP
JMP bit2s [2]                   # b6 to b8: five dominant
JMP bit2e [1]                   # b6 to b7: no run: the REPEAT on b8
bit2s: SHIFT_IN 0 [6]           # b9 to b15: the stuff bit into the raw history, not the CRC, no PUSH
bit2e: REPEAT 10, bit2          # bits 32 to 41, the CRC's last
SHIFT_IN 0 [1]                  # the CRC delimiter, sampled; the slot's edge two clocks on
SET 0, 0 [7]                    # the ACK slot: pulled dominant for the bit, whatever the CRC said
SET 0, 1 [7]                    # the ACK delimiter: let go
gap: NOP [6]                    # EOF and the intermission
REPEAT 10, gap
ACC_PUSH                        # the CRC residue's low byte: 0 and 0 when the CRC matched
ACC_PUSH                        # its high byte; halted
