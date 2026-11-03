/*
 * HMI port: LCD + keypad hardware glue (STM32F103).
 *
 * The stock HMI has an LCD and a 4-key pad (ESC/UP/DOWN/ENTER, per the
 * "KEY Ageing Test" strings). The exact LCD controller and the key/LCD GPIO
 * mapping come from the schematic — SPI1 is a candidate for the panel. These
 * are skeletons that keep the build linking; fill them per the board.
 */
#include "stm32f103.h"
#include "inv/hmi.h"

void hmi_lcd_init(void)
{
    /* TODO(schematic): init the LCD controller (likely over SPI1) + backlight. */
}

void hmi_lcd_clear(void)
{
    /* TODO: clear framebuffer / display RAM. */
}

void hmi_lcd_draw_row(uint8_t row, const char *text, bool sel)
{
    /* TODO: render `text` at the given text row; invert if `sel`.
     * The navigation engine already composed the full "label+value" line. */
    (void)row; (void)text; (void)sel;
}

void hmi_keypad_init(void)
{
    /* TODO(schematic): configure the 4 key GPIOs as inputs with pull-ups. */
}

/*
 * Return an hmi_key_t on a fresh key press, else -1. Replace with a real
 * debounced GPIO scan once the key pins are known.
 */
int hmi_keypad_poll(void)
{
    return -1;
}
