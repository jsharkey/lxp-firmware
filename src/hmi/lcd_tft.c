/*
 * lcd_tft — driver for the factory HMI graphic LCD (docs/23), for our firmware.
 *
 * Bit-banged 4-wire serial on GPIOB (PB12 SCLK / PB13 SDA / PB14 DC / PB15 /CS),
 * MIPI-DCS, MSB-first. Pixels are 1bpp packed 8-to-a-byte: one RAMWR data byte
 * paints 8 horizontal pixels (bit 7 = leftmost). The controller is addressed in
 * byte-columns across (CASET) and pixel rows down (RASET). This matches the
 * factory image byte-for-byte at the wire, so tools/tft.py renders our output
 * exactly as it renders the factory's.
 */
#include "stm32f103.h"
#include "inv/lcd_tft.h"
#include <string.h>

#define PIN_SCLK (1u << 12)   /* PB12 */
#define PIN_SDA  (1u << 13)   /* PB13 */
#define PIN_DC   (1u << 14)   /* PB14 */
#define PIN_CS   (1u << 15)   /* PB15 */

static volatile uint32_t s_sink;
static void dly(uint32_t n) { while (n--) s_sink++; }

/* Shift one byte out MSB-first; the panel samples SDA on the SCLK rising edge
 * (same order the factory sub_080114d2 uses). DC selects command vs data; CS is
 * held low throughout, so byte boundaries are defined by the clock count. */
static void shift(uint8_t dc, uint8_t b)
{
    if (dc) GPIOB->BSRR = PIN_DC; else GPIOB->BRR = PIN_DC;
    GPIOB->BRR = PIN_CS;                 /* keep /CS asserted */
    for (int i = 0; i < 8; i++) {
        GPIOB->BRR = PIN_SCLK;           /* clock low                */
        if (b & 0x80) GPIOB->BSRR = PIN_SDA; else GPIOB->BRR = PIN_SDA;
        GPIOB->BSRR = PIN_SCLK;          /* clock high -> sampled     */
        b = (uint8_t)(b << 1);
    }
}

void lcd_cmd(uint8_t c)  { shift(0, c); }
void lcd_data(uint8_t d) { shift(1, d); }

void lcd_window(uint8_t x0, uint8_t x1, uint8_t y0, uint8_t y1)
{
    lcd_cmd(0x2A);                        /* CASET (byte-columns)      */
    lcd_data(0); lcd_data(x0); lcd_data(0); lcd_data(x1);
    lcd_cmd(0x2B);                        /* RASET (pixel rows)        */
    lcd_data(0); lcd_data(y0); lcd_data(0); lcd_data(y1);
    lcd_cmd(0x2C);                        /* RAMWR                     */
}

void lcd_fill(uint8_t x0, uint8_t x1, uint8_t y0, uint8_t y1, uint8_t b)
{
    lcd_window(x0, x1, y0, y1);
    uint32_t n = (uint32_t)(x1 - x0 + 1) * (uint32_t)(y1 - y0 + 1);
    while (n--) lcd_data(b);
}

void lcd_clear(void) { lcd_fill(0, LCD_COLS - 1, 0, LCD_ROWS - 1, 0x00); }

void lcd_tft_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;
    /* PB12..PB15 = output push-pull 50 MHz (CRH nibbles 4..7). */
    GPIOB->CRH = (GPIOB->CRH & 0x0000FFFFu) | 0x33330000u;
    GPIOB->BSRR = PIN_SCLK | PIN_SDA;     /* idle clock/data high      */
    GPIOB->BRR  = PIN_CS;                 /* assert /CS                */

    /* Init sequence mirrors the factory bring-up (docs/23); the exact command
     * set is what the real panel needs. tools/tft.py ignores all but
     * CASET/RASET/RAMWR, so this is faithful on hardware and harmless in sim. */
    lcd_cmd(0x01); dly(2000);             /* software reset            */
    lcd_cmd(0xD7); lcd_data(0x9F);
    lcd_cmd(0x11); dly(2000);             /* sleep out                 */
    lcd_cmd(0x28);                        /* display off               */
    lcd_cmd(0xC0); lcd_data(0x18); lcd_data(0x01);
    lcd_cmd(0xC3); lcd_data(0x02);
    lcd_cmd(0xC4); lcd_data(0x05);
    lcd_cmd(0xD0); lcd_data(0x1D);
    lcd_cmd(0x39);
    lcd_cmd(0x3A); lcd_data(0x02);        /* COLMOD (1bpp-packed mode)  */
    lcd_cmd(0x36); lcd_data(0x00);        /* MADCTL (no swap/mirror)    */
    lcd_cmd(0xB0); lcd_data(0x9F);
    lcd_cmd(0xB1); lcd_data(0x00);
    lcd_cmd(0x20);                        /* inversion off             */
    lcd_clear();
    lcd_cmd(0x29);                        /* display on                */
}

/* ---- 8x8 font (bit 7 = leftmost pixel), enough for "Hello World!" ---- */
static const uint8_t FONT_BLANK[8] = {0, 0, 0, 0, 0, 0, 0, 0};
static const uint8_t FONT_EXCL[8]  = {0x18,0x18,0x18,0x18,0x18,0x00,0x18,0x00};
static const uint8_t FONT_H[8]     = {0x42,0x42,0x42,0x7E,0x42,0x42,0x42,0x00};
static const uint8_t FONT_W[8]     = {0x42,0x42,0x42,0x42,0x5A,0x66,0x42,0x00};
static const uint8_t FONT_d[8]     = {0x02,0x02,0x3E,0x42,0x42,0x46,0x3A,0x00};
static const uint8_t FONT_e[8]     = {0x00,0x00,0x3C,0x42,0x7E,0x40,0x3C,0x00};
static const uint8_t FONT_l[8]     = {0x18,0x08,0x08,0x08,0x08,0x08,0x1C,0x00};
static const uint8_t FONT_o[8]     = {0x00,0x00,0x3C,0x42,0x42,0x42,0x3C,0x00};
static const uint8_t FONT_r[8]     = {0x00,0x00,0x5C,0x62,0x40,0x40,0x40,0x00};

static const uint8_t *glyph(char ch)
{
    switch (ch) {
    case '!': return FONT_EXCL;
    case 'H': return FONT_H;
    case 'W': return FONT_W;
    case 'd': return FONT_d;
    case 'e': return FONT_e;
    case 'l': return FONT_l;
    case 'o': return FONT_o;
    case 'r': return FONT_r;
    default:  return FONT_BLANK;          /* space + unsupported chars  */
    }
}

void lcd_putc(uint8_t col, uint8_t row, char ch)
{
    const uint8_t *g = glyph(ch);
    lcd_window(col, col, row, (uint8_t)(row + 7));   /* one 8px column, 8 rows */
    for (int r = 0; r < 8; r++) lcd_data(g[r]);
}

void lcd_text(uint8_t col, uint8_t row, const char *s)
{
    for (; *s; s++, col++) lcd_putc(col, row, *s);
}
