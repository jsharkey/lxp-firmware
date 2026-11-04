/*
 * Clock / system init for STM32F103, modelled on the original image's
 * SystemInit (which we disassembled at 0x0800231c: it enables HSION, clears
 * RCC->CFGR, disables HSE/CSS/PLL, writes RCC->CIR, calls SetSysClock, then
 * sets SCB->VTOR = 0x08000000).
 *
 * Target: 72 MHz SYSCLK from an 8 MHz HSE crystal (PLL x9). AHB=72, APB1=36,
 * APB2=72. VERIFY the HSE value and PLL multiplier against the schematic — the
 * USART baud (e.g. the DSP link) depends on these being exact.
 */
#include "stm32f103.h"
#include "inv/variant.h"

uint32_t SystemCoreClock = 72000000UL;

void SystemInit(void)
{
    /* 1. Make sure HSI is on and selected (safe starting point) */
    RCC->CR |= RCC_CR_HSION;
    RCC->CFGR = 0;
    RCC->CR &= ~(RCC_CR_HSEON | RCC_CR_PLLON);

    /* 2. Flash: prefetch on, 2 wait states (required for 48 < SYSCLK <= 72) */
    FLASH->ACR = FLASH_ACR_PRFTBE | FLASH_ACR_LATENCY_2;

    /* 3. Start HSE */
    RCC->CR |= RCC_CR_HSEON;
    while (!(RCC->CR & RCC_CR_HSERDY)) { }

    /* 4. Bus prescalers: AHB/1, APB1/2, APB2/1 */
    RCC->CFGR |= RCC_CFGR_HPRE_DIV1 | RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV1;

    /* 5. PLL = HSE * 9 = 72 MHz */
    RCC->CFGR |= RCC_CFGR_PLLSRC_HSE | RCC_CFGR_PLLMULL9;
    RCC->CR   |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY)) { }

    /* 6. Switch SYSCLK to PLL */
    RCC->CFGR |= RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS_PLL) != RCC_CFGR_SWS_PLL) { }

    /* 7. Vector table base. On a monolithic image (12000XP) this is the flash
     * base; on an App-over-bootloader image (18kPV) the App's vectors are
     * relocated (0x0800C800), so take it from the active variant descriptor
     * rather than hard-coding FLASH_BASE_ADDR. */
    SCB->VTOR = inv_variant()->vector_addr;
}
