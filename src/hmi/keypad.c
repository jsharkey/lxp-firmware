/*
 * Front-panel keypad: the four keys, read from GPIO (STM32F103).
 *
 * Reads the four front-panel keys (PA8/PA11/PC8/PC9, active-low) with a debounce
 * that mirrors the factory's key read (sub_08016af0): a key reports once per
 * fresh press (release-then-press re-arms it). See include/inv/keypad.h for the
 * pin map.
 *
 * The front-panel display is the monochrome graphic LCD (src/hmi/lcd_tft.c),
 * not a character LCD — an earlier 20×4 HD44780/PCF8574 I²C stand-in display was
 * removed once the real panel was decoded (docs/28). This file is keypad-only;
 * the navigation engine (src/hmi/hmi.c) is hardware-agnostic and unaffected.
 */
#include "stm32f103.h"
#include "inv/hmi.h"
#include "inv/keypad.h"

/* ---- keypad: 4 keys on PA8 / PA11 / PC8 / PC9, active-low, debounced ---- */
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
