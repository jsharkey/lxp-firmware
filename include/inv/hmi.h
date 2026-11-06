/*
 * HMI: LCD + keypad menu system — public API.
 *
 * Modelled on the stock firmware, which drives a data-driven menu table (an
 * array of fixed-size item structs with a label pointer and a value binding;
 * see docs/06-hmi.md). This reimplementation keeps that shape: a static menu
 * tree of `hmi_item_t`, a navigation state machine, and hardware-abstracted
 * draw/key interfaces so the navigation logic is unit-testable on a host.
 *
 * Items bind to the same register model the Modbus slave uses: display items
 * read input/holding registers; editable items read+write holding registers
 * (so an edit and a Modbus write hit the same store).
 */
#ifndef INV_HMI_H
#define INV_HMI_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Front-panel keys (ENTER/ESC/UP/DOWN, per the stock "KEY Ageing Test"). */
typedef enum { HMI_KEY_UP, HMI_KEY_DOWN, HMI_KEY_ENTER, HMI_KEY_ESC } hmi_key_t;

/* Register space a value binds to. */
typedef enum { HMI_REG_NONE, HMI_REG_INPUT, HMI_REG_HOLDING } hmi_regspace_t;

/* Item kinds. */
typedef enum {
    HMI_INFO,     /* read-only display of a register (e.g. SN, FW, telemetry) */
    HMI_U16,      /* editable unsigned value with range/step/scale            */
    HMI_ENUM,     /* editable choice from a fixed list                        */
    HMI_SUBMENU,  /* opens a nested menu                                       */
    HMI_ACTION    /* runs a callback (e.g. "Update", a reset command)         */
} hmi_item_kind_t;

struct hmi_menu;

typedef struct hmi_item {
    const char       *label;
    hmi_item_kind_t   kind;
    hmi_regspace_t    space;   /* for INFO/U16/ENUM: which register space      */
    uint16_t          reg;     /* register number (IR_* or HR_*)               */
    int32_t           min, max, step;  /* U16 edit bounds                      */
    uint16_t          scale;   /* display divisor (1, 10, 100…); 0 => treat 1  */
    const char       *unit;    /* e.g. "V", "A", "%"; may be NULL              */
    const char *const *choices;/* ENUM labels, indexed by register value       */
    uint8_t           nchoices;
    const struct hmi_menu *submenu;  /* SUBMENU target                         */
    void             (*action)(void);/* ACTION callback                        */
} hmi_item_t;

typedef struct hmi_menu {
    const char       *title;
    const hmi_item_t *items;
    uint8_t           count;
} hmi_menu_t;

/* Register access + LCD output, provided by the app/port. */
typedef struct {
    /* read a register; return false if unreadable */
    bool (*read)(hmi_regspace_t space, uint16_t reg, uint16_t *out);
    /* write a holding register; return false if rejected */
    bool (*write)(uint16_t reg, uint16_t val);
    /* draw one display row (row 0 = top). `sel` marks the highlighted row. */
    void (*draw_row)(uint8_t row, const char *text, bool sel);
    void (*clear)(void);
    uint8_t rows;             /* visible text rows on the panel               */
} hmi_io_t;

#define HMI_MAX_DEPTH 6

typedef struct {
    const hmi_io_t *io;
    const hmi_menu_t *stack[HMI_MAX_DEPTH];
    uint8_t  sel[HMI_MAX_DEPTH];   /* selected index per level  */
    uint8_t  top[HMI_MAX_DEPTH];   /* scroll offset per level   */
    uint8_t  depth;                /* 0 = root                  */
    bool     editing;
    int32_t  edit_val;             /* working value while editing */
} hmi_t;

void hmi_init(hmi_t *h, const hmi_menu_t *root, const hmi_io_t *io);
void hmi_key(hmi_t *h, hmi_key_t key);   /* advance the state machine */
void hmi_render(hmi_t *h);               /* draw the current view     */

/* Format a value string for an item (exposed for tests). Returns `buf`. */
const char *hmi_format_value(const hmi_item_t *it, uint16_t raw, char *buf, size_t n);

/* The reimplementation's root menu (src/hmi/hmi_model.c). */
extern const hmi_menu_t hmi_root_menu;

/* ---- Front-panel keypad (src/hmi/keypad.c) ----
 * The physical panel's display is the monochrome graphic LCD (src/hmi/lcd_tft.c,
 * docs/28); the menu's on-screen rendering belongs there. The navigation engine
 * above stays hardware-agnostic: it draws through the hmi_io_t callbacks, so a
 * display backend plugs in without touching the engine (a NULL draw_row makes
 * hmi_render a no-op — headless but valid, as when only the keypad is wired). */
void hmi_keypad_init(void);
int  hmi_keypad_poll(void);   /* returns an hmi_key_t, or -1 if no key */

#endif /* INV_HMI_H */
