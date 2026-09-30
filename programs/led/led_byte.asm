# The host's byte on the LEDs: gpio[3:0] <- the low nibble of each byte from
# the TX FIFO, then wait for the next, forever. Nothing on the core writes
# four pins at once, so the byte goes through the accumulator: ACC_LOAD twice
# puts it in both halves of poly, and ACC_CRC on a pad that reads 1 with acc
# 0 feeds back once, acc <- poly (f = acc[15] ^ 1 = 1). Sixteen ACC_OUTs
# empty acc again for the next byte, the last four onto pins 3, 2, 1, 0:
# acc bits 3..0, the byte's low nibble. The first twelve go to gpio 0, which
# also starts the byte high for ACC_CRC to read: it flickers for 26 clocks
# of the 35 a byte takes, the other three pins move once. gpio_in 0 is the readback of pad
# 0: nothing outside may hold it low. The LEDs are LD0..LD3 on the PYNQ-Z2.

loop:   PULL                # shift_reg <- the byte (stalls while the FIFO is empty)
        ACC_LOAD            # poly <- {byte, poly[15:8]}
        ACC_LOAD            # poly <- {byte, byte}
        SET 0, 1            # pad 0 high, so gpio_in 0 reads 1 next clock
        ACC_CRC 0           # acc was 0: f = 1, acc <- poly
drain:  ACC_OUT 0           # acc[15:4] out on gpio 0, twelve clocks
        REPEAT 12, drain
        ACC_OUT 3           # acc[3], the byte's bit 3
        ACC_OUT 2           # bit 2
        ACC_OUT 1           # bit 1
        ACC_OUT 0           # bit 0; acc is 0 again
        JMP loop
