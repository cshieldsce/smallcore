# CRC-4 on the current ISA: the widest CRC the core can compute, the second
# of the three CRC baselines (docs/crc-baselines.md). Four host bytes go out
# on pin 0 MSB first and come back through the pad as every CAN bit does; the
# CRC-4 of the 32 bits, x^4 + x + 1, goes to the host in the low nibble of one
# byte.
#
# The spec's register, shift then XOR the polynomial in at the taps, cannot
# live in in_shift_reg: a bit in the middle of it cannot be written, and
# rebuilding it through a pin needs the old copy to survive while the new one
# shifts in, twice the width. So the register is kept from its input end: the
# bit the spec feeds back, f = in ^ crc[3], depends only on the last four
# feedback bits, f = in ^ f3 ^ f4 for this polynomial, and the shift that
# takes f in is the only write. The parity is control flow, two paths through
# SKIPs that meet on a pin: pin 1 cleared by the first SKIP's side effect and
# set on the paths whose parity is one, then sampled back in. Every input bit
# takes a slot beside its feedback bit, so the register holds four of each,
# the input at bit 0 and the feedback bits at 1, 3, 5, 7: eight bits of
# register for four of CRC, and CRC-15 wants thirty. The PULL between bytes
# breaks a body, so the four bytes are written out. At the end the window is
# turned into the register's own bits, crc[3] = f3 ^ f4, crc[2] = f2 ^ f3,
# crc[1] = f1 ^ f2, crc[0] = f1, each a two-way SKIP into the pin and a
# sample, newest last so that the bits still needed stay in reach. 101
# words, 43 distinct; 8 to 11 cycles an input bit.

        CONFIG shift_dir, 1     # MSB first: the bytes go out bit 7 first, a sample enters at bit 0 and ages upward
        PULL                    # byte 0 (stalls while the FIFO is empty)
b0:     SHIFT_OUT               # the data bit onto pin 0
        SHIFT_IN 0              # and back: bit 0 of the register, the feedback bits above it at 1, 3, 5, 7
        SKIP 0, 1  1, 0         # pin 1 <- 0, f so far; in = 1? step over: parity 1
        JMP b0_a0               # in = 0: parity 0
b0_a1:  SKIP 5, 0               # parity 1: bit 5 = 0? step over: parity 1 still
        JMP b0_p0               # bit 5 = 1: parity 0
b0_p1:  SKIP 7, 0               # parity 1: bit 7 = 0? step over: parity 1, f = 1
        JMP b0_f                # bit 7 = 1: parity 0, f = 0
        SET 1, 1                # f = 1
        JMP b0_f
b0_a0:  SKIP 5, 0               # parity 0: bit 5 = 0? step over: parity 0 still
        JMP b0_p1               # bit 5 = 1: parity 1
b0_p0:  SKIP 7, 1               # parity 0: bit 7 = 1? step over: parity 1, f = 1
        JMP b0_f                # bit 7 = 0: parity 0, f = 0
        SET 1, 1                # f = 1
b0_f:   SHIFT_IN 1              # f into the register at bit 0
        REPEAT 8, b0            # the byte's eight bits
        PULL                    # byte 1 (stalls while the FIFO is empty)
b1:     SHIFT_OUT               # the data bit onto pin 0
        SHIFT_IN 0              # and back: bit 0 of the register, the feedback bits above it at 1, 3, 5, 7
        SKIP 0, 1  1, 0         # pin 1 <- 0, f so far; in = 1? step over: parity 1
        JMP b1_a0               # in = 0: parity 0
b1_a1:  SKIP 5, 0               # parity 1: bit 5 = 0? step over: parity 1 still
        JMP b1_p0               # bit 5 = 1: parity 0
b1_p1:  SKIP 7, 0               # parity 1: bit 7 = 0? step over: parity 1, f = 1
        JMP b1_f                # bit 7 = 1: parity 0, f = 0
        SET 1, 1                # f = 1
        JMP b1_f
b1_a0:  SKIP 5, 0               # parity 0: bit 5 = 0? step over: parity 0 still
        JMP b1_p1               # bit 5 = 1: parity 1
b1_p0:  SKIP 7, 1               # parity 0: bit 7 = 1? step over: parity 1, f = 1
        JMP b1_f                # bit 7 = 0: parity 0, f = 0
        SET 1, 1                # f = 1
b1_f:   SHIFT_IN 1              # f into the register at bit 0
        REPEAT 8, b1            # the byte's eight bits
        PULL                    # byte 2 (stalls while the FIFO is empty)
b2:     SHIFT_OUT               # the data bit onto pin 0
        SHIFT_IN 0              # and back: bit 0 of the register, the feedback bits above it at 1, 3, 5, 7
        SKIP 0, 1  1, 0         # pin 1 <- 0, f so far; in = 1? step over: parity 1
        JMP b2_a0               # in = 0: parity 0
b2_a1:  SKIP 5, 0               # parity 1: bit 5 = 0? step over: parity 1 still
        JMP b2_p0               # bit 5 = 1: parity 0
b2_p1:  SKIP 7, 0               # parity 1: bit 7 = 0? step over: parity 1, f = 1
        JMP b2_f                # bit 7 = 1: parity 0, f = 0
        SET 1, 1                # f = 1
        JMP b2_f
b2_a0:  SKIP 5, 0               # parity 0: bit 5 = 0? step over: parity 0 still
        JMP b2_p1               # bit 5 = 1: parity 1
b2_p0:  SKIP 7, 1               # parity 0: bit 7 = 1? step over: parity 1, f = 1
        JMP b2_f                # bit 7 = 0: parity 0, f = 0
        SET 1, 1                # f = 1
b2_f:   SHIFT_IN 1              # f into the register at bit 0
        REPEAT 8, b2            # the byte's eight bits
        PULL                    # byte 3 (stalls while the FIFO is empty)
b3:     SHIFT_OUT               # the data bit onto pin 0
        SHIFT_IN 0              # and back: bit 0 of the register, the feedback bits above it at 1, 3, 5, 7
        SKIP 0, 1  1, 0         # pin 1 <- 0, f so far; in = 1? step over: parity 1
        JMP b3_a0               # in = 0: parity 0
b3_a1:  SKIP 5, 0               # parity 1: bit 5 = 0? step over: parity 1 still
        JMP b3_p0               # bit 5 = 1: parity 0
b3_p1:  SKIP 7, 0               # parity 1: bit 7 = 0? step over: parity 1, f = 1
        JMP b3_f                # bit 7 = 1: parity 0, f = 0
        SET 1, 1                # f = 1
        JMP b3_f
b3_a0:  SKIP 5, 0               # parity 0: bit 5 = 0? step over: parity 0 still
        JMP b3_p1               # bit 5 = 1: parity 1
b3_p0:  SKIP 7, 1               # parity 0: bit 7 = 1? step over: parity 1, f = 1
        JMP b3_f                # bit 7 = 0: parity 0, f = 0
        SET 1, 1                # f = 1
b3_f:   SHIFT_IN 1              # f into the register at bit 0
        REPEAT 8, b3            # the byte's eight bits
        SKIP 4, 1  1, 0         # crc[3] = f3 ^ f4: pin 1 <- 0; bit 4 = 1? step over
        JMP c3_0                # bit 4 = 0
        SKIP 6, 1               # bit 4 = 1: bit 6 = 1? step over: even
        SET 1, 1                # odd
        JMP c3_f
c3_0:   SKIP 6, 0               # bit 4 = 0: bit 6 = 0? step over: even
        SET 1, 1                # odd
c3_f:   SHIFT_IN 1              # into the register
        SKIP 3, 1  1, 0         # crc[2] = f2 ^ f3, the window a bit older: pin 1 <- 0; bit 3 = 1? step over
        JMP c2_0                # bit 3 = 0
        SKIP 5, 1               # bit 3 = 1: bit 5 = 1? step over: even
        SET 1, 1                # odd
        JMP c2_f
c2_0:   SKIP 5, 0               # bit 3 = 0: bit 5 = 0? step over: even
        SET 1, 1                # odd
c2_f:   SHIFT_IN 1              # into the register
        SKIP 2, 1  1, 0         # crc[1] = f1 ^ f2: pin 1 <- 0; bit 2 = 1? step over
        JMP c1_0                # bit 2 = 0
        SKIP 4, 1               # bit 2 = 1: bit 4 = 1? step over: even
        SET 1, 1                # odd
        JMP c1_f
c1_0:   SKIP 4, 0               # bit 2 = 0: bit 4 = 0? step over: even
        SET 1, 1                # odd
c1_f:   SHIFT_IN 1              # into the register
        SKIP 3, 0  1, 0         # crc[0] = f1: pin 1 <- 0; bit 3 = 0? step over
        SET 1, 1
        SHIFT_IN 1              # into the register: crc[3:0] in the low nibble
        PUSH                    # to the host; halted
