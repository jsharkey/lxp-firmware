/*
 * HMI panel wiring — the LCD + keypad the reimplementation drives.
 *
 * The *factory* panel is a SPI1 controller (docs/16) whose exact protocol is
 * not yet reverse-engineered. Byte-matching the stock HMI is an explicit
 * non-goal (README "Strategy"), so for a buildable, observable, bring-up-grade
 * panel this firmware drives a **ubiquitous hobby display**: a 20x4 HD44780
 * character LCD behind a PCF8574 I2C backpack ("LCM1602"-style), bit-banged on
 * two GPIOs. That makes the HMI:
 *   - real, running firmware output (the menu engine -> I2C -> a char matrix),
 *   - trivially modelled by the emulator (tools/panel.py decodes the exact same
 *     I2C + PCF8574 + HD44780 contract defined here into a text framebuffer),
 *   - and a faithful match for the on-screen app (tools/hmi_app.py): 4 buttons
 *     drive the real key GPIOs, the firmware renders, the LCD updates.
 *
 * The constants below are the single source of truth shared by the firmware
 * (src/hmi/hmi_port.c) and the simulator model (tools/panel.py). Change them in
 * one place and both ends stay in agreement.
 *
 * On real hardware the schematic will dictate different pins / controller; swap
 * this header and hmi_port.c then. The menu engine (src/hmi/hmi.c) and model are
 * hardware-agnostic and unaffected.
 */
#ifndef INV_HMI_PANEL_H
#define INV_HMI_PANEL_H

/* ---- Geometry: 20 columns x 4 rows character LCD ---- */
#define HMI_LCD_COLS   20
#define HMI_LCD_ROWS   4

/* ---- I2C (bit-banged) bus pins, on GPIOE ---- */
#define HMI_I2C_PORT   GPIOE
#define HMI_I2C_SCL    0      /* PE0 = SCL */
#define HMI_I2C_SDA    1      /* PE1 = SDA */

/* ---- PCF8574 I2C backpack ---- */
#define HMI_PCF8574_ADDR  0x27          /* 7-bit address (common default)      */
/* PCF8574 P0..P7 -> HD44780 control/data (the standard "LiquidCrystal_I2C"
 * backpack wiring). High data nibble P4..P7 carries one HD44780 nibble. */
#define HMI_BP_RS   0x01   /* P0 -> HD44780 RS (0 = command, 1 = data)         */
#define HMI_BP_RW   0x02   /* P1 -> HD44780 R/W (held 0 = write)               */
#define HMI_BP_EN   0x04   /* P2 -> HD44780 E  (latches on the falling edge)   */
#define HMI_BP_BL   0x08   /* P3 -> backlight (held on)                        */

/* HD44780 DDRAM base address of each of the 4 rows (20x4 layout). */
#define HMI_DDRAM_ROW0  0x00
#define HMI_DDRAM_ROW1  0x40
#define HMI_DDRAM_ROW2  0x14
#define HMI_DDRAM_ROW3  0x54

/* ---- Front-panel keys (the factory key pins, docs/16) ----
 * PA8, PA11, PC8, PC9 = IN-PU, read by the factory's debounced sub_08016af0.
 * Mapped UP / DOWN / ENTER / ESC (the "KEY Ageing Test" four-key pad). Active
 * low (a pressed key pulls the pin to ground against its pull-up). */
#define HMI_KEY_UP_PORT     GPIOA
#define HMI_KEY_UP_PIN      8      /* PA8  */
#define HMI_KEY_DOWN_PORT   GPIOA
#define HMI_KEY_DOWN_PIN    11     /* PA11 */
#define HMI_KEY_ENTER_PORT  GPIOC
#define HMI_KEY_ENTER_PIN   8      /* PC8  */
#define HMI_KEY_ESC_PORT    GPIOC
#define HMI_KEY_ESC_PIN     9      /* PC9  */

#endif /* INV_HMI_PANEL_H */
