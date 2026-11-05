/*
 * bxCAN port for CAN1 — the battery BMS bus (docs/16, docs/20). Polled RX (the
 * stock firmware polls CAN1 with no IRQ) plus a non-blocking TX for the periodic
 * keep-alive/request. Hardware glue around the decoder in bms_can.c.
 *
 * CAN1 is remapped to PB8(RX)/PB9(TX): the default PA11/PA12 pins clash with the
 * AC transfer relay on PA12 (docs/16/18), so the battery bus lives on PB8/PB9.
 *
 * NOTE(baud): docs/20 has the pack's bit timing as PENDING (expected 500 kbit/s).
 * The BTR below is a provisional 500 kbit/s @ 36 MHz PCLK1; confirm from the SBT
 * decode. Bus timing does not affect the host/sim harness.
 */
#include "stm32f103.h"
#include "inv/bms_can.h"

/* 500 kbit/s @ 36 MHz PCLK1: BRP=8, TS1=7tq, TS2=1tq, SJW=1tq -> 9 tq/bit, /8.
 * BTR fields hold (value-1): SJW[25:24], TS2[22:20], TS1[19:16], BRP[9:0]. */
#define CAN_BTR_500K  ((0U << 24) | (0U << 20) | (6U << 16) | (8U - 1U))

/* Bound every hardware-ack wait so a sim that does not model the bxCAN init
 * handshake (MSR never changes) still proceeds instead of spinning forever. */
#define CAN_ACK_TIMEOUT  100000U

static void wait_bit(volatile uint32_t *reg, uint32_t mask, int want)
{
    for (uint32_t t = 0; t < CAN_ACK_TIMEOUT; t++) {
        int set = (*reg & mask) ? 1 : 0;
        if (set == want) return;
    }
}

void can_port_init(void)
{
    /* clocks: CAN1 (APB1), GPIOB + AFIO (APB2) */
    RCC->APB1ENR |= RCC_APB1ENR_CAN1EN;
    RCC->APB2ENR |= RCC_APB2ENR_IOPBEN | RCC_APB2ENR_AFIOEN;

    /* remap CAN1 to PB8/PB9, then PB8 = floating input (0x4), PB9 = AF-PP 50MHz (0xB) */
    AFIO->MAPR = (AFIO->MAPR & ~AFIO_MAPR_CAN_REMAP) | AFIO_MAPR_CAN_REMAP_PB89;
    GPIOB->CRH = (GPIOB->CRH & ~0x000000FFU) | 0x000000B4U;

    /* enter init mode */
    CAN1->MCR &= ~CAN_MCR_SLEEP;
    wait_bit(&CAN1->MSR, CAN_MSR_SLAK, 0);
    CAN1->MCR |= CAN_MCR_INRQ;
    wait_bit(&CAN1->MSR, CAN_MSR_INAK, 1);

    CAN1->BTR = CAN_BTR_500K;              /* normal mode, provisional 500k */

    /* one accept-all filter bank -> FIFO 0 (32-bit mask mode, mask = 0) */
    CAN1->FMR  |= CAN_FMR_FINIT;
    CAN1->FA1R &= ~1U;                     /* deactivate filter 0 while configuring */
    CAN1->FS1R |= 1U;                      /* 32-bit scale          */
    CAN1->FM1R &= ~1U;                     /* identifier-mask mode  */
    CAN1->sFilterRegister[0].FR1 = 0;      /* id    = don't care    */
    CAN1->sFilterRegister[0].FR2 = 0;      /* mask  = 0 -> accept all */
    CAN1->FFA1R &= ~1U;                    /* filter 0 -> FIFO 0    */
    CAN1->FA1R  |= 1U;                     /* activate filter 0     */
    CAN1->FMR  &= ~CAN_FMR_FINIT;

    /* leave init -> normal mode */
    CAN1->MCR &= ~CAN_MCR_INRQ;
    wait_bit(&CAN1->MSR, CAN_MSR_INAK, 0);
}

void can_port_poll(void (*on_frame)(uint32_t id, const uint8_t *data, uint8_t dlc))
{
    while (CAN1->RF0R & CAN_RF0R_FMP0) {           /* messages pending in FIFO 0 */
        uint32_t rir  = CAN1->sFIFOMailBox[0].RIR;
        uint32_t rdtr = CAN1->sFIFOMailBox[0].RDTR;
        uint32_t lo   = CAN1->sFIFOMailBox[0].RDLR;
        uint32_t hi   = CAN1->sFIFOMailBox[0].RDHR;
        uint8_t  data[8] = {
            (uint8_t)lo, (uint8_t)(lo >> 8), (uint8_t)(lo >> 16), (uint8_t)(lo >> 24),
            (uint8_t)hi, (uint8_t)(hi >> 8), (uint8_t)(hi >> 16), (uint8_t)(hi >> 24),
        };
        uint32_t id  = (rir & CAN_RIR_IDE) ? (rir >> 3) : (rir >> 21);  /* ext : std */
        uint8_t  dlc = (uint8_t)(rdtr & 0xF);
        if (on_frame) on_frame(id, data, dlc);
        CAN1->RF0R = CAN_RF0R_RFOM0;               /* release the mailbox */
    }
}

void can_port_send(uint32_t std_id, const uint8_t *data, uint8_t dlc)
{
    if (!(CAN1->TSR & CAN_TSR_TME0)) return;       /* no free mailbox -> drop (non-blocking) */
    if (dlc > 8) dlc = 8;
    uint32_t lo = 0, hi = 0;
    for (uint8_t i = 0; i < dlc; i++) {
        if (i < 4) lo |= (uint32_t)data[i] << (8 * i);
        else       hi |= (uint32_t)data[i] << (8 * (i - 4));
    }
    CAN1->sTxMailBox[0].TDTR = dlc;
    CAN1->sTxMailBox[0].TDLR = lo;
    CAN1->sTxMailBox[0].TDHR = hi;
    CAN1->sTxMailBox[0].TIR  = (std_id << 21) | CAN_RIR_TXRQ;   /* standard data frame, request TX */
}
