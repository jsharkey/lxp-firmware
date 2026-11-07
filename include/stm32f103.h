/*
 * Minimal STM32F103xE register definitions — hand-written, dependency-free.
 *
 * Just enough to boot, set up the 72 MHz clock, drive GPIO and a USART. This
 * keeps the skeleton self-contained; contributors may later swap in full CMSIS
 * (ST device pack) or libopencm3 without changing the application layer.
 *
 * Device assumption (refine from the schematic): STM32F103VET6-class part,
 * 512 KB flash @ 0x08000000, 64 KB SRAM @ 0x20000000, 8 MHz HSE crystal.
 */
#ifndef STM32F103_H
#define STM32F103_H

#include <stdint.h>

#define __IO volatile

/* ---- memory bases ---- */
#define FLASH_BASE_ADDR   0x08000000UL
#define SRAM_BASE_ADDR    0x20000000UL
#define PERIPH_BASE       0x40000000UL
#define APB1PERIPH_BASE   (PERIPH_BASE)
#define APB2PERIPH_BASE   (PERIPH_BASE + 0x10000UL)
#define AHBPERIPH_BASE    (PERIPH_BASE + 0x20000UL)

/* ---- RCC ---- */
typedef struct {
    __IO uint32_t CR; __IO uint32_t CFGR; __IO uint32_t CIR;
    __IO uint32_t APB2RSTR; __IO uint32_t APB1RSTR; __IO uint32_t AHBENR;
    __IO uint32_t APB2ENR;  __IO uint32_t APB1ENR;  __IO uint32_t BDCR;
    __IO uint32_t CSR;
} RCC_TypeDef;
#define RCC   ((RCC_TypeDef *)(AHBPERIPH_BASE + 0x1000UL))   /* 0x40021000 */

#define RCC_CR_HSION      (1UL << 0)
#define RCC_CR_HSEON      (1UL << 16)
#define RCC_CR_HSERDY     (1UL << 17)
#define RCC_CR_PLLON      (1UL << 24)
#define RCC_CR_PLLRDY     (1UL << 25)
#define RCC_CFGR_SW_PLL   (2UL << 0)
#define RCC_CFGR_SWS_PLL  (2UL << 2)
#define RCC_CFGR_HPRE_DIV1   (0UL << 4)
#define RCC_CFGR_PPRE1_DIV2  (4UL << 8)
#define RCC_CFGR_PPRE2_DIV1  (0UL << 11)
#define RCC_CFGR_PLLSRC_HSE  (1UL << 16)
#define RCC_CFGR_PLLMULL9    (7UL << 18)   /* x9 */
#define RCC_APB2ENR_AFIOEN   (1UL << 0)
#define RCC_APB2ENR_IOPAEN   (1UL << 2)
#define RCC_APB2ENR_IOPBEN   (1UL << 3)
#define RCC_APB2ENR_IOPCEN   (1UL << 4)
#define RCC_APB2ENR_IOPDEN   (1UL << 5)
#define RCC_APB2ENR_IOPEEN   (1UL << 6)
#define RCC_APB2ENR_SPI1EN   (1UL << 12)
#define RCC_APB2ENR_USART1EN (1UL << 14)
#define RCC_APB1ENR_USART2EN (1UL << 17)
#define RCC_APB1ENR_USART3EN (1UL << 18)
#define RCC_APB1ENR_UART5EN  (1UL << 20)

/* ---- FLASH access control ---- */
typedef struct { __IO uint32_t ACR; } FLASH_TypeDef;
#define FLASH ((FLASH_TypeDef *)(AHBPERIPH_BASE + 0x2000UL))  /* 0x40022000 */
#define FLASH_ACR_LATENCY_2  (2UL << 0)
#define FLASH_ACR_PRFTBE     (1UL << 4)

/* ---- GPIO ---- */
typedef struct {
    __IO uint32_t CRL; __IO uint32_t CRH; __IO uint32_t IDR;
    __IO uint32_t ODR; __IO uint32_t BSRR; __IO uint32_t BRR; __IO uint32_t LCKR;
} GPIO_TypeDef;
#define GPIOA ((GPIO_TypeDef *)(APB2PERIPH_BASE + 0x0800UL))  /* 0x40010800 */
#define GPIOB ((GPIO_TypeDef *)(APB2PERIPH_BASE + 0x0C00UL))
#define GPIOC ((GPIO_TypeDef *)(APB2PERIPH_BASE + 0x1000UL))
#define GPIOD ((GPIO_TypeDef *)(APB2PERIPH_BASE + 0x1400UL))
#define GPIOE ((GPIO_TypeDef *)(APB2PERIPH_BASE + 0x1800UL))

/* ---- USART ---- */
typedef struct {
    __IO uint32_t SR; __IO uint32_t DR; __IO uint32_t BRR;
    __IO uint32_t CR1; __IO uint32_t CR2; __IO uint32_t CR3; __IO uint32_t GTPR;
} USART_TypeDef;
#define USART1 ((USART_TypeDef *)(APB2PERIPH_BASE + 0x3800UL)) /* 0x40013800 */
#define USART2 ((USART_TypeDef *)(APB1PERIPH_BASE + 0x4400UL)) /* 0x40004400 */
#define USART3 ((USART_TypeDef *)(APB1PERIPH_BASE + 0x4800UL)) /* 0x40004800 */
#define UART5  ((USART_TypeDef *)(APB1PERIPH_BASE + 0x5000UL)) /* 0x40005000 */
#define UART5  ((USART_TypeDef *)(APB1PERIPH_BASE + 0x5000UL)) /* 0x40005000 */
#define USART_SR_TXE  (1UL << 7)
#define USART_SR_TC   (1UL << 6)
#define USART_SR_RXNE (1UL << 5)
#define USART_CR1_UE     (1UL << 13)
#define USART_CR1_TXEIE  (1UL << 7)
#define USART_CR1_TCIE   (1UL << 6)
#define USART_CR1_RXNEIE (1UL << 5)
#define USART_CR1_TE  (1UL << 3)
#define USART_CR1_RE  (1UL << 2)

/* ---- SPI (SPI1 drives the external config/settings NOR flash, docs/21) ---- */
typedef struct {
    __IO uint32_t CR1; __IO uint32_t CR2; __IO uint32_t SR; __IO uint32_t DR;
    __IO uint32_t CRCPR; __IO uint32_t RXCRCR; __IO uint32_t TXCRCR;
    __IO uint32_t I2SCFGR; __IO uint32_t I2SPR;
} SPI_TypeDef;
#define SPI1 ((SPI_TypeDef *)(APB2PERIPH_BASE + 0x3000UL))   /* 0x40013000 */
#define SPI_SR_RXNE     (1UL << 0)
#define SPI_SR_TXE      (1UL << 1)
#define SPI_SR_BSY      (1UL << 7)
#define SPI_CR1_CPHA    (1UL << 0)
#define SPI_CR1_CPOL    (1UL << 1)
#define SPI_CR1_MSTR    (1UL << 2)
#define SPI_CR1_BR_DIV8 (2UL << 3)   /* fPCLK/8 */
#define SPI_CR1_SPE     (1UL << 6)
#define SPI_CR1_SSI     (1UL << 8)
#define SPI_CR1_SSM     (1UL << 9)

/* ---- AFIO (alternate-function remap) ---- */
typedef struct {
    __IO uint32_t EVCR; __IO uint32_t MAPR; __IO uint32_t EXTICR[4]; __IO uint32_t MAPR2;
} AFIO_TypeDef;
#define AFIO ((AFIO_TypeDef *)(APB2PERIPH_BASE + 0x0000UL))   /* 0x40010000 */
#define AFIO_MAPR_CAN_REMAP      (3UL << 13)
/* SWJ_CFG (bits 24-26): 010 = JTAG-DP off, SW-DP on -> frees PA15/PB3/PB4 */
#define AFIO_MAPR_SWJ_NOJTAG     (2UL << 24)
#define AFIO_MAPR_CAN_REMAP_PB89 (2UL << 13)   /* CAN1: RX=PB8, TX=PB9 (docs/16) */

/* ---- bxCAN (CAN1) ---- */
typedef struct { __IO uint32_t TIR, TDTR, TDLR, TDHR; } CAN_TxMailBox_TypeDef;
typedef struct { __IO uint32_t RIR, RDTR, RDLR, RDHR; } CAN_FIFOMailBox_TypeDef;
typedef struct { __IO uint32_t FR1, FR2; } CAN_FilterRegister_TypeDef;
typedef struct {
    __IO uint32_t MCR, MSR, TSR, RF0R, RF1R, IER, ESR, BTR;
    uint32_t RESERVED0[88];
    CAN_TxMailBox_TypeDef   sTxMailBox[3];
    CAN_FIFOMailBox_TypeDef sFIFOMailBox[2];
    uint32_t RESERVED1[12];
    __IO uint32_t FMR, FM1R;
    uint32_t RESERVED2;
    __IO uint32_t FS1R;
    uint32_t RESERVED3;
    __IO uint32_t FFA1R;
    uint32_t RESERVED4;
    __IO uint32_t FA1R;
    uint32_t RESERVED5[8];
    CAN_FilterRegister_TypeDef sFilterRegister[14];
} CAN_TypeDef;
#define CAN1 ((CAN_TypeDef *)(APB1PERIPH_BASE + 0x6400UL))    /* 0x40006400 */
#define RCC_APB1ENR_CAN1EN  (1UL << 25)
#define CAN_MCR_INRQ        (1UL << 0)
#define CAN_MCR_SLEEP       (1UL << 1)
#define CAN_MSR_INAK        (1UL << 0)
#define CAN_MSR_SLAK        (1UL << 1)
#define CAN_TSR_TME0        (1UL << 26)
#define CAN_RF0R_FMP0       (3UL << 0)         /* messages pending count */
#define CAN_RF0R_RFOM0      (1UL << 5)         /* release FIFO 0 output mailbox */
#define CAN_RIR_TXRQ        (1UL << 0)         /* (TIR) transmit request        */
#define CAN_RIR_RTR         (1UL << 1)
#define CAN_RIR_IDE         (1UL << 2)
#define CAN_FMR_FINIT       (1UL << 0)
#define CAN_IER_FMPIE0      (1UL << 1)         /* FIFO0 message-pending interrupt */

/* ---- external IRQ numbers (STM32F103 high-density) ---- */
#define USB_LP_CAN1_RX0_IRQn  20
#define USART2_IRQn           38
#define USART3_IRQn           39
#define UART5_IRQn            53

/* ---- Cortex-M3 core: SysTick, SCB, NVIC ---- */
typedef struct {
    __IO uint32_t CTRL; __IO uint32_t LOAD; __IO uint32_t VAL; __IO uint32_t CALIB;
} SysTick_TypeDef;
#define SysTick ((SysTick_TypeDef *)0xE000E010UL)
#define SysTick_CTRL_ENABLE    (1UL << 0)
#define SysTick_CTRL_TICKINT   (1UL << 1)
#define SysTick_CTRL_CLKSOURCE (1UL << 2)

typedef struct {
    __IO uint32_t CPUID; __IO uint32_t ICSR; __IO uint32_t VTOR;
    /* ... (truncated; only VTOR needed here) */
} SCB_TypeDef;
#define SCB ((SCB_TypeDef *)0xE000ED00UL)

#define NVIC_ISER ((__IO uint32_t *)0xE000E100UL)
static inline void nvic_enable_irq(int irqn) { NVIC_ISER[irqn >> 5] = (1UL << (irqn & 0x1F)); }

extern uint32_t SystemCoreClock;
void SystemInit(void);

#endif /* STM32F103_H */
