/*
 * Holding-register write validation. See inv/settings_validate.h and docs/39 T04.
 *
 * Mirrors the factory's observed dongle behaviour: out-of-range -> reject with
 * MB_EXC_ILLEGAL_VALUE (value not stored), read-only -> MB_EXC_SLAVE_FAILURE.
 * The enforced ranges below are the factory's *actual* enforced bounds (recovered
 * by the oracle), which for a few registers are looser than the published spec --
 * those deviations are catalogued in docs/31 and replicated here for parity.
 */
#include "inv/settings_validate.h"
#include "inv/modbus_map.h"

#define NO_MAX 0xFFFFu          /* "this register enforces no upper bound" */

/* reg -> [lo, hi] inclusive. Out-of-range writes draw MB_EXC_ILLEGAL_VALUE. */
typedef struct { uint16_t reg, lo, hi; } sv_range_t;
static const sv_range_t RANGES[] = {
    { HR_COM_ADDR,        0, 150    },   /* HR 15: Modbus slave address              */
    { HR_PV_INPUT_MODEL,  0,   7    },   /* HR 20: PV routing model                  */
    { HR_ACCHG_POWER_PCT, 0, 100    },   /* HR 66: AC-charge power %                  */
    { HR_EOD,            10, NO_MAX },   /* HR 105: factory checks the lower bound
                                            only -- accepts > 90 (docs/31). spec 10-90 */
    { HR_CHARGE_CURR,     0, NO_MAX },   /* HR 101: factory enforces no upper bound --
                                            accepts > 140 (docs/31). spec 0-140        */
};

/* Registers a write must not change: the factory answers a write with an
 * exception (FW-version words are reported, not set). */
static const uint16_t READONLY[] = { HR_SLAVE_COM_VER, HR_CNTL_FW_VER };  /* HR 9, 10 */

sv_result_t settings_validate(uint16_t reg, uint16_t val)
{
    sv_result_t r = { val, MB_OK };

    for (unsigned i = 0; i < sizeof READONLY / sizeof READONLY[0]; i++)
        if (reg == READONLY[i]) { r.exc = MB_EXC_SLAVE_FAILURE; return r; }

    for (unsigned i = 0; i < sizeof RANGES / sizeof RANGES[0]; i++) {
        if (reg == RANGES[i].reg) {
            if (val < RANGES[i].lo || val > RANGES[i].hi)
                r.exc = MB_EXC_ILLEGAL_VALUE;
            return r;
        }
    }
    return r;   /* registers without a recovered range: accept verbatim */
}
