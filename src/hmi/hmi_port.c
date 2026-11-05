/*
 * HMI port: LCD + keypad hardware glue (STM32F103).
 *
 * Drives a 20x4 HD44780 character LCD over a PCF8574 I2C backpack (bit-banged
 * I2C on two GPIOs), and reads the four front-panel keys from GPIO. See
 * include/inv/hmi_panel.h for the wiring (pins, backpack bit map, row
 * addresses) — that header is the contract the emulator model (tools/panel.py)
 * decodes, so the simulator renders exactly what this code sends.
 *
 * The navigation engine (src/hmi/hmi.c) is hardware-agnostic; it hands us fully
 * composed "label+value" rows and a selected flag. We show the selection with a
 * '>' cursor in column 0 (a char LCD cannot invert a row).
 *
 * NOTE: the *factory* panel is a SPI1 controller (docs/16), not this I2C part.
 * This is a clean, buildable, emulator-observable bring-up panel, not a
 * byte-match of the stock HMI (an explicit non-goal). Swap this file + the
 * panel header when the schematic pins the real controller.
 */
#include "stm32f103.h"
#include "inv/hmi.h"
#include "inv/hmi_panel.h"
#include <string.h>

/* ---- small, nominal bit-bang delay ----
 * Real HD44780/I2C need microsecond-scale delays; the emulator decodes by bit
 * order, not timing, so a short loop keeps emulation fast. Widen for real HW. */
#ifndef HMI_LCD_DELAY_LOOPS
#define HMI_LCD_DELAY_LOOPS 2    /* nominal; recalibrate (or use a timer) for real HW */
#endif
static volatile uint32_t s_delay_sink;
static void lcd_delay(void)
{
    for (volatile int i = 0; i < HMI_LCD_DELAY_LOOPS; i++) s_delay_sink++;
}

/* ---- bit-banged I2C master on PE0 (SCL) / PE1 (SDA) ----
 * Push-pull drive is sufficient: the emulator's PCF8574 model is the only other
 * device on the bus and never drives SDA (we ignore ACK). */
static void scl(int level)
{
    if (level) HMI_I2C_PORT->BSRR = (1u << HMI_I2C_SCL);
    else       HMI_I2C_PORT->BRR  = (1u << HMI_I2C_SCL);
    lcd_delay();
}
static void sda(int level)
{
    if (level) HMI_I2C_PORT->BSRR = (1u << HMI_I2C_SDA);
    else       HMI_I2C_PORT->BRR  = (1u << HMI_I2C_SDA);
    lcd_delay();
}

static void i2c_start(void)
{
    sda(1); scl(1);
    sda(0);          /* SDA high->low while SCL high = START */
    scl(0);
}

static void i2c_stop(void)
{
    sda(0); scl(1);
    sda(1);          /* SDA low->high while SCL high = STOP */
}

static void i2c_write_byte(uint8_t b)
{
    for (int i = 0; i < 8; i++) {        /* MSB first */
        sda((b & 0x80) ? 1 : 0);
        scl(1);                          /* slave samples on the rising edge */
        scl(0);
        b = (uint8_t)(b << 1);
    }
    sda(1);                              /* release SDA for ACK */
    scl(1);                              /* 9th clock (ACK); we don't read it */
    scl(0);
}

/* Write one PCF8574 port value (one I2C transaction). */
static void pcf_write(uint8_t val)
{
    i2c_start();
    i2c_write_byte((uint8_t)(HMI_PCF8574_ADDR << 1)); /* address + write bit (0) */
    i2c_write_byte(val);
    i2c_stop();
}

/* ---- HD44780 in 4-bit mode behind the backpack ----
 * Each HD44780 nibble is latched by an E falling edge: write {nibble,ctrl,E=1}
 * then {nibble,ctrl,E=0}. Backlight is held on throughout. */
static void lcd_nibble(uint8_t nib, uint8_t ctrl)
{
    uint8_t base = (uint8_t)((nib << 4) | ctrl | HMI_BP_BL);
    pcf_write((uint8_t)(base | HMI_BP_EN));   /* E high  */
    pcf_write(base);                          /* E low -> latch */
}

static void lcd_byte(uint8_t value, uint8_t ctrl)
{
    lcd_nibble((uint8_t)(value >> 4), ctrl);  /* high nibble first */
    lcd_nibble((uint8_t)(value & 0x0F), ctrl);
}

static void lcd_cmd(uint8_t c)  { lcd_byte(c, 0); }
static void lcd_data(uint8_t d) { lcd_byte(d, HMI_BP_RS); }

/* DDRAM base address of a text row (20x4 map). */
static uint8_t row_addr(uint8_t row)
{
    switch (row) {
    case 0:  return HMI_DDRAM_ROW0;
    case 1:  return HMI_DDRAM_ROW1;
    case 2:  return HMI_DDRAM_ROW2;
    default: return HMI_DDRAM_ROW3;
    }
}

void hmi_lcd_init(void)
{
    /* PE0/PE1 = push-pull outputs, 2 MHz; idle the bus high (I2C released). */
    RCC->APB2ENR |= RCC_APB2ENR_IOPEEN;
    GPIOE->CRL = (GPIOE->CRL & ~0x000000FFu) | 0x00000022u;  /* PE0,PE1 = out PP 2MHz */
    HMI_I2C_PORT->BSRR = (1u << HMI_I2C_SCL) | (1u << HMI_I2C_SDA);

    /* HD44780 power-on into 4-bit mode. The three 0x3 nibbles + one 0x2 are
     * single-nibble writes (the standard 4-bit bring-up); four nibbles keeps
     * the decoder's nibble pairing aligned for the paired bytes that follow. */
    lcd_nibble(0x3, 0); lcd_nibble(0x3, 0); lcd_nibble(0x3, 0);
    lcd_nibble(0x2, 0);
    lcd_cmd(0x28);   /* function set: 4-bit, 2-line, 5x8 (drives all 4 rows) */
    lcd_cmd(0x0C);   /* display on, cursor off, blink off */
    lcd_cmd(0x06);   /* entry mode: increment, no shift */
    lcd_cmd(0x01);   /* clear */
}

void hmi_lcd_clear(void)
{
    lcd_cmd(0x01);   /* clear display, cursor home */
}

void hmi_lcd_draw_row(uint8_t row, const char *text, bool sel)
{
    if (row >= HMI_LCD_ROWS) return;
    char buf[HMI_LCD_COLS];
    buf[0] = sel ? '>' : ' ';            /* selection cursor in column 0 */
    unsigned n = text ? (unsigned)strlen(text) : 0u;
    for (unsigned c = 1; c < HMI_LCD_COLS; c++)
        buf[c] = (c - 1 < n) ? text[c - 1] : ' ';

    /* The engine clears the panel before each full render, so trailing blanks
     * are already clear — only write through the last non-blank cell. */
    unsigned last = 0;
    for (unsigned c = 0; c < HMI_LCD_COLS; c++)
        if (buf[c] != ' ') last = c + 1;
    if (last == 0) return;

    lcd_cmd((uint8_t)(0x80 | row_addr(row)));   /* set DDRAM to row start */
    for (unsigned c = 0; c < last; c++)
        lcd_data((uint8_t)buf[c]);
}

/* ---- keypad: 4 keys on PA8 / PA11 / PC8 / PC9, active-low, debounced ----
 * Mirrors the factory's debounced key read (sub_08016af0): a key reports once
 * per fresh press (release-then-press re-arms it). */
static uint8_t s_key_stable;    /* debounced pressed-mask, bit per hmi_key_t */
static uint8_t s_key_last;      /* previous raw sample                       */
static uint8_t s_key_cnt;       /* consecutive identical raw samples         */
static uint8_t s_key_reported;  /* keys already reported this press          */

static uint8_t key_raw(void)
{
    uint8_t m = 0;              /* pressed = pin low (active low) */
    if (!(HMI_KEY_UP_PORT->IDR    & (1u << HMI_KEY_UP_PIN)))    m |= (1u << HMI_KEY_UP);
    if (!(HMI_KEY_DOWN_PORT->IDR  & (1u << HMI_KEY_DOWN_PIN)))  m |= (1u << HMI_KEY_DOWN);
    if (!(HMI_KEY_ENTER_PORT->IDR & (1u << HMI_KEY_ENTER_PIN))) m |= (1u << HMI_KEY_ENTER);
    if (!(HMI_KEY_ESC_PORT->IDR   & (1u << HMI_KEY_ESC_PIN)))   m |= (1u << HMI_KEY_ESC);
    return m;
}

void hmi_keypad_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPCEN;
    /* PA8  = input pull-up (CRH nibble 0) */
    GPIOA->CRH = (GPIOA->CRH & ~0x0000000Fu) | 0x00000008u;
    /* PA11 = input pull-up (CRH nibble 3) */
    GPIOA->CRH = (GPIOA->CRH & ~0x0000F000u) | 0x00008000u;
    /* PC8  = input pull-up (CRH nibble 0) */
    GPIOC->CRH = (GPIOC->CRH & ~0x0000000Fu) | 0x00000008u;
    /* PC9  = input pull-up (CRH nibble 1) */
    GPIOC->CRH = (GPIOC->CRH & ~0x000000F0u) | 0x00000080u;
    /* input-pull-up direction bit lives in ODR; set the key pins' pull high */
    GPIOA->BSRR = (1u << HMI_KEY_UP_PIN) | (1u << HMI_KEY_DOWN_PIN);
    GPIOC->BSRR = (1u << HMI_KEY_ENTER_PIN) | (1u << HMI_KEY_ESC_PIN);
    s_key_stable = s_key_last = s_key_cnt = s_key_reported = 0;
}

#define KEY_DEBOUNCE 3     /* identical samples to accept a change */

int hmi_keypad_poll(void)
{
    uint8_t raw = key_raw();
    if (raw == s_key_last) {
        if (s_key_cnt < 255) s_key_cnt++;
    } else {
        s_key_last = raw;
        s_key_cnt = 0;
    }
    if (s_key_cnt == KEY_DEBOUNCE)      /* raw held steady long enough */
        s_key_stable = raw;

    uint8_t fresh = (uint8_t)(s_key_stable & ~s_key_reported);
    s_key_reported = s_key_stable;      /* re-arm only after release */

    if (fresh & (1u << HMI_KEY_UP))    return HMI_KEY_UP;
    if (fresh & (1u << HMI_KEY_DOWN))  return HMI_KEY_DOWN;
    if (fresh & (1u << HMI_KEY_ENTER)) return HMI_KEY_ENTER;
    if (fresh & (1u << HMI_KEY_ESC))   return HMI_KEY_ESC;
    return -1;
}
