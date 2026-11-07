/* Host tests for the discharge-by-voltage hysteresis gate (docs/41, T15). make test
 * Mirrors the shared vectors in tests/dischg_gate_contract.py (factory oracle). */
#include "inv/dischg_gate.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

/* Bank word for a battery voltage of `v` (divided units): the gate does bank/10. */
#define BANK(v) ((uint16_t)((v) * 10))

int main(void)
{
    const uint16_t START = 480, STOP = 460;   /* deadband 460..480 */

    /* From OFF: turn on only at/above START (start-inclusive). */
    CHECK(inv_dischg_volt_gate(false, BANK(450), START, STOP) == false, "off: 450 < start -> off");
    CHECK(inv_dischg_volt_gate(false, BANK(479), START, STOP) == false, "off: 479 < start -> off");
    CHECK(inv_dischg_volt_gate(false, BANK(480), START, STOP) == true,  "off: 480 == start -> on");
    CHECK(inv_dischg_volt_gate(false, BANK(500), START, STOP) == true,  "off: 500 > start -> on");
    /* In the deadband from OFF, stay off (must reach START, not just STOP). */
    CHECK(inv_dischg_volt_gate(false, BANK(460), START, STOP) == false, "off: 460 in band -> stays off");
    CHECK(inv_dischg_volt_gate(false, BANK(470), START, STOP) == false, "off: 470 in band -> stays off");

    /* From ON: stay on until V drops BELOW STOP (stop is the turn-off edge). */
    CHECK(inv_dischg_volt_gate(true, BANK(500), START, STOP) == true,  "on: 500 -> stays on");
    CHECK(inv_dischg_volt_gate(true, BANK(480), START, STOP) == true,  "on: 480 -> stays on");
    CHECK(inv_dischg_volt_gate(true, BANK(460), START, STOP) == true,  "on: 460 == stop -> stays on");
    CHECK(inv_dischg_volt_gate(true, BANK(459), START, STOP) == false, "on: 459 < stop -> off");
    CHECK(inv_dischg_volt_gate(true, BANK(450), START, STOP) == false, "on: 450 < stop -> off");
    /* In the deadband from ON, stay on (hysteresis latch). */
    CHECK(inv_dischg_volt_gate(true, BANK(470), START, STOP) == true,  "on: 470 in band -> stays on");

    /* The /10 divide: bank is finer-grained than the threshold. 4799/10 = 479 < 480. */
    CHECK(inv_dischg_volt_gate(false, 4799, START, STOP) == false, "off: bank 4799 -> 479 -> off");
    CHECK(inv_dischg_volt_gate(false, 4800, START, STOP) == true,  "off: bank 4800 -> 480 -> on");

    /* --- discharge-by-SOC gate (same hysteresis on the SOC byte; verdict 0x2000dbc4) */
    const uint8_t SSTART = 50, SSTOP = 40;    /* SOC deadband 40..50 */
    /* From OFF: turn on only at/above start. */
    CHECK(inv_dischg_soc_gate(false, 39, SSTART, SSTOP) == false, "soc off: 39 < start -> off");
    CHECK(inv_dischg_soc_gate(false, 49, SSTART, SSTOP) == false, "soc off: 49 < start -> off");
    CHECK(inv_dischg_soc_gate(false, 50, SSTART, SSTOP) == true,  "soc off: 50 == start -> on");
    CHECK(inv_dischg_soc_gate(false, 60, SSTART, SSTOP) == true,  "soc off: 60 > start -> on");
    CHECK(inv_dischg_soc_gate(false, 45, SSTART, SSTOP) == false, "soc off: 45 in band -> stays off");
    /* From ON: stay on until SOC drops below stop. */
    CHECK(inv_dischg_soc_gate(true, 60, SSTART, SSTOP) == true,  "soc on: 60 -> stays on");
    CHECK(inv_dischg_soc_gate(true, 50, SSTART, SSTOP) == true,  "soc on: 50 -> stays on");
    CHECK(inv_dischg_soc_gate(true, 40, SSTART, SSTOP) == true,  "soc on: 40 == stop -> stays on");
    CHECK(inv_dischg_soc_gate(true, 39, SSTART, SSTOP) == false, "soc on: 39 < stop -> off");
    CHECK(inv_dischg_soc_gate(true, 45, SSTART, SSTOP) == true,  "soc on: 45 in band -> stays on");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
