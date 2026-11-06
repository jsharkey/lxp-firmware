/*
 * HMI navigation engine (hardware-agnostic). See include/inv/hmi.h.
 * Mirrors the stock firmware's data-driven menu: move with UP/DOWN, ENTER opens
 * a submenu / enters value edit / runs an action, ESC goes back / cancels edit.
 */
#include "inv/hmi.h"
#include <stdio.h>
#include <string.h>

static uint16_t item_scale(const hmi_item_t *it) { return it->scale ? it->scale : 1; }

const char *hmi_format_value(const hmi_item_t *it, uint16_t raw, char *buf, size_t n)
{
    if (it->kind == HMI_ENUM) {
        if (it->choices && raw < it->nchoices) { snprintf(buf, n, "%s", it->choices[raw]); return buf; }
        snprintf(buf, n, "%u", raw); return buf;
    }
    uint16_t s = item_scale(it);
    if (s == 1) {
        snprintf(buf, n, "%u%s", raw, it->unit ? it->unit : "");
    } else {
        unsigned dec = (s >= 1000) ? 3 : (s >= 100) ? 2 : 1;
        snprintf(buf, n, "%u.%0*u%s", raw / s, dec, raw % s, it->unit ? it->unit : "");
    }
    return buf;
}

static const hmi_menu_t *cur(const hmi_t *h) { return h->stack[h->depth]; }
static uint8_t *psel(hmi_t *h) { return &h->sel[h->depth]; }
static uint8_t *ptop(hmi_t *h) { return &h->top[h->depth]; }

void hmi_init(hmi_t *h, const hmi_menu_t *root, const hmi_io_t *io)
{
    memset(h, 0, sizeof *h);
    h->io = io;
    h->stack[0] = root;
}

static void clamp_scroll(hmi_t *h)
{
    uint8_t rows = h->io->rows ? h->io->rows : 4;
    uint8_t sel = *psel(h), top = *ptop(h);
    if (sel < top) top = sel;
    else if (sel >= top + rows) top = (uint8_t)(sel - rows + 1);
    *ptop(h) = top;
}

static bool read_val(const hmi_t *h, const hmi_item_t *it, uint16_t *v)
{
    return it->space != HMI_REG_NONE && h->io->read && h->io->read(it->space, it->reg, v);
}

void hmi_key(hmi_t *h, hmi_key_t key)
{
    const hmi_menu_t *m = cur(h);
    if (m->count == 0) return;
    const hmi_item_t *it = &m->items[*psel(h)];

    if (h->editing) {
        switch (key) {
        case HMI_KEY_UP:
            h->edit_val += it->step ? it->step : 1;
            if (h->edit_val > it->max) h->edit_val = it->max;
            break;
        case HMI_KEY_DOWN:
            h->edit_val -= it->step ? it->step : 1;
            if (h->edit_val < it->min) h->edit_val = it->min;
            break;
        case HMI_KEY_ENTER:
            if (h->io->write) h->io->write(it->reg, (uint16_t)h->edit_val);
            h->editing = false;
            break;
        case HMI_KEY_ESC:
            h->editing = false;      /* cancel, discard edit_val */
            break;
        }
        return;
    }

    switch (key) {
    case HMI_KEY_UP:
        if (*psel(h) > 0) (*psel(h))--;
        clamp_scroll(h);
        break;
    case HMI_KEY_DOWN:
        if (*psel(h) + 1 < m->count) (*psel(h))++;
        clamp_scroll(h);
        break;
    case HMI_KEY_ENTER:
        switch (it->kind) {
        case HMI_SUBMENU:
            if (it->submenu && h->depth + 1 < HMI_MAX_DEPTH) {
                h->depth++;
                h->stack[h->depth] = it->submenu;
                h->sel[h->depth] = 0;
                h->top[h->depth] = 0;
            }
            break;
        case HMI_U16:
        case HMI_ENUM: {
            uint16_t v = 0;
            read_val(h, it, &v);
            h->edit_val = v;
            h->editing = true;
            break;
        }
        case HMI_ACTION:
            if (it->action) it->action();
            break;
        case HMI_INFO:
            break;
        }
        break;
    case HMI_KEY_ESC:
        if (h->depth > 0) h->depth--;
        break;
    }
}

void hmi_render(hmi_t *h)
{
    /* No display backend wired (e.g. only the keypad is connected): nothing to
     * draw. The engine still navigates via hmi_key(); a renderer plugs in by
     * supplying draw_row. */
    if (!h->io->draw_row) return;

    const hmi_menu_t *m = cur(h);
    uint8_t rows = h->io->rows ? h->io->rows : 4;
    if (h->io->clear) h->io->clear();

    for (uint8_t r = 0; r < rows; r++) {
        uint8_t idx = (uint8_t)(*ptop(h) + r);
        if (idx >= m->count) { h->io->draw_row(r, "", false); continue; }
        const hmi_item_t *it = &m->items[idx];
        char val[24] = "", line[40];

        if (it->kind == HMI_SUBMENU) {
            snprintf(line, sizeof line, "%s>", it->label);
        } else if (it->kind == HMI_ACTION) {
            snprintf(line, sizeof line, "%s", it->label);
        } else {
            uint16_t v = 0;
            bool editing_this = h->editing && idx == *psel(h);
            uint16_t raw = editing_this ? (uint16_t)h->edit_val : (read_val(h, it, &v) ? v : 0);
            hmi_format_value(it, raw, val, sizeof val);
            if (editing_this)
                snprintf(line, sizeof line, "%s[%s]", it->label, val);
            else
                snprintf(line, sizeof line, "%s%s", it->label, val);
        }
        h->io->draw_row(r, line, idx == *psel(h));
    }
}
