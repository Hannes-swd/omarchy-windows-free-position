#!/usr/bin/env python3
"""
navigate_windows.py
Navega entre ventanas del workspace activo usando Super+flechas.

- Flotante: mueve todas las ventanas para centrar la objetivo (infinite canvas)
- Tileado master: movefocus l/r/u/d
- Tileado dwindle: movefocus left/right/up/down

Uso: python3 navigate_windows.py <left|right|up|down>
"""

import subprocess
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import (hyprctl_json, move_focus, focus_window, move_window_exact_lua,
                       batch_async, resize_window_exact, move_window_exact)

DIR_SHORT = {"left": "l", "right": "r", "up": "u", "down": "d"}

# Que fraccion de la pantalla debe ocupar la ventana enfocada tras el "zoom"
# (que en realidad es un resize real de la ventana, no zoom de pantalla, para
# no afectar la barra/fondo/menus).
FILL_RATIO = 0.65
MIN_ZOOM = 1.0
MAX_ZOOM = 2.2

ZOOM_STATE_FILE = "/tmp/infinite-desktop-zoom-state.json"


def load_zoom_state():
    try:
        with open(ZOOM_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def save_zoom_state(addr, w, h):
    try:
        with open(ZOOM_STATE_FILE, "w") as f:
            json.dump({"addr": addr, "orig_w": w, "orig_h": h}, f)
    except Exception:
        pass


def resize_window_centered(addr, new_w, new_h, at, size):
    cx = at[0] + size[0] // 2
    cy = at[1] + size[1] // 2
    resize_window_exact(new_w, new_h, addr)
    move_window_exact(cx - new_w // 2, cy - new_h // 2, addr)


def movefocus(direction):
    # La wiki documenta el selector de direccion de hl.dsp.focus como l/r/u/d
    # sin importar el layout.
    move_focus(DIR_SHORT[direction])


def get_focused_monitor():
    """Ojo: hyprctl monitors reporta el ancho/alto en pixeles fisicos del modo
    de video, pero las posiciones/tamanos de ventana (hyprctl clients) estan
    en coordenadas LOGICAS (= pixeles fisicos / scale). Hay que dividir por
    scale aca o todo el centrado sale desplazado en monitores con escalado
    fraccional (p.ej. 1.25, 1.5)."""
    monitors = hyprctl_json(["monitors"]) or []
    for m in monitors:
        if m.get("focused"):
            scale = m.get("scale") or 1
            return {"x": m["x"], "y": m["y"], "width": int(m["width"] / scale), "height": int(m["height"] / scale)}
    return {"x": 0, "y": 0, "width": 1920, "height": 1080}


def get_monitor_center():
    m = get_focused_monitor()
    return m["x"] + m["width"] // 2, m["y"] + m["height"] // 2


def zoom_for_window_size(window_w, window_h, monitor_w, monitor_h):
    """Zoom tal que la ventana ocupe ~FILL_RATIO de la pantalla en ambos ejes,
    sin recortarla en ninguno de los dos (se usa el eje mas restrictivo)."""
    if window_w <= 0 or window_h <= 0:
        return MIN_ZOOM
    zoom_x = (monitor_w * FILL_RATIO) / window_w
    zoom_y = (monitor_h * FILL_RATIO) / window_h
    return max(MIN_ZOOM, min(MAX_ZOOM, min(zoom_x, zoom_y)))


def get_window_bounds(w):
    x, y = w["at"][0], w["at"][1]
    ww, wh = w["size"][0], w["size"][1]
    return {"left": x, "right": x+ww, "top": y, "bottom": y+wh,
            "center_x": x+ww//2, "center_y": y+wh//2}


def overlap_h(b1, b2):
    return not (b1["right"] <= b2["left"] or b1["left"] >= b2["right"])


def overlap_v(b1, b2):
    return not (b1["bottom"] <= b2["top"] or b1["top"] >= b2["bottom"])


def find_target(floating, current_bounds, center, direction):
    cx, cy = center

    aligned = []
    for w in floating:
        b = get_window_bounds(w)
        wx, wy = b["center_x"], b["center_y"]
        if direction == "left"  and overlap_v(current_bounds, b) and wx < cx:
            aligned.append((w, cx - wx))
        elif direction == "right" and overlap_v(current_bounds, b) and wx > cx:
            aligned.append((w, wx - cx))
        elif direction == "up"   and overlap_h(current_bounds, b) and wy < cy:
            aligned.append((w, cy - wy))
        elif direction == "down" and overlap_h(current_bounds, b) and wy > cy:
            aligned.append((w, wy - cy))

    if aligned:
        return sorted(aligned, key=lambda x: x[1])[0][0]

    same_dir = []
    for w in floating:
        b = get_window_bounds(w)
        wx, wy = b["center_x"], b["center_y"]
        if direction == "left"  and wx < cx: same_dir.append((w, cx - wx))
        elif direction == "right" and wx > cx: same_dir.append((w, wx - cx))
        elif direction == "up"   and wy < cy: same_dir.append((w, cy - wy))
        elif direction == "down" and wy > cy: same_dir.append((w, wy - cy))

    if same_dir:
        return sorted(same_dir, key=lambda x: x[1])[0][0]

    opp = {"left":"right","right":"left","up":"down","down":"up"}[direction]
    wrap = []
    for w in floating:
        b = get_window_bounds(w)
        wx, wy = b["center_x"], b["center_y"]
        if opp == "left"  and wx < cx: wrap.append((w, cx - wx))
        elif opp == "right" and wx > cx: wrap.append((w, wx - cx))
        elif opp == "up"   and wy < cy: wrap.append((w, cy - wy))
        elif opp == "down" and wy > cy: wrap.append((w, wy - cy))

    if wrap:
        return sorted(wrap, key=lambda x: x[1])[0][0]

    return None


def pan_to_window(floating, target_addr, center_x, center_y, monitor_w, monitor_h):
    """Desplaza TODAS las ventanas flotantes para que la ventana objetivo quede
    centrada en pantalla, le da el foco, y agranda (resize real, no zoom de
    pantalla) la ventana objetivo segun su tamano original. La ventana que
    estaba agrandada antes vuelve a su tamano original."""
    target = next((w for w in floating if w["address"] == target_addr), None)
    if not target:
        return

    orig_w, orig_h = target["size"][0], target["size"][1]

    tx = target["at"][0] + orig_w // 2
    ty = target["at"][1] + orig_h // 2
    dx = center_x - tx
    dy = center_y - ty

    exprs = []
    for w in floating:
        if w["address"] == target_addr:
            continue  # se reposiciona junto con el resize mas abajo, para evitar carrera
        nx = w["at"][0] + dx
        ny = w["at"][1] + dy
        exprs.append(move_window_exact_lua(int(nx), int(ny), w["address"]))
    batch_async(exprs)
    focus_window(target_addr)

    # Restaurar el tamano de la ventana que estaba agrandada antes (si sigue existiendo).
    prev = load_zoom_state()
    if prev and prev["addr"] != target_addr:
        prev_window = next((w for w in floating if w["address"] == prev["addr"]), None)
        if prev_window:
            # prev_window["at"] es su posicion ANTES del pan de arriba (que ya
            # incluyo su propio movimiento por dx,dy); sumamos el delta para
            # no perder ese desplazamiento al recentrar con el nuevo tamano.
            panned_at = (prev_window["at"][0] + dx, prev_window["at"][1] + dy)
            resize_window_centered(prev["addr"], prev["orig_w"], prev["orig_h"],
                                    panned_at, prev_window["size"])

    zoom = zoom_for_window_size(orig_w, orig_h, monitor_w, monitor_h)
    new_w, new_h = int(orig_w * zoom), int(orig_h * zoom)
    resize_window_centered(target_addr, new_w, new_h, (center_x - orig_w // 2, center_y - orig_h // 2), (orig_w, orig_h))
    save_zoom_state(target_addr, orig_w, orig_h)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("left", "right", "up", "down"):
        print("Uso: navigate_windows.py <left|right|up|down>")
        sys.exit(1)

    direction = sys.argv[1]

    ws = hyprctl_json(["activeworkspace"])
    if not ws:
        sys.exit(1)
    workspace_id = ws["id"]

    clients = hyprctl_json(["clients"]) or []
    ws_clients = [w for w in clients if w.get("workspace", {}).get("id") == workspace_id]
    floating = [w for w in ws_clients if w.get("floating")]

    # ── modo mosaico ──────────────────────────────────────────────────────────
    if not floating:
        movefocus(direction)
        return

    # ── modo flotante ──────────────────────────────────────
    if len(floating) <= 1:
        return

    focused = hyprctl_json(["activewindow"])
    if not focused or not focused.get("address"):
        return

    monitor = get_focused_monitor()
    center_x = monitor["x"] + monitor["width"] // 2
    center_y = monitor["y"] + monitor["height"] // 2
    current_bounds = get_window_bounds(focused)
    target = find_target(floating, current_bounds, (center_x, center_y), direction)
    if target:
        pan_to_window(floating, target["address"], center_x, center_y, monitor["width"], monitor["height"])


if __name__ == "__main__":
    main()
