/* Host tests for the HR 11 ResetSetting command dispatcher.  make test
 *
 * Verifies that each command bit invokes exactly its op, NULL ops are skipped
 * (and not counted as acted), reserved bits are ignored, reboot runs last, and
 * the returned mask reflects the bits actually acted on. docs/39 T12.
 */
#include "inv/command.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

/* call log */
static int seq[16], nseq;
enum { E_ENERGY=1, E_DEFAULT, E_ADJ, E_FAULT, E_MON, E_CHG, E_DISCHG, E_REBOOT };
static void push(int e){ if (nseq < 16) seq[nseq++] = e; }
static void energy(void){ push(E_ENERGY); }
static void defaults(void){ push(E_DEFAULT); }
static void adj(void){ push(E_ADJ); }
static void fault(void){ push(E_FAULT); }
static void mon(void){ push(E_MON); }
static void chg(void){ push(E_CHG); }
static void dischg(void){ push(E_DISCHG); }
static void reboot(void){ push(E_REBOOT); }

static const inv_cmd_ops_t FULL = {
    energy, defaults, adj, fault, mon, chg, dischg, reboot
};

int main(void)
{
    uint16_t acted;

    /* each single bit calls exactly its op */
    struct { uint16_t bit; int ev; } one[] = {
        {INV_CMD_ENERGY_CLR,E_ENERGY},{INV_CMD_ALL_DEFAULT,E_DEFAULT},
        {INV_CMD_ADJRATIO_CLR,E_ADJ},{INV_CMD_FAULT_CLR,E_FAULT},
        {INV_CMD_MONITOR_CLR,E_MON},{INV_CMD_BMS_CHG_ON,E_CHG},
        {INV_CMD_BMS_DISCHG_ON,E_DISCHG},{INV_CMD_INV_REBOOT,E_REBOOT},
    };
    for (unsigned i = 0; i < sizeof(one)/sizeof(one[0]); i++) {
        nseq = 0;
        acted = inv_command_apply(one[i].bit, &FULL);
        CHECK(acted == one[i].bit, "single bit -> acted==bit");
        CHECK(nseq == 1 && seq[0] == one[i].ev, "single bit -> exactly its op");
    }

    /* all bits: every op runs, reboot is LAST */
    nseq = 0;
    acted = inv_command_apply(0x00FF, &FULL);
    CHECK(acted == 0x00FF, "all known bits acted");
    CHECK(nseq == 8, "all eight ops ran");
    CHECK(seq[nseq-1] == E_REBOOT, "reboot runs last");

    /* reserved bits (8-15) ignored */
    nseq = 0;
    acted = inv_command_apply(0xFF00, &FULL);
    CHECK(acted == 0 && nseq == 0, "reserved bits do nothing");

    /* NULL ops skipped and not counted (ours wires only a subset) */
    const inv_cmd_ops_t partial = { energy, 0,0,0,0, chg, dischg, reboot };
    nseq = 0;
    acted = inv_command_apply(0x00FF, &partial);
    CHECK(acted == (INV_CMD_ENERGY_CLR|INV_CMD_BMS_CHG_ON|INV_CMD_BMS_DISCHG_ON|INV_CMD_INV_REBOOT),
          "only non-NULL ops counted as acted");
    CHECK(nseq == 4, "NULL ops skipped");

    /* a no-op word and a NULL ops table are safe */
    CHECK(inv_command_apply(0, &FULL) == 0, "zero word -> nothing");
    CHECK(inv_command_apply(0x00FF, 0) == 0, "NULL ops -> nothing");

    printf("test_command: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
