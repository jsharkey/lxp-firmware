/*
 * lcd_tft — the factory HMI's graphic LCD, as a driver for our firmware.
 *
 * This targets the SAME panel the factory image drives (docs/23), so our
 * firmware is a drop-in on the real hardware:
 *   - bit-banged 4-wire serial on GPIOB: PB12 SCLK, PB13 SDA, PB14 DC, PB15 /CS,
 *   - MIPI-DCS command set (CASET / RASET / RAMWR), MSB-first,
 *   - 1 bit per pixel, 8 pixels packed per byte; addressed in byte-columns
 *     across (CASET) and pixel rows down (RASET).
 *
 * The visible panel is 240x160: byte-columns LCD_PANEL_X0..127 (columns left of
 * that are an off-panel margin). A text cell is 8x8: one byte-column wide
 * (= 8 px) and 8 rows tall.
 */
#ifndef INV_LCD_TFT_H
#define INV_LCD_TFT_H

#include <stdint.h>

#define LCD_COLS      128     /* byte-columns in the controller GRAM            */
#define LCD_ROWS      160     /* pixel rows                                      */
#define LCD_PANEL_X0  48      /* first visible byte-column (panel left edge)     */

void lcd_tft_init(void);

/* Low-level (exposed for tests / custom drawing). */
void lcd_cmd(uint8_t c);
void lcd_data(uint8_t d);
void lcd_window(uint8_t x0, uint8_t x1, uint8_t y0, uint8_t y1); /* x in bytes, y in rows */

/* Fill a byte-column x row rectangle with one packed byte (0x00 clears). */
void lcd_fill(uint8_t x0, uint8_t x1, uint8_t y0, uint8_t y1, uint8_t b);
void lcd_clear(void);                       /* clear the whole GRAM to 0        */

/* Draw an 8x8 glyph string. `col` is a byte-column, `row` a pixel row; each
 * character advances one byte-column (8 px). */
void lcd_putc(uint8_t col, uint8_t row, char ch);
void lcd_text(uint8_t col, uint8_t row, const char *s);

#endif /* INV_LCD_TFT_H */
