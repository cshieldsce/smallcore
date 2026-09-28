# CRC-8 on candidate Lanes, two lanes: four host bytes out on pin 0 MSB
# first and back through the pad; the register kept from its input end, the
# Fibonacci form (docs/crc-baselines.md), f = in ^ the feedback bits at the
# taps, the input into lane 0 at age 0, f(t-1-i) at lane 1's bit i: eight bits of each; the parity as two paths through SKIPs meeting on pin 1,
# cleared by the cell's first word, sampled back in as the new feedback bit.
# Then the CRC out on pin 1 MSB first, one bit per run of the `crc` body: the
# register's top bit is the feedback with a 0 in, the same tree, and a 0 fed
# back in its place shifts the register on without feedback; pin 3, held at
# 0, is both. The PULL between bytes breaks a body, so the four are written
# out. 100 words, 46 distinct. Written by gen.py.

CONFIG shift_dir, 1             # MSB first: a sample enters at bit 0 and ages upward
SET 3, 0                        # pin 3: the 0 the emission feeds in
PULL                            # byte 0
b0: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b0e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b0o1                        # 1: odd
b0e1: SKIP1 5, 0                # even so far: 0? step over: even still
JMP b0o2                        # 1: odd
b0e2: SKIP1 6, 0                # even so far: 0? step over: even still
JMP b0o3                        # 1: odd
b0e3: SKIP1 7, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b0_f
b0o1: SKIP1 5, 0                # odd so far: 0? step over: odd still
JMP b0e2                        # 1: even
b0o2: SKIP1 6, 0                # odd so far: 0? step over: odd still
JMP b0e3                        # 1: even
b0o3: SKIP1 7, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b0_f: SHIFT_IN1 1               # f into the window
REPEAT 8, b0                    # the byte's eight bits
PULL                            # byte 1
b1: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b1e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b1o1                        # 1: odd
b1e1: SKIP1 5, 0                # even so far: 0? step over: even still
JMP b1o2                        # 1: odd
b1e2: SKIP1 6, 0                # even so far: 0? step over: even still
JMP b1o3                        # 1: odd
b1e3: SKIP1 7, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b1_f
b1o1: SKIP1 5, 0                # odd so far: 0? step over: odd still
JMP b1e2                        # 1: even
b1o2: SKIP1 6, 0                # odd so far: 0? step over: odd still
JMP b1e3                        # 1: even
b1o3: SKIP1 7, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b1_f: SHIFT_IN1 1               # f into the window
REPEAT 8, b1                    # the byte's eight bits
PULL                            # byte 2
b2: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b2e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b2o1                        # 1: odd
b2e1: SKIP1 5, 0                # even so far: 0? step over: even still
JMP b2o2                        # 1: odd
b2e2: SKIP1 6, 0                # even so far: 0? step over: even still
JMP b2o3                        # 1: odd
b2e3: SKIP1 7, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b2_f
b2o1: SKIP1 5, 0                # odd so far: 0? step over: odd still
JMP b2e2                        # 1: even
b2o2: SKIP1 6, 0                # odd so far: 0? step over: odd still
JMP b2e3                        # 1: even
b2o3: SKIP1 7, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b2_f: SHIFT_IN1 1               # f into the window
REPEAT 8, b2                    # the byte's eight bits
PULL                            # byte 3
b3: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b3e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b3o1                        # 1: odd
b3e1: SKIP1 5, 0                # even so far: 0? step over: even still
JMP b3o2                        # 1: odd
b3e2: SKIP1 6, 0                # even so far: 0? step over: even still
JMP b3o3                        # 1: odd
b3e3: SKIP1 7, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b3_f
b3o1: SKIP1 5, 0                # odd so far: 0? step over: odd still
JMP b3e2                        # 1: even
b3o2: SKIP1 6, 0                # odd so far: 0? step over: odd still
JMP b3e3                        # 1: even
b3o3: SKIP1 7, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b3_f: SHIFT_IN1 1               # f into the window
REPEAT 8, b3                    # the byte's eight bits
crc: SHIFT_IN 3, 1, 0           # a 0 in, age 0; pin 1 <- 0
ce0: SKIP 0, 0                  # even so far: 0? step over: even still
JMP co1                         # 1: odd
ce1: SKIP1 5, 0                 # even so far: 0? step over: even still
JMP co2                         # 1: odd
ce2: SKIP1 6, 0                 # even so far: 0? step over: even still
JMP co3                         # 1: odd
ce3: SKIP1 7, 0                 # even so far: 0? step over: even
SET 1, 1                        # odd
JMP c_f
co1: SKIP1 5, 0                 # odd so far: 0? step over: odd still
JMP ce2                         # 1: even
co2: SKIP1 6, 0                 # odd so far: 0? step over: odd still
JMP ce3                         # 1: even
co3: SKIP1 7, 1                 # odd so far: 1? step over: even
SET 1, 1                        # odd
c_f: SHIFT_IN1 3                # a 0 back for the feedback: the register shifts on
REPEAT 8, crc                   # pin 1 holds the CRC's bit as the REPEAT issues; halted after the last
