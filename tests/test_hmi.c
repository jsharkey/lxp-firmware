/* Host unit tests for the HMI navigation engine.  make test */
#include "inv/hmi.h"
#include "inv/modbus_map.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

static uint16_t input_regs[160], holding_regs[256];
static char rowtext[8][40];
static bool rowsel[8];
static int g_restore;

/* ACTION override (weak in model) */
void hmi_request_restore_defaults(void) { g_restore++; }

static bool io_read(hmi_regspace_t sp, uint16_t r, uint16_t *o) {
    if (sp == HMI_REG_INPUT  && r < 160) { *o = input_regs[r];  return true; }
    if (sp == HMI_REG_HOLDING && r < 256) { *o = holding_regs[r]; return true; }
    return false;
}
static bool io_write(uint16_t r, uint16_t v) {
    if (r < 256) { holding_regs[r] = v; return true; }
    return false;
}
static void io_draw(uint8_t row, const char *t, bool sel) {
    if (row < 8) { snprintf(rowtext[row], 40, "%s", t); rowsel[row] = sel; }
}
static void io_clear(void) { memset(rowtext, 0, sizeof rowtext); memset(rowsel, 0, sizeof rowsel); }
static const hmi_io_t io = { io_read, io_write, io_draw, io_clear, 4 };

static int selected_row(void) { for (int i=0;i<4;i++) if (rowsel[i]) return i; return -1; }

int main(void) {
    hmi_t h;

    /* format: scaled value with unit, and enum choice */
    char buf[24];
    const hmi_item_t vb = {"",HMI_INFO,HMI_REG_INPUT,IR_VBAT,0,0,0,10,"V",0,0,0,0};
    CHECK(strcmp(hmi_format_value(&vb, 525, buf, sizeof buf), "52.5V")==0, "format scaled");
    static const char *const ch[] = {"A","B","C"};
    const hmi_item_t en = {"",HMI_ENUM,HMI_REG_HOLDING,0,0,2,1,1,0,ch,3,0,0};
    CHECK(strcmp(hmi_format_value(&en, 2, buf, sizeof buf), "C")==0, "format enum");

    /* init + initial render */
    input_regs[IR_VBAT] = 520;
    hmi_init(&h, &hmi_root_menu, &io);
    hmi_render(&h);
    CHECK(selected_row()==0, "start selection row 0");
    CHECK(strncmp(rowtext[0], "State: ", 7)==0, "row0 is State");
    CHECK(strcmp(rowtext[1], "Battery Volt: 52.0V")==0, "row1 battery volt formatted");

    /* DOWN moves selection; scroll keeps it visible */
    for (int i=0;i<5;i++) hmi_key(&h, HMI_KEY_DOWN);
    hmi_render(&h);
    CHECK(selected_row()>=0 && selected_row()<4, "selection stays within window after scroll");

    /* go to EPS Voltage Set (index 4 = ENUM), edit it */
    hmi_init(&h, &hmi_root_menu, &io);
    for (int i=0;i<4;i++) hmi_key(&h, HMI_KEY_DOWN);     /* sel = 4 */
    holding_regs[HR_EPS_VOLT_SET] = 1;                   /* "230V" */
    hmi_key(&h, HMI_KEY_ENTER);                          /* enter edit */
    hmi_render(&h);
    CHECK(h.editing, "enter edit on ENUM");
    hmi_key(&h, HMI_KEY_UP); hmi_key(&h, HMI_KEY_UP);    /* 1->2->3 */
    hmi_key(&h, HMI_KEY_UP);                             /* clamp at max 3 */
    hmi_key(&h, HMI_KEY_ENTER);                          /* commit */
    CHECK(!h.editing, "commit exits edit");
    CHECK(holding_regs[HR_EPS_VOLT_SET]==3, "enum edit clamped+written (277V)");

    /* U16 edit with cancel (ESC discards) */
    hmi_init(&h, &hmi_root_menu, &io);
    for (int i=0;i<8;i++) hmi_key(&h, HMI_KEY_DOWN);     /* Charge Current Limit (idx 8) */
    holding_regs[HR_CHARGE_CURR] = 10;
    hmi_key(&h, HMI_KEY_ENTER);
    hmi_key(&h, HMI_KEY_UP); hmi_key(&h, HMI_KEY_UP);    /* 10->12 (working) */
    hmi_key(&h, HMI_KEY_ESC);                            /* cancel */
    CHECK(!h.editing && holding_regs[HR_CHARGE_CURR]==10, "U16 edit cancel discards");

    /* U16 clamp at min */
    hmi_key(&h, HMI_KEY_ENTER);
    for (int i=0;i<20;i++) hmi_key(&h, HMI_KEY_DOWN);    /* below 0 -> clamp */
    hmi_key(&h, HMI_KEY_ENTER);
    CHECK(holding_regs[HR_CHARGE_CURR]==0, "U16 clamp at min");

    /* SUBMENU push/pop */
    hmi_init(&h, &hmi_root_menu, &io);
    for (int i=0;i<12;i++) hmi_key(&h, HMI_KEY_DOWN);    /* Parallel Setting (idx 12) */
    hmi_key(&h, HMI_KEY_ENTER);
    CHECK(h.depth==1, "enter submenu");
    hmi_key(&h, HMI_KEY_ESC);
    CHECK(h.depth==0, "esc leaves submenu");

    /* ACTION */
    hmi_init(&h, &hmi_root_menu, &io);
    for (int i=0;i<14;i++) hmi_key(&h, HMI_KEY_DOWN);    /* Restore Defaults (idx 14) */
    g_restore = 0;
    hmi_key(&h, HMI_KEY_ENTER);
    CHECK(g_restore==1, "action fires callback");

    printf("%s: %d/%d checks passed\n", g_fail?"FAILED":"OK", g_run-g_fail, g_run);
    return g_fail ? 1 : 0;
}
