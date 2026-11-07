/* Host tests for the ARM->DSP config push (docs/08).  make test */
#include "inv/dsp_link.h"
#include "inv/modbus_map.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

static uint16_t holding[256];
static bool rd(void *c, uint16_t reg, uint16_t *o) {
    (void)c; if (reg >= 256) return false; *o = holding[reg]; return true;
}

static const uint8_t SN[10] = {'E','G','4','1','2','3','4','5','6','7'};

int main(void)
{
    holding[HR_OUTPUT_PRIO_CFG] = 2;        /* AC First */
    holding[HR_SYS_ENABLE]      = 0x00A5;
    holding[HR_FUNC_EN]         = 0x0080;   /* ACChargeEn */
    holding[HR_EOD]             = 20;

    dsp_cfg_src_t src = {0};
    src.address = 1;
    memcpy(src.sn, SN, 10);
    src.year=24; src.month=11; src.day=4; src.hour=13; src.minute=30; src.second=0;
    src.read_holding = rd; src.ctx = 0;

    uint8_t f[DSP_FRAME_MAX];

    /* ---- block 0 frame structure ---- */
    size_t n = dsp_build_config_frame(&src, 0, f, sizeof f);
    CHECK(n > 0, "block0 built");
    CHECK(f[DSP_OFF_ADDR] == 1, "addr");
    CHECK(f[DSP_OFF_TYPE] == DSP_FRAME_TYPE_CONFIG, "type == 1");
    CHECK(memcmp(f + DSP_OFF_HEADER, SN, 10) == 0, "SN in header");
    CHECK(f[DSP_OFF_HEADER + 10] == 24 && f[DSP_OFF_HEADER + 13] == 13, "timestamp in header");
    CHECK(f[DSP_OFF_BLOCKID] == 0, "block id 0");
    CHECK(f[0x1e] == 2, "output priority (AC First=2) at frame 0x1e");
    /* CRC valid (little-endian trailing) */
    uint16_t crc = dsp_crc16(f, n - 2);
    CHECK((f[n-2] | (f[n-1] << 8)) == crc, "block0 CRC valid");

    /* ---- full-snapshot rotation: all blocks, ids 0..N-1, each a valid type-1 frame ---- */
    dsp_push_t p; dsp_push_init(&p);
    int seen[DSP_CONFIG_NBLOCKS] = {0};
    for (int i = 0; i < DSP_CONFIG_NBLOCKS; i++) {
        size_t len = dsp_push_next(&p, &src, f, sizeof f);
        CHECK(len > 0 && f[DSP_OFF_TYPE] == 1, "rotated frame is type 1");
        CHECK(f[DSP_OFF_BLOCKID] == i, "rotation emits blocks in order 0..7");
        uint16_t c = dsp_crc16(f, len - 2);
        CHECK((f[len-2] | (f[len-1] << 8)) == c, "rotated frame CRC valid");
        seen[f[DSP_OFF_BLOCKID]] = 1;
    }
    CHECK(p.next_block == 0, "rotation wraps back to block 0");
    int all = 1; for (int i = 0; i < DSP_CONFIG_NBLOCKS; i++) all &= seen[i];
    CHECK(all, "all blocks emitted in one full snapshot");

    /* a changed setting shows up in the next snapshot (full image, not delta) */
    holding[HR_OUTPUT_PRIO_CFG] = 1;        /* PV First */
    dsp_build_config_frame(&src, 0, f, sizeof f);
    CHECK(f[0x1e] == 1, "new value re-sent in full snapshot");

    /* ---- block 0 HR-driven byte encodings (factory-decoded; T10/T25) ----
     * Each byte's transform is pinned against the factory per-block filler by
     * single-write capture (docs/wiring/ARM-USART3-DSP/block-00-output-priority.md
     * + hr-push-matrix.md). This locks our encoding to those values. */
    memset(holding, 0, sizeof holding);
    holding[HR_SYS_ENABLE]       = 0x00A5;  /* 0x19 = 0xA5 & 0xFE = 0xA4            */
    holding[HR_EPS_VOLT_SET]     = 240;     /* volt sel 3 ...                      */
    holding[HR_EPS_FREQ_SET]     = 60;      /* ... | 0x08 -> 0x1a = 0x0B           */
    holding[HR_FUNCTION_EN1]     = 0x0081;  /* bit0->0x80, bit7->0x10 (bit3 = none) */
    holding[HR_SET_SYSTEM_TYPE]  = 1;       /* bit0 -> 0x08; 0x1c = 0x90|0x08       */
    holding[HR_OUTPUT_PRIO_CFG]  = 2;       /* 0x1e = 2                            */
    holding[HR_PV_INPUT_MODEL]   = 4;       /* 0x28 = 4                            */
    holding[HR_FUNC_EN]          = 0x0002;  /* bit1 -> 0x10; 0x2c = 0x10           */
    dsp_build_config_frame(&src, 0, f, sizeof f);
    CHECK(f[0x19] == 0xA4, "block0 0x19 = SYS_ENABLE & 0xFE");
    CHECK(f[0x1a] == 0x0B, "block0 0x1a = EPS volt-sel(240)=3 | 60Hz 0x08");
    /* 0x1c = FUNCTION_EN1(b0,b7) | systype b0 0x08. The factory's 0x02 "FuncEn-
     * unconfigured" latch clears on the first HR 21 write; we are always configured
     * so we omit it -- byte-exact in the configured state (see the ABS check). */
    CHECK(f[0x1c] == 0x98, "block0 0x1c = FUNCTION_EN1(b0->0x80,b7->0x10) | systype b0 0x08");
    CHECK(f[0x1e] == 0x02, "block0 0x1e = OUTPUT_PRIO_CFG");
    CHECK(f[0x28] == 0x04, "block0 0x28 = PV_INPUT_MODEL");
    CHECK(f[0x2c] == 0x10, "block0 0x2c = FUNC_EN remap (bit1->0x10)");
    /* FUNCTION_EN1 bit3 contributes nothing to 0x1c (the 0x08 is systype's) */
    memset(holding, 0, sizeof holding);
    holding[HR_FUNCTION_EN1] = 0x0008;      /* bit3 only, systype 0 */
    dsp_build_config_frame(&src, 0, f, sizeof f);
    CHECK(f[0x1c] == 0x00, "block0 0x1c: FUNCTION_EN1 bit3 adds nothing");
    /* a register that contributes nothing leaves the byte at zero */
    memset(holding, 0, sizeof holding);
    dsp_build_config_frame(&src, 0, f, sizeof f);
    CHECK(f[0x1c] == 0x00, "block0 0x1c zero when no enable bits set (configured)");
    CHECK(f[0x19] == 0x00 && f[0x2c] == 0x00, "block0 0x19/0x2c zero when regs zero");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
