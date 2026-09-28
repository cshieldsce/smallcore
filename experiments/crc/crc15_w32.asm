# CRC-15 on candidate W32, the register carried on: four host bytes out on pin 0 MSB
# first and back through the pad; the register kept from its input end, the
# Fibonacci form (docs/crc-baselines.md), f = in ^ the feedback bits at the
# taps, f(t-1-i) at age 2i + 1, the input at age 0: 30 bits of register; the parity as two paths through SKIPs meeting on pin 1,
# cleared by the cell's first word, sampled back in as the new feedback bit.
# Then the CRC out on pin 1 MSB first, one bit per run of the `crc` body: the
# register's top bit is the feedback with a 0 in, the same tree, and a 0 fed
# back in its place shifts the register on without feedback; pin 3, held at
# 0, is both. The PULL between bytes breaks a body, so the four are written
# out. 180 words, 90 distinct. Written by gen.py.

CONFIG shift_dir, 1             # MSB first: a sample enters at bit 0 and ages upward
SET 3, 0                        # pin 3: the 0 the emission feeds in
PULL                            # byte 0
b0: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b0e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b0o1                        # 1: odd
b0e1: SKIP 1, 0                 # even so far: 0? step over: even still
JMP b0o2                        # 1: odd
b0e2: SKIP 9, 0                 # even so far: 0? step over: even still
JMP b0o3                        # 1: odd
b0e3: SKIP 13, 0                # even so far: 0? step over: even still
JMP b0o4                        # 1: odd
b0e4: SKIP 15, 0                # even so far: 0? step over: even still
JMP b0o5                        # 1: odd
b0e5: SKIP 21, 0                # even so far: 0? step over: even still
JMP b0o6                        # 1: odd
b0e6: SKIP 23, 0                # even so far: 0? step over: even still
JMP b0o7                        # 1: odd
b0e7: SKIP 29, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b0_f
b0o1: SKIP 1, 0                 # odd so far: 0? step over: odd still
JMP b0e2                        # 1: even
b0o2: SKIP 9, 0                 # odd so far: 0? step over: odd still
JMP b0e3                        # 1: even
b0o3: SKIP 13, 0                # odd so far: 0? step over: odd still
JMP b0e4                        # 1: even
b0o4: SKIP 15, 0                # odd so far: 0? step over: odd still
JMP b0e5                        # 1: even
b0o5: SKIP 21, 0                # odd so far: 0? step over: odd still
JMP b0e6                        # 1: even
b0o6: SKIP 23, 0                # odd so far: 0? step over: odd still
JMP b0e7                        # 1: even
b0o7: SKIP 29, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b0_f: SHIFT_IN 1                # f into the window
REPEAT 8, b0                    # the byte's eight bits
PULL                            # byte 1
b1: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b1e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b1o1                        # 1: odd
b1e1: SKIP 1, 0                 # even so far: 0? step over: even still
JMP b1o2                        # 1: odd
b1e2: SKIP 9, 0                 # even so far: 0? step over: even still
JMP b1o3                        # 1: odd
b1e3: SKIP 13, 0                # even so far: 0? step over: even still
JMP b1o4                        # 1: odd
b1e4: SKIP 15, 0                # even so far: 0? step over: even still
JMP b1o5                        # 1: odd
b1e5: SKIP 21, 0                # even so far: 0? step over: even still
JMP b1o6                        # 1: odd
b1e6: SKIP 23, 0                # even so far: 0? step over: even still
JMP b1o7                        # 1: odd
b1e7: SKIP 29, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b1_f
b1o1: SKIP 1, 0                 # odd so far: 0? step over: odd still
JMP b1e2                        # 1: even
b1o2: SKIP 9, 0                 # odd so far: 0? step over: odd still
JMP b1e3                        # 1: even
b1o3: SKIP 13, 0                # odd so far: 0? step over: odd still
JMP b1e4                        # 1: even
b1o4: SKIP 15, 0                # odd so far: 0? step over: odd still
JMP b1e5                        # 1: even
b1o5: SKIP 21, 0                # odd so far: 0? step over: odd still
JMP b1e6                        # 1: even
b1o6: SKIP 23, 0                # odd so far: 0? step over: odd still
JMP b1e7                        # 1: even
b1o7: SKIP 29, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b1_f: SHIFT_IN 1                # f into the window
REPEAT 8, b1                    # the byte's eight bits
PULL                            # byte 2
b2: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b2e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b2o1                        # 1: odd
b2e1: SKIP 1, 0                 # even so far: 0? step over: even still
JMP b2o2                        # 1: odd
b2e2: SKIP 9, 0                 # even so far: 0? step over: even still
JMP b2o3                        # 1: odd
b2e3: SKIP 13, 0                # even so far: 0? step over: even still
JMP b2o4                        # 1: odd
b2e4: SKIP 15, 0                # even so far: 0? step over: even still
JMP b2o5                        # 1: odd
b2e5: SKIP 21, 0                # even so far: 0? step over: even still
JMP b2o6                        # 1: odd
b2e6: SKIP 23, 0                # even so far: 0? step over: even still
JMP b2o7                        # 1: odd
b2e7: SKIP 29, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b2_f
b2o1: SKIP 1, 0                 # odd so far: 0? step over: odd still
JMP b2e2                        # 1: even
b2o2: SKIP 9, 0                 # odd so far: 0? step over: odd still
JMP b2e3                        # 1: even
b2o3: SKIP 13, 0                # odd so far: 0? step over: odd still
JMP b2e4                        # 1: even
b2o4: SKIP 15, 0                # odd so far: 0? step over: odd still
JMP b2e5                        # 1: even
b2o5: SKIP 21, 0                # odd so far: 0? step over: odd still
JMP b2e6                        # 1: even
b2o6: SKIP 23, 0                # odd so far: 0? step over: odd still
JMP b2e7                        # 1: even
b2o7: SKIP 29, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b2_f: SHIFT_IN 1                # f into the window
REPEAT 8, b2                    # the byte's eight bits
PULL                            # byte 3
b3: SHIFT_OUT 1, 0              # the data bit onto pin 0; pin 1 <- 0
SHIFT_IN 0                      # and back: the input, age 0
b3e0: SKIP 0, 0                 # even so far: 0? step over: even still
JMP b3o1                        # 1: odd
b3e1: SKIP 1, 0                 # even so far: 0? step over: even still
JMP b3o2                        # 1: odd
b3e2: SKIP 9, 0                 # even so far: 0? step over: even still
JMP b3o3                        # 1: odd
b3e3: SKIP 13, 0                # even so far: 0? step over: even still
JMP b3o4                        # 1: odd
b3e4: SKIP 15, 0                # even so far: 0? step over: even still
JMP b3o5                        # 1: odd
b3e5: SKIP 21, 0                # even so far: 0? step over: even still
JMP b3o6                        # 1: odd
b3e6: SKIP 23, 0                # even so far: 0? step over: even still
JMP b3o7                        # 1: odd
b3e7: SKIP 29, 0                # even so far: 0? step over: even
SET 1, 1                        # odd
JMP b3_f
b3o1: SKIP 1, 0                 # odd so far: 0? step over: odd still
JMP b3e2                        # 1: even
b3o2: SKIP 9, 0                 # odd so far: 0? step over: odd still
JMP b3e3                        # 1: even
b3o3: SKIP 13, 0                # odd so far: 0? step over: odd still
JMP b3e4                        # 1: even
b3o4: SKIP 15, 0                # odd so far: 0? step over: odd still
JMP b3e5                        # 1: even
b3o5: SKIP 21, 0                # odd so far: 0? step over: odd still
JMP b3e6                        # 1: even
b3o6: SKIP 23, 0                # odd so far: 0? step over: odd still
JMP b3e7                        # 1: even
b3o7: SKIP 29, 1                # odd so far: 1? step over: even
SET 1, 1                        # odd
b3_f: SHIFT_IN 1                # f into the window
REPEAT 8, b3                    # the byte's eight bits
crc: SHIFT_IN 3, 1, 0           # a 0 in, age 0; pin 1 <- 0
ce0: SKIP 0, 0                  # even so far: 0? step over: even still
JMP co1                         # 1: odd
ce1: SKIP 1, 0                  # even so far: 0? step over: even still
JMP co2                         # 1: odd
ce2: SKIP 9, 0                  # even so far: 0? step over: even still
JMP co3                         # 1: odd
ce3: SKIP 13, 0                 # even so far: 0? step over: even still
JMP co4                         # 1: odd
ce4: SKIP 15, 0                 # even so far: 0? step over: even still
JMP co5                         # 1: odd
ce5: SKIP 21, 0                 # even so far: 0? step over: even still
JMP co6                         # 1: odd
ce6: SKIP 23, 0                 # even so far: 0? step over: even still
JMP co7                         # 1: odd
ce7: SKIP 29, 0                 # even so far: 0? step over: even
SET 1, 1                        # odd
JMP c_f
co1: SKIP 1, 0                  # odd so far: 0? step over: odd still
JMP ce2                         # 1: even
co2: SKIP 9, 0                  # odd so far: 0? step over: odd still
JMP ce3                         # 1: even
co3: SKIP 13, 0                 # odd so far: 0? step over: odd still
JMP ce4                         # 1: even
co4: SKIP 15, 0                 # odd so far: 0? step over: odd still
JMP ce5                         # 1: even
co5: SKIP 21, 0                 # odd so far: 0? step over: odd still
JMP ce6                         # 1: even
co6: SKIP 23, 0                 # odd so far: 0? step over: odd still
JMP ce7                         # 1: even
co7: SKIP 29, 1                 # odd so far: 1? step over: even
SET 1, 1                        # odd
c_f: SHIFT_IN 3                 # a 0 back for the feedback: the register shifts on
REPEAT 15, crc                  # pin 1 holds the CRC's bit as the REPEAT issues; halted after the last
