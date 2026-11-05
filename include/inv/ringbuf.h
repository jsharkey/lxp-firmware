/*
 * Lock-free single-producer / single-consumer byte ring buffer.
 *
 * This is the primitive behind the interrupt-driven UART/CAN drivers: an ISR is
 * the sole producer for an RX ring (or the sole consumer for a TX ring) and the
 * main loop is the other end. On a single-core Cortex-M, an SPSC ring needs no
 * critical section — the producer only advances `head`, the consumer only
 * advances `tail`, and each is a naturally-atomic aligned 32-bit store. `volatile`
 * keeps the compiler from caching the index the other side updates.
 *
 * Capacity must be a power of two; one slot is reserved to distinguish full from
 * empty, so a size-N ring holds N-1 bytes. Header-only and MMIO-free, so it is
 * compiled and unit-tested on the host (tests/test_ringbuf.c).
 */
#ifndef INV_RINGBUF_H
#define INV_RINGBUF_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef struct {
    uint8_t         *buf;
    uint32_t         size;          /* power of two */
    volatile uint32_t head;         /* producer writes */
    volatile uint32_t tail;         /* consumer writes */
} ringbuf_t;

static inline void rb_init(ringbuf_t *r, uint8_t *storage, uint32_t size_pow2)
{
    r->buf = storage;
    r->size = size_pow2;
    r->head = 0;
    r->tail = 0;
}

static inline bool rb_is_empty(const ringbuf_t *r) { return r->head == r->tail; }

static inline uint32_t rb_count(const ringbuf_t *r)
{
    return (r->head - r->tail) & (r->size - 1);
}

static inline bool rb_is_full(const ringbuf_t *r)
{
    return (((r->head + 1) & (r->size - 1)) == r->tail);
}

/* Producer side. Returns false (drops the byte) when full. */
static inline bool rb_put(ringbuf_t *r, uint8_t b)
{
    uint32_t h = r->head;
    uint32_t n = (h + 1) & (r->size - 1);
    if (n == r->tail) return false;     /* full */
    r->buf[h] = b;
    r->head = n;                        /* publish after the data store */
    return true;
}

/* Consumer side. Returns false when empty. */
static inline bool rb_get(ringbuf_t *r, uint8_t *out)
{
    uint32_t t = r->tail;
    if (t == r->head) return false;     /* empty */
    *out = r->buf[t];
    r->tail = (t + 1) & (r->size - 1);
    return true;
}

#endif /* INV_RINGBUF_H */
