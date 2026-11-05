/*
 * Host unit tests for the SPSC ring buffer (inv/ringbuf.h) behind the
 * interrupt-driven UART/CAN drivers. Build & run:  make test
 */
#include "inv/ringbuf.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(cond, msg) do { g_run++; if (!(cond)) { \
    printf("  FAIL: %s  (%s:%d)\n", msg, __FILE__, __LINE__); g_fail++; } } while (0)

int main(void) {
    uint8_t store[8];                 /* size 8 ring holds 7 bytes */
    ringbuf_t r;
    rb_init(&r, store, sizeof store);
    uint8_t b;

    CHECK(rb_is_empty(&r), "fresh ring is empty");
    CHECK(!rb_is_full(&r), "fresh ring is not full");
    CHECK(rb_count(&r) == 0, "fresh count 0");
    CHECK(!rb_get(&r, &b), "get on empty fails");

    /* fill to capacity (size-1 = 7) */
    for (int i = 0; i < 7; i++) CHECK(rb_put(&r, (uint8_t)(0x10 + i)), "put within capacity");
    CHECK(rb_is_full(&r), "full after size-1 puts");
    CHECK(rb_count(&r) == 7, "count == 7 when full");
    CHECK(!rb_put(&r, 0xFF), "put on full drops");

    /* drain in order (FIFO) */
    for (int i = 0; i < 7; i++) {
        CHECK(rb_get(&r, &b), "get within count");
        CHECK(b == (uint8_t)(0x10 + i), "FIFO order preserved");
    }
    CHECK(rb_is_empty(&r), "empty after draining");
    CHECK(!rb_get(&r, &b), "get on drained-empty fails");

    /* wrap-around: head/tail cross the size boundary repeatedly */
    uint8_t expect = 0;
    for (int round = 0; round < 100; round++) {
        for (int i = 0; i < 5; i++) CHECK(rb_put(&r, expect++), "wrap put");
        for (int i = 0; i < 5; i++) {
            uint8_t got;
            CHECK(rb_get(&r, &got), "wrap get");
            CHECK(got == (uint8_t)(expect - 5 + i), "wrap value integrity");
        }
    }
    CHECK(rb_is_empty(&r), "empty after wrap rounds");

    printf("test_ringbuf: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
