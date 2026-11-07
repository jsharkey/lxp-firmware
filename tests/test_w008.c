/* Host tests for the W008 (FW-version mismatch) source and the relayed DSP
 * version read-back (HR 10 low).  make test
 *
 * W008 is raised when the peer identity the safety CPU relays (g_safety_bank
 * +3..6) does not match the model's 4-char identity, a case-insensitive compare
 * (factory sub_0801a93a vs "ceaa"; docs/32, docs/33 §tag-0, T02b/T12). The
 * default host build is the 12000XP variant, whose model_code is "ceaa".
 */
#include "inv/safety_cpu.h"
#include "inv/variant.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

static void set_ident(const char *s)
{
    memset(g_safety_bank, 0, SAFETY_BANK_SIZE);
    for (unsigned i = 0; i < SAFETY_IDENT_LEN && s[i]; i++)
        g_safety_bank[SAFETY_OFF_IDENT + i] = (uint8_t)s[i];
}

int main(void)
{
    /* --- the pure compare helper (model-code agnostic) --- */
    const uint8_t ceaa[4] = { 'c', 'e', 'a', 'a' };
    const uint8_t CEAA[4] = { 'C', 'E', 'A', 'A' };
    const uint8_t cEaA[4] = { 'c', 'E', 'a', 'A' };
    const uint8_t zero[4] = { 0, 0, 0, 0 };
    const uint8_t wrong[4] = { 'f', 'a', 'a', 'b' };
    const uint8_t pre3[4] = { 'c', 'e', 'a', 'x' };  /* first 3 match, 4th differs */

    CHECK(inv_fw_ident_matches(ceaa, "ceaa"),  "exact match");
    CHECK(inv_fw_ident_matches(CEAA, "ceaa"),  "uppercase relayed matches (case-insensitive)");
    CHECK(inv_fw_ident_matches(ceaa, "CEAA"),  "uppercase model_code matches");
    CHECK(inv_fw_ident_matches(cEaA, "ceaa"),  "mixed case matches");
    CHECK(!inv_fw_ident_matches(zero, "ceaa"), "all-zero identity -> mismatch");
    CHECK(!inv_fw_ident_matches(wrong, "ceaa"), "different code -> mismatch");
    CHECK(!inv_fw_ident_matches(pre3, "ceaa"), "last char differs -> mismatch");
    CHECK(!inv_fw_ident_matches(ceaa, "cea"),  "model_code shorter than 4 -> no match");
    CHECK(!inv_fw_ident_matches(ceaa, 0),      "NULL model_code -> no match");

    /* --- the LATCHED bank-driven mismatch against the active variant (ceaa) ---
     * safety_cpu_fw_mismatch() latches OK once a matching identity is seen (the
     * factory health bit), so the mismatch states must be observed BEFORE the first
     * match within this single process. */
    CHECK(strcmp(inv_variant()->model_code, "ceaa") == 0, "host build is the 12000XP (ceaa)");

    memset(g_safety_bank, 0, SAFETY_BANK_SIZE);
    CHECK(safety_cpu_fw_mismatch(), "bare bank (no safety link) -> W008 raised");

    set_ident("zzzz");
    CHECK(safety_cpu_fw_mismatch(), "wrong relayed identity -> W008 still raised");

    set_ident("CEAA");
    CHECK(!safety_cpu_fw_mismatch(), "case-insensitive match -> W008 clears (latches OK)");

    set_ident("zzzz");
    CHECK(!safety_cpu_fw_mismatch(), "after a match, W008 stays clear (latched, factory parity)");

    /* --- DSP version read-back (HR 10 low, bank+2) --- */
    memset(g_safety_bank, 0, SAFETY_BANK_SIZE);
    CHECK(safety_cpu_dsp_version() == 0, "no link -> DSP version 0");
    g_safety_bank[SAFETY_OFF_DSP_VER] = 0x2a;
    CHECK(safety_cpu_dsp_version() == 0x2a, "DSP version read from bank+2");

    printf("test_w008: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
