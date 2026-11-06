/*
 * Operating-state classifier + fault/warning composer -- see inv/classify.h.
 *
 * docs/22 (the ARM/DSP split) establishes the shape: the ARM mostly PASSES
 * THROUGH the received mode byte as IR 0, with a not-running/fault override and
 * a canonicalisation of non-standard bytes; and it MERGES the relayed 32-bit
 * fault/warn words with a few ARM-local bits for IR 60-63.
 */
#include "inv/classify.h"
#include "inv/states.h"

bool inv_state_is_canonical(uint8_t m)
{
    switch (m) {
    /* Table 9 (IR000-State.md) */
    case STATE_STANDBY:           /* 0x00 */
    case STATE_FAULT:             /* 0x01 */
    case STATE_PROGRAMMING:       /* 0x02 */
    case STATE_PV_ONGRID:         /* 0x04 */
    case STATE_PV_CHARGE:         /* 0x08 */
    case STATE_PV_CHARGE_ONGRID:  /* 0x0C */
    case STATE_BAT_ONGRID:        /* 0x10 */
    case STATE_PV_BAT_ONGRID:     /* 0x14 */
    case STATE_AC_CHARGE:         /* 0x20 */
    case STATE_PV_AC_CHARGE:      /* 0x28 */
    case STATE_BAT_OFFGRID:       /* 0x40 */
    case STATE_PV_OFFGRID:        /* 0x80 */
    case STATE_PV_CHARGE_OFFGRID: /* 0x88 */
    case STATE_PV_BAT_OFFGRID:    /* 0xC0 */
    /* LCD-only status codes (IR000-State.md "On the LCD"): the manual's §17.3
     * table adds these two beyond the Modbus operating-mode table. */
    case 0x11:                    /* Bypass */
    case 0x19:                    /* PV Charge + Bypass */
        return true;
    default:
        return false;
    }
}

inv_class_t inv_classify(uint8_t mode_byte, uint32_t relayed_fault,
                         uint32_t relayed_warn, uint32_t local_flags)
{
    inv_class_t out;

    /* --- FaultCode (IR 60/61): relayed word + ARM-local bits ---------------
     * Most bits pass through from the safety-CPU frame verbatim; the ARM sets
     * E000 (bit 0) and E017 (bit 17) itself. E027 (bit 27) is the frame's own
     * "sample mismatch" verdict, so it is left to pass through. (IR060_063.) */
    out.fault = relayed_fault;
    if (local_flags & INV_LOCAL_FAULT_E000)
        out.fault |= (1u << INV_FAULT_BIT_E000);
    if (local_flags & INV_LOCAL_FAULT_E017)
        out.fault |= (1u << INV_FAULT_BIT_E017);

    /* --- WarningCode (IR 62/63): relayed word + ARM-local W008 -------------
     * The grid/high warnings come from the frame; W008 (FW-version mismatch,
     * bit 8) is computed on the ARM from the per-processor version compare. */
    out.warn = relayed_warn;
    if (local_flags & INV_LOCAL_WARN_W008)
        out.warn |= (1u << INV_WARN_BIT_W008);

    /* --- State (IR 0): canonicalised pass-through with a fault override -----
     * Documented behaviour (docs/22): a fault / not-running condition overrides
     * the mode, and a non-canonical byte is canonicalised. We report a fault
     * condition as STATE_FAULT and a non-canonical byte as STATE_STANDBY.
     *
     * NOT-YET-ORACLE-VERIFIED (docs/39 T06b): docs/22's prose gives the override
     * target as 0x02 and a canonicalisation default of 0x08, but those were read
     * from a 05-series image whose addresses have drifted; the 07 classifier is
     * not re-pinned yet, so the exact override code and unknown-byte default are
     * provisional. The composition above and the pass-through of canonical modes
     * are solid; these two choices are the open points for the factory oracle. */
    if ((out.fault != 0u) || (local_flags & INV_LOCAL_NOT_RUNNING))
        out.state = (uint16_t)STATE_FAULT;
    else if (inv_state_is_canonical(mode_byte))
        out.state = mode_byte;
    else
        out.state = (uint16_t)STATE_STANDBY;

    return out;
}
