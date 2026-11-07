/* Host tests for the operating-state classifier + fault/warn composer.  make test
 *
 * Covers the fault & warn bit composition (relayed word + ARM-local
 * E000/E017/W008, E027 pass-through) and the state pass-through. State is a PURE
 * PASS-THROUGH of the relayed mode byte -- no canonicalisation, no fault override
 * -- pinned against the factory 07 oracle (docs/39 T06b; the wire-fed factory and
 * ours sim checks are in test_arm_sim_*.py). docs/22, docs/39 T06.
 */
#include "inv/classify.h"
#include "inv/states.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

int main(void)
{
    inv_class_t r;

    /* --- state: canonical modes pass through verbatim --------------------- */
    const uint8_t modes[] = {0x00,0x01,0x02,0x04,0x08,0x0C,0x10,0x14,
                             0x20,0x28,0x40,0x80,0x88,0xC0,0x11,0x19};
    for (unsigned i = 0; i < sizeof(modes); i++) {
        r = inv_classify(modes[i], 0, 0, 0);
        CHECK(r.state == modes[i], "canonical mode passes through");
        CHECK(inv_state_is_canonical(modes[i]), "canonical set membership");
    }

    /* --- state: non-canonical bytes ALSO pass through verbatim ------------
     * The 07 classifier does no canonicalisation (docs/39 T06b): an arbitrary
     * byte appears at IR_STATE unchanged. (inv_state_is_canonical() remains a
     * query helper for the documented mode set, but it does NOT gate IR_STATE.) */
    const uint8_t junk[] = {0x03,0x05,0x07,0x0D,0x13,0x21,0x7F,0xAA,0xFF};
    for (unsigned i = 0; i < sizeof(junk); i++) {
        CHECK(!inv_state_is_canonical(junk[i]), "non-canonical not in documented set");
        r = inv_classify(junk[i], 0, 0, 0);
        CHECK(r.state == junk[i], "non-canonical byte passes through verbatim");
    }

    /* --- state: a relayed/local fault does NOT change State ----------------
     * The fault flows to the FaultCode (IR 60/61); IR_STATE stays the mode byte
     * (the DSP itself encodes Fault 0x01 / Standby 0x00 into the mode). */
    r = inv_classify(STATE_BAT_ONGRID, (1u << 19), 0, 0);    /* E019 relayed */
    CHECK(r.state == STATE_BAT_ONGRID, "a relayed fault does NOT override state");
    CHECK(r.fault == (1u << 19), "...it composes into the FaultCode instead");
    r = inv_classify(STATE_PV_ONGRID, 0, 0, INV_LOCAL_FAULT_E000);
    CHECK(r.state == STATE_PV_ONGRID, "an ARM-local fault does NOT override state");
    r = inv_classify(STATE_BAT_ONGRID, 0, 0xFFFFFFFFu, 0);   /* warnings only */
    CHECK(r.state == STATE_BAT_ONGRID, "warnings alone do NOT change state");

    /* --- FaultCode composition (IR 60/61) --------------------------------- */
    r = inv_classify(STATE_STANDBY, 0, 0, 0);
    CHECK(r.fault == 0, "no fault bits when clean");
    r = inv_classify(STATE_STANDBY, 0, 0, INV_LOCAL_FAULT_E000);
    CHECK(r.fault == (1u << 0), "E000 set locally -> fault bit 0");
    r = inv_classify(STATE_STANDBY, 0, 0, INV_LOCAL_FAULT_E017);
    CHECK(r.fault == (1u << 17), "E017 set locally -> fault bit 17");
    /* relayed word passes through; E027 (bit 27, frame's own) survives; local
     * E000/E017 OR in on top. */
    r = inv_classify(STATE_STANDBY, (1u << 27) | (1u << 16), 0,
                     INV_LOCAL_FAULT_E000 | INV_LOCAL_FAULT_E017);
    CHECK(r.fault == ((1u<<27)|(1u<<16)|(1u<<0)|(1u<<17)),
          "relayed E027+E016 merged with local E000+E017");

    /* --- WarningCode composition (IR 62/63) ------------------------------- */
    r = inv_classify(STATE_STANDBY, 0, 0, 0);
    CHECK(r.warn == 0, "no warn bits when clean");
    r = inv_classify(STATE_STANDBY, 0, 0, INV_LOCAL_WARN_W008);
    CHECK(r.warn == (1u << 8), "W008 computed locally -> warn bit 8");
    r = inv_classify(STATE_STANDBY, 0, 0, INV_LOCAL_WARN_W000);
    CHECK(r.warn == (1u << 0), "W000 battery-comms-loss -> warn bit 0");
    /* relayed grid warnings (W016/17/18 high bits) pass through; local W008/W000 OR */
    r = inv_classify(STATE_STANDBY, 0, (1u << 16) | (1u << 17) | (1u << 18),
                     INV_LOCAL_WARN_W008 | INV_LOCAL_WARN_W000);
    CHECK(r.warn == ((1u<<16)|(1u<<17)|(1u<<18)|(1u<<8)|(1u<<0)),
          "relayed grid warnings merged with local W008 + W000");

    /* --- fault and warn are independent ----------------------------------- */
    r = inv_classify(STATE_AC_CHARGE, (1u << 22), (1u << 25),
                     INV_LOCAL_FAULT_E000 | INV_LOCAL_WARN_W008);
    CHECK(r.fault == ((1u<<22)|(1u<<0)), "fault word independent of warn");
    CHECK(r.warn  == ((1u<<25)|(1u<<8)), "warn word independent of fault");
    CHECK(r.state == STATE_AC_CHARGE, "state stays the mode byte regardless of fault/warn");

    printf("test_classify: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
