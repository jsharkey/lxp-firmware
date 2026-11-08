/* Host tests for the generator-charge-by-voltage hysteresis gate (T16, docs HR194_198).
 * make test. Mirrors the factory-verified vectors in tests/gen_charge_contract.py. */
#include "inv/gen_charge.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

#define BANK(v) ((uint16_t)((v) * 10))      /* bank word for battery voltage v (/10) */

int main(void)
{
    const uint16_t START = 464, END = 480;   /* HR194 start-V, HR195 end-V */

    /* From OFF: start charging only when battery is BELOW start (charge direction). */
    CHECK(inv_gen_charge_volt_gate(false, BANK(450), START, END, true) == true,  "off: 450 < start -> charge on");
    CHECK(inv_gen_charge_volt_gate(false, BANK(463), START, END, true) == true,  "off: 463 < start -> on");
    CHECK(inv_gen_charge_volt_gate(false, BANK(464), START, END, true) == false, "off: 464 == start -> stays off");
    CHECK(inv_gen_charge_volt_gate(false, BANK(490), START, END, true) == false, "off: 490 > start -> off");
    /* In the deadband from OFF, stay off (must drop below start). */
    CHECK(inv_gen_charge_volt_gate(false, BANK(470), START, END, true) == false, "off: 470 in band -> stays off");

    /* From ON: stop only when battery reaches end AND the DSP confirms (stop_ok). */
    CHECK(inv_gen_charge_volt_gate(true, BANK(450), START, END, true) == true,  "on: 450 -> stays on");
    CHECK(inv_gen_charge_volt_gate(true, BANK(479), START, END, true) == true,  "on: 479 < end -> stays on");
    CHECK(inv_gen_charge_volt_gate(true, BANK(480), START, END, true) == false, "on: 480 == end + confirm -> off");
    CHECK(inv_gen_charge_volt_gate(true, BANK(490), START, END, true) == false, "on: 490 > end + confirm -> off");
    /* In the deadband from ON, stay on (hysteresis latch). */
    CHECK(inv_gen_charge_volt_gate(true, BANK(470), START, END, true) == true,  "on: 470 in band -> stays on");

    /* Stop is gated on the DSP confirmation: without stop_ok, it keeps charging even above end. */
    CHECK(inv_gen_charge_volt_gate(true, BANK(490), START, END, false) == true, "on: 490 but no confirm -> stays on");
    CHECK(inv_gen_charge_volt_gate(true, BANK(480), START, END, false) == true, "on: 480 but no confirm -> stays on");

    /* The /10 divide: bank is finer-grained than the threshold. 4639/10 = 463 < 464. */
    CHECK(inv_gen_charge_volt_gate(false, 4639, START, END, true) == true,  "off: bank 4639 -> 463 -> on");
    CHECK(inv_gen_charge_volt_gate(false, 4640, START, END, true) == false, "off: bank 4640 -> 464 -> off");

    /* --- SOC sibling (GenChargeType = 1): same hysteresis on the SOC byte. --- */
    const uint8_t SSTART = 20, SEND = 100;   /* HR196 start-SOC, HR197 end-SOC (%) */

    /* From OFF: start charging only when SOC is BELOW start. */
    CHECK(inv_gen_charge_soc_gate(false, 10, SSTART, SEND, true) == true,  "soc off: 10 < start -> on");
    CHECK(inv_gen_charge_soc_gate(false, 19, SSTART, SEND, true) == true,  "soc off: 19 < start -> on");
    CHECK(inv_gen_charge_soc_gate(false, 20, SSTART, SEND, true) == false, "soc off: 20 == start -> off");
    CHECK(inv_gen_charge_soc_gate(false, 50, SSTART, SEND, true) == false, "soc off: 50 in band -> off");
    /* From ON: stop only at end AND with the DSP confirm. */
    CHECK(inv_gen_charge_soc_gate(true, 50, SSTART, SEND, true) == true,   "soc on: 50 in band -> stays on");
    CHECK(inv_gen_charge_soc_gate(true, 99, SSTART, SEND, true) == true,   "soc on: 99 < end -> stays on");
    CHECK(inv_gen_charge_soc_gate(true, 100, SSTART, SEND, true) == false, "soc on: 100 == end + confirm -> off");
    CHECK(inv_gen_charge_soc_gate(true, 100, SSTART, SEND, false) == true, "soc on: 100 but no confirm -> stays on");

    /* --- Combined controller: HR120 bit7 selects which latch is returned. --- */
    inv_gen_charge_state_t st = {false, false};
    /* by voltage (charge_by_soc=false): low V starts, SOC path irrelevant to the verdict. */
    CHECK(inv_gen_charge_permit(&st, false, BANK(450), START, END, 90, SSTART, SEND, true) == true,
          "permit volt: low V -> charge");
    CHECK(st.v_active == true && st.s_active == false, "permit: both latches stepped (V on, SOC off at 90)");
    /* by SOC (charge_by_soc=true): returns the SOC latch instead. */
    inv_gen_charge_state_t st2 = {false, false};
    CHECK(inv_gen_charge_permit(&st2, true, BANK(500), START, END, 10, SSTART, SEND, true) == true,
          "permit soc: low SOC -> charge (even though V high)");
    CHECK(st2.v_active == false && st2.s_active == true, "permit: V latch off (500>start), SOC latch on (10<start)");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
