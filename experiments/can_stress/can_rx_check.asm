# 6C with a stuff check and a CRC delimiter check that answer with an
# error flag: the JMPs out of the bodies are patched in, the assembler refuses them. rc is drained after.
# 76 words, 40 distinct.

CONFIG open_drain01, 1
CONFIG shift_dir, 1
PULL
ACC_LOAD
PULL
ACC_LOAD
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
sof: SHIFT_IN 0
WAIT 0, 0 [4]
c0: SHIFT_IN 0
ACC_CRC 0
PUSH
SKIP_NORUN 5, 1
JMP c0s [3]
SKIP_NORUN 5, 0
JMP c0s [2]
JMP c0e [1]
c0s: SHIFT_IN 0
SKIP_NORUN 2, 0
JMP c0e  # PATCH err
SKIP_NORUN 2, 1
JMP c0e  # PATCH err
NOP [3]
c0e: REPEAT 32, c0
c1: SHIFT_IN 0
ACC_CRC 0
PUSH
SKIP_NORUN 5, 1
JMP c1s [3]
SKIP_NORUN 5, 0
JMP c1s [2]
JMP c1e [1]
c1s: SHIFT_IN 0
SKIP_NORUN 2, 0
JMP c1e  # PATCH err
SKIP_NORUN 2, 1
JMP c1e  # PATCH err
NOP [3]
c1e: REPEAT 10, c1
SHIFT_IN 0
SKIP 0, 1
JMP err
SET 0, 0 [7]
SET 0, 1 [7]
gap: NOP [6]
REPEAT 9, gap
ACC_PUSH
ACC_PUSH
JMP sof
err: SET 0, 0
SHIFT_IN 0 [4]
SHIFT_IN 0 [5]
SHIFT_IN 0 [5]
SHIFT_IN 0 [5]
SHIFT_IN 0 [5]
SHIFT_IN 0 [5]
SHIFT_IN 0 [5]
SHIFT_IN 0 [5]
SET 0, 1
PUSH
drain: NOP
REPEAT 1, drain
clr: ACC_OUT 3
REPEAT 16, clr
JMP listen
