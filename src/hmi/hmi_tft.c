/*
 * hmi_tft — render the menu engine's rows on the graphic LCD (lcd_tft).
 *
 * Bridges the hardware-agnostic navigation engine (src/hmi/hmi.c) to the
 * monochrome graphic panel (src/hmi/lcd_tft.c): it supplies the hmi_io_t
 * draw_row/clear backend. The engine composes each "label+value" row plus a
 * selected flag; we paint it with the 8x8 font, one menu row per HMI_TFT_ROW_H
 * pixel band, and mark the selection with a '>' cursor in the first cell (the
 * panel is monochrome, so a cursor reads cleaner than inverting a row).
 *
 * Layout: the visible panel is byte-columns LCD_PANEL_X0..LCD_COLS-1 (= 80
 * character cells) by LCD_ROWS pixel rows. HMI_TFT_ROWS rows of HMI_TFT_ROW_H
 * px tile the full height and the 8x8 glyphs are centred in each band. Each row
 * clears its own band before drawing, so the whole visible area is rewritten
 * every render and hmi_tft_clear() is a no-op — no full-screen blank, so no
 * flicker.
 */
#include "inv/hmi.h"
#include "inv/lcd_tft.h"

/* Pixel rows per menu row: tile the panel height into HMI_TFT_ROWS bands. */
#define HMI_TFT_ROW_H   (LCD_ROWS / HMI_TFT_ROWS)

void hmi_tft_clear(void)
{
    /* No-op: each row self-clears its band (see file header), so there is no
     * full-screen blank between renders. lcd_tft_init() cleared the GRAM once. */
}

void hmi_tft_draw_row(uint8_t row, const char *text, bool sel)
{
    if (row >= HMI_TFT_ROWS) return;
    uint8_t y = (uint8_t)(row * HMI_TFT_ROW_H);

    /* Clear this row's band across the full visible width, then draw. */
    lcd_fill(LCD_PANEL_X0, LCD_COLS - 1, y, (uint8_t)(y + HMI_TFT_ROW_H - 1), 0x00);

    uint8_t gy = (uint8_t)(y + (HMI_TFT_ROW_H - 8) / 2);   /* centre the 8px glyph */
    lcd_putc(LCD_PANEL_X0, gy, sel ? '>' : ' ');           /* selection cursor */
    lcd_text((uint8_t)(LCD_PANEL_X0 + 1), gy, text ? text : "");
}
