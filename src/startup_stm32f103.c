/*
 * Startup + vector table for STM32F103 high-density (60 external IRQs).
 * Mirrors the original image's layout: vector table at 0x08000000, Reset copies
 * .data, zeroes .bss, calls SystemInit, then main(). Handlers are weak so real
 * ones can override them.
 */
#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
extern int  main(void);
extern void SystemInit(void);

void Reset_Handler(void);
void Default_Handler(void);

#define WEAK_ALIAS __attribute__((weak, alias("Default_Handler")))

/* Cortex-M system exceptions */
void NMI_Handler(void)        WEAK_ALIAS;
void HardFault_Handler(void)  WEAK_ALIAS;
void MemManage_Handler(void)  WEAK_ALIAS;
void BusFault_Handler(void)   WEAK_ALIAS;
void UsageFault_Handler(void) WEAK_ALIAS;
void SVC_Handler(void)        WEAK_ALIAS;
void DebugMon_Handler(void)   WEAK_ALIAS;
void PendSV_Handler(void)     WEAK_ALIAS;
void SysTick_Handler(void)    WEAK_ALIAS;

/* STM32F103 high-density external interrupts (IRQ0..59) */
void WWDG_IRQHandler(void)            WEAK_ALIAS;
void PVD_IRQHandler(void)             WEAK_ALIAS;
void TAMPER_IRQHandler(void)          WEAK_ALIAS;
void RTC_IRQHandler(void)             WEAK_ALIAS;
void FLASH_IRQHandler(void)           WEAK_ALIAS;
void RCC_IRQHandler(void)             WEAK_ALIAS;
void EXTI0_IRQHandler(void)           WEAK_ALIAS;
void EXTI1_IRQHandler(void)           WEAK_ALIAS;
void EXTI2_IRQHandler(void)           WEAK_ALIAS;
void EXTI3_IRQHandler(void)           WEAK_ALIAS;
void EXTI4_IRQHandler(void)           WEAK_ALIAS;
void DMA1_Channel1_IRQHandler(void)   WEAK_ALIAS;
void DMA1_Channel2_IRQHandler(void)   WEAK_ALIAS;
void DMA1_Channel3_IRQHandler(void)   WEAK_ALIAS;
void DMA1_Channel4_IRQHandler(void)   WEAK_ALIAS;
void DMA1_Channel5_IRQHandler(void)   WEAK_ALIAS;
void DMA1_Channel6_IRQHandler(void)   WEAK_ALIAS;
void DMA1_Channel7_IRQHandler(void)   WEAK_ALIAS;
void ADC1_2_IRQHandler(void)          WEAK_ALIAS;
void USB_HP_CAN1_TX_IRQHandler(void)  WEAK_ALIAS;
void USB_LP_CAN1_RX0_IRQHandler(void) WEAK_ALIAS;
void CAN1_RX1_IRQHandler(void)        WEAK_ALIAS;
void CAN1_SCE_IRQHandler(void)        WEAK_ALIAS;
void EXTI9_5_IRQHandler(void)         WEAK_ALIAS;
void TIM1_BRK_IRQHandler(void)        WEAK_ALIAS;
void TIM1_UP_IRQHandler(void)         WEAK_ALIAS;
void TIM1_TRG_COM_IRQHandler(void)    WEAK_ALIAS;
void TIM1_CC_IRQHandler(void)         WEAK_ALIAS;
void TIM2_IRQHandler(void)            WEAK_ALIAS;
void TIM3_IRQHandler(void)            WEAK_ALIAS;
void TIM4_IRQHandler(void)            WEAK_ALIAS;
void I2C1_EV_IRQHandler(void)         WEAK_ALIAS;
void I2C1_ER_IRQHandler(void)         WEAK_ALIAS;
void I2C2_EV_IRQHandler(void)         WEAK_ALIAS;
void I2C2_ER_IRQHandler(void)         WEAK_ALIAS;
void SPI1_IRQHandler(void)            WEAK_ALIAS;
void SPI2_IRQHandler(void)            WEAK_ALIAS;
void USART1_IRQHandler(void)          WEAK_ALIAS;
void USART2_IRQHandler(void)          WEAK_ALIAS;
void USART3_IRQHandler(void)          WEAK_ALIAS;
void EXTI15_10_IRQHandler(void)       WEAK_ALIAS;
void RTCAlarm_IRQHandler(void)        WEAK_ALIAS;
void USBWakeUp_IRQHandler(void)       WEAK_ALIAS;
void TIM8_BRK_IRQHandler(void)        WEAK_ALIAS;
void TIM8_UP_IRQHandler(void)         WEAK_ALIAS;
void TIM8_TRG_COM_IRQHandler(void)    WEAK_ALIAS;
void TIM8_CC_IRQHandler(void)         WEAK_ALIAS;
void ADC3_IRQHandler(void)            WEAK_ALIAS;
void FSMC_IRQHandler(void)            WEAK_ALIAS;
void SDIO_IRQHandler(void)            WEAK_ALIAS;
void TIM5_IRQHandler(void)            WEAK_ALIAS;
void SPI3_IRQHandler(void)            WEAK_ALIAS;
void UART4_IRQHandler(void)           WEAK_ALIAS;
void UART5_IRQHandler(void)           WEAK_ALIAS;
void TIM6_IRQHandler(void)            WEAK_ALIAS;
void TIM7_IRQHandler(void)            WEAK_ALIAS;
void DMA2_Channel1_IRQHandler(void)   WEAK_ALIAS;
void DMA2_Channel2_IRQHandler(void)   WEAK_ALIAS;
void DMA2_Channel3_IRQHandler(void)   WEAK_ALIAS;
void DMA2_Channel4_5_IRQHandler(void) WEAK_ALIAS;

typedef void (*vector_t)(void);

__attribute__((section(".isr_vector"), used))
const vector_t g_vectors[] = {
    (vector_t)&_estack,
    Reset_Handler, NMI_Handler, HardFault_Handler, MemManage_Handler,
    BusFault_Handler, UsageFault_Handler, 0, 0, 0, 0,
    SVC_Handler, DebugMon_Handler, 0, PendSV_Handler, SysTick_Handler,
    /* external */
    WWDG_IRQHandler, PVD_IRQHandler, TAMPER_IRQHandler, RTC_IRQHandler,
    FLASH_IRQHandler, RCC_IRQHandler, EXTI0_IRQHandler, EXTI1_IRQHandler,
    EXTI2_IRQHandler, EXTI3_IRQHandler, EXTI4_IRQHandler,
    DMA1_Channel1_IRQHandler, DMA1_Channel2_IRQHandler, DMA1_Channel3_IRQHandler,
    DMA1_Channel4_IRQHandler, DMA1_Channel5_IRQHandler, DMA1_Channel6_IRQHandler,
    DMA1_Channel7_IRQHandler, ADC1_2_IRQHandler, USB_HP_CAN1_TX_IRQHandler,
    USB_LP_CAN1_RX0_IRQHandler, CAN1_RX1_IRQHandler, CAN1_SCE_IRQHandler,
    EXTI9_5_IRQHandler, TIM1_BRK_IRQHandler, TIM1_UP_IRQHandler,
    TIM1_TRG_COM_IRQHandler, TIM1_CC_IRQHandler, TIM2_IRQHandler, TIM3_IRQHandler,
    TIM4_IRQHandler, I2C1_EV_IRQHandler, I2C1_ER_IRQHandler, I2C2_EV_IRQHandler,
    I2C2_ER_IRQHandler, SPI1_IRQHandler, SPI2_IRQHandler, USART1_IRQHandler,
    USART2_IRQHandler, USART3_IRQHandler, EXTI15_10_IRQHandler, RTCAlarm_IRQHandler,
    USBWakeUp_IRQHandler, TIM8_BRK_IRQHandler, TIM8_UP_IRQHandler,
    TIM8_TRG_COM_IRQHandler, TIM8_CC_IRQHandler, ADC3_IRQHandler, FSMC_IRQHandler,
    SDIO_IRQHandler, TIM5_IRQHandler, SPI3_IRQHandler, UART4_IRQHandler,
    UART5_IRQHandler, TIM6_IRQHandler, TIM7_IRQHandler, DMA2_Channel1_IRQHandler,
    DMA2_Channel2_IRQHandler, DMA2_Channel3_IRQHandler, DMA2_Channel4_5_IRQHandler,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;      /* copy .data from flash */
    for (dst = &_sbss; dst < &_ebss;) *dst++ = 0; /* zero .bss */

    SystemInit();
    main();
    for (;;) { }                                 /* main should not return */
}

void Default_Handler(void) { for (;;) { } }
