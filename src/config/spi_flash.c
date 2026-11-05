/*
 * SPI NOR flash driver (SPI1 + PA4 CS) -- see inv/spi_flash.h.
 *
 * Matches the factory wiring (docs/21): SPI1 master, PA4 as a GPIO chip-select
 * held low for the duration of each command. Commands are the usual SPI NOR
 * set: 0x03 read, 0x02 page program, 0x20 4 KB sector erase, 0x06 WREN,
 * 0x05 RDSR (poll WIP).
 */
#include "stm32f103.h"
#include "inv/spi_flash.h"

#define CMD_WREN  0x06u
#define CMD_RDSR  0x05u
#define CMD_READ  0x03u
#define CMD_PP    0x02u
#define CMD_SE    0x20u
#define CMD_JEDEC 0x9Fu
#define SR_WIP    0x01u

#define CS_PIN    (1u << 4)                 /* PA4 */
#define CS_LOW()  (GPIOA->BRR  = CS_PIN)    /* assert   (active low) */
#define CS_HIGH() (GPIOA->BSRR = CS_PIN)    /* deassert */

static uint8_t xfer(uint8_t b)
{
    while (!(SPI1->SR & SPI_SR_TXE)) { }
    SPI1->DR = b;
    while (!(SPI1->SR & SPI_SR_RXNE)) { }
    return (uint8_t)SPI1->DR;
}

static void send_cmd_addr(uint8_t cmd, uint32_t addr)
{
    xfer(cmd);
    xfer((uint8_t)(addr >> 16));
    xfer((uint8_t)(addr >> 8));
    xfer((uint8_t)addr);
}

static void wren(void)
{
    CS_LOW();
    xfer(CMD_WREN);
    CS_HIGH();
}

static void wait_wip(void)
{
    CS_LOW();
    xfer(CMD_RDSR);
    while (xfer(0xFF) & SR_WIP) { }         /* sim reports WIP=0, so this returns at once */
    CS_HIGH();
}

void spi_flash_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_SPI1EN;
    /* PA4 = output push-pull 50 MHz (CS); PA5 = AF PP (SCK); PA6 = input floating
     * (MISO); PA7 = AF PP (MOSI). Low nibble-per-pin in CRL, bits [31:16]. */
    GPIOA->CRL = (GPIOA->CRL & ~0xFFFF0000u) | 0xB4B30000u;
    CS_HIGH();
    SPI1->CR1 = SPI_CR1_MSTR | SPI_CR1_SSM | SPI_CR1_SSI | SPI_CR1_BR_DIV8;
    SPI1->CR1 |= SPI_CR1_SPE;
}

uint32_t spi_flash_jedec(void)
{
    CS_LOW();
    xfer(CMD_JEDEC);
    uint32_t mfr = xfer(0xFF), typ = xfer(0xFF), cap = xfer(0xFF);
    CS_HIGH();
    return (mfr << 16) | (typ << 8) | cap;
}

void spi_flash_read(uint32_t addr, uint8_t *buf, size_t n)
{
    CS_LOW();
    send_cmd_addr(CMD_READ, addr);
    for (size_t i = 0; i < n; i++) buf[i] = xfer(0xFF);
    CS_HIGH();
}

void spi_flash_page_program(uint32_t addr, const uint8_t *buf, size_t n)
{
    wren();
    CS_LOW();
    send_cmd_addr(CMD_PP, addr);
    for (size_t i = 0; i < n; i++) xfer(buf[i]);
    CS_HIGH();
    wait_wip();
}

void spi_flash_sector_erase(uint32_t addr)
{
    wren();
    CS_LOW();
    send_cmd_addr(CMD_SE, addr);
    CS_HIGH();
    wait_wip();
}
