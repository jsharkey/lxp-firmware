/*
 * Front-panel keypad wiring — the four keys the HMI reads.
 *
 * The physical front panel has a four-key pad and a monochrome graphic LCD
 * (the LCD is driven by src/hmi/lcd_tft.c, bit-banged 4-wire on GPIOB — see
 * docs/28 / docs/wiring/ARM-LCD-panel.md). There is **no** character LCD and no I²C
 * display on this hardware; an earlier 20×4 HD44780-over-PCF8574 stand-in was
 * removed once the real graphic panel was decoded.
 *
 * The keys are on the factory key pins (docs/16): PA8, PA11, PC8, PC9, read as
 * IN-PU by the factory's debounced sampler (sub_08016af0) and mapped
 * UP / DOWN / ENTER / ESC (the "KEY Ageing Test" four-key pad). Active low: a
 * pressed key pulls its pin to ground against the pull-up.
 */
#ifndef INV_KEYPAD_H
#define INV_KEYPAD_H

#define HMI_KEY_UP_PORT     GPIOA
#define HMI_KEY_UP_PIN      8      /* PA8  */
#define HMI_KEY_DOWN_PORT   GPIOA
#define HMI_KEY_DOWN_PIN    11     /* PA11 */
#define HMI_KEY_ENTER_PORT  GPIOC
#define HMI_KEY_ENTER_PIN   8      /* PC8  */
#define HMI_KEY_ESC_PORT    GPIOC
#define HMI_KEY_ESC_PIN     9      /* PC9  */

#endif /* INV_KEYPAD_H */
