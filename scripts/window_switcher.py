#!/usr/bin/env python3
"""
window_switcher.py
Reutiliza el selector de imagenes propio de Omarchy (omarchy-menu-images /
omarchy-shell image-selector) - la MISMA interfaz que el selector de fondos
de pantalla - para elegir entre las ventanas abiertas en el workspace activo,
mostrando una captura EN VIVO de cada una (no un icono generico).

Cada ventana se captura COMPLETA y aislada: si no entra donde esta ahora
dentro del monitor, se mueve a una esquina que si le entre; cualquier OTRA
ventana flotante que tape esa zona se aparca temporalmente bien lejos
mientras tanto (enfocar no alcanza para traerla al frente de forma
confiable). Todo se devuelve exactamente a donde estaba apenas se toma la
captura, ventana por ventana.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import hyprctl_json, move_window_exact
from navigate_windows import pan_to_window, get_focused_monitor

THUMB_SIZE = "440x300"
MOVE_SETTLE = 0.4      # segundos a esperar tras reposicionar antes de capturar
PARKING_OFFSET = 20000  # bien fuera de cualquier monitor real

# Cache de capturas: una ventana que ya se capturo alguna vez reusa esa misma
# imagen siempre, sin importar si se movio, cambio de tamano o su contenido
# es distinto ahora - solo una ventana NUEVA (que nunca se capturo) toma una
# captura fresca. Mucho mas rapido que recapturar todo cada vez; el precio es
# que las miniaturas se quedan desactualizadas hasta que la ventana se cierre
# (su cache se borra) y se vuelva a abrir.
CACHE_DIR = os.path.expanduser("~/.cache/omarchy-windows-free-position/window-switcher")


def cache_path(addr):
    return os.path.join(CACHE_DIR, f"{addr.replace('0x', '')}.png")


def cached_capture(win):
    """Devuelve la ruta a la imagen cacheada si esta ventana ya se capturo
    antes (sin importar si se movio/redimensiono/cambio de contenido)."""
    img_path = cache_path(win["address"])
    return img_path if os.path.isfile(img_path) else None


def save_to_cache(win, img_path):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        shutil.copyfile(img_path, cache_path(win["address"]))
    except Exception:
        pass


def prune_cache(open_addresses):
    """Borra entradas de ventanas que ya no estan abiertas, para que el cache
    no crezca sin limite con el tiempo."""
    try:
        open_safe = {a.replace("0x", "") for a in open_addresses}
        for fname in os.listdir(CACHE_DIR):
            stem = fname.rsplit(".", 1)[0]
            if stem not in open_safe:
                try:
                    os.remove(os.path.join(CACHE_DIR, fname))
                except OSError:
                    pass
    except FileNotFoundError:
        pass


def sanitize(name, limit=60):
    name = re.sub(r"[^\w\- ]", "", name).strip()
    return (name or "window")[:limit]


def fits_within(ax, ay, aw, ah, bx, by, bw, bh):
    return ax >= bx and ay >= by and ax + aw <= bx + bw and ay + ah <= by + bh


def rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    return not (ax + aw <= bx or ax >= bx + bw or ay + ah <= by or ay >= by + bh)


def grim_capture(x, y, w, h, out_path):
    try:
        r = subprocess.run(["grim", "-g", f"{x},{y} {w}x{h}", out_path], capture_output=True, timeout=2)
        return r.returncode == 0 and os.path.isfile(out_path)
    except Exception:
        return False


def capture_window(win, monitor, siblings, out_path):
    """Captura la ventana COMPLETA y aislada de cualquier otra que la tape."""
    x, y = win["at"][0], win["at"][1]
    w, h = win["size"][0], win["size"][1]
    addr = win["address"]

    anchor_x, anchor_y = x, y
    needs_move = not fits_within(x, y, w, h, monitor["x"], monitor["y"], monitor["width"], monitor["height"])
    if needs_move:
        anchor_x, anchor_y = monitor["x"], monitor["y"]

    # Aparcar lejos cualquier OTRA ventana flotante que tape la zona donde se
    # va a capturar (enfocar no garantiza traer la ventana objetivo al frente).
    parked = []
    for s in siblings:
        if not s.get("floating") or s["address"] == addr:
            continue
        sx, sy = s["at"][0], s["at"][1]
        sw, sh = s["size"][0], s["size"][1]
        if rects_overlap(anchor_x, anchor_y, w, h, sx, sy, sw, sh):
            move_window_exact(sx + PARKING_OFFSET, sy + PARKING_OFFSET, s["address"])
            parked.append((s["address"], sx, sy))

    if needs_move:
        move_window_exact(anchor_x, anchor_y, addr)

    if needs_move or parked:
        time.sleep(MOVE_SETTLE)

    ok = grim_capture(anchor_x, anchor_y, w, h, out_path)

    if needs_move:
        move_window_exact(x, y, addr)
    for addr_p, ox, oy in parked:
        move_window_exact(ox, oy, addr_p)

    return ok


def make_placeholder(text, out_path):
    subprocess.run(
        ["convert", "-size", THUMB_SIZE, "xc:#242424",
         "-gravity", "center", "-fill", "white", "-pointsize", "24",
         "-annotate", "0", text[:24], out_path],
        capture_output=True,
    )


def main():
    active = hyprctl_json(["activeworkspace"])
    if not active:
        return
    workspace_id = active["id"]

    clients = hyprctl_json(["clients"]) or []
    windows = [w for w in clients if w.get("workspace", {}).get("id") == workspace_id]
    if not windows:
        subprocess.run(["omarchy-notification-send", "Window switcher", "No windows open on this workspace"])
        return

    monitor = get_focused_monitor()
    prune_cache([w["address"] for w in windows])

    tmp_dir = tempfile.mkdtemp(prefix="window-switcher-")
    mapping = {}
    try:
        for w in windows:
            cls = w.get("class") or "window"
            title = w.get("title") or cls
            label = sanitize(f"{title}" if title.lower() != cls.lower() else cls)
            img_path = os.path.join(tmp_dir, f"{label}.png")
            n = 2
            while img_path in mapping:
                img_path = os.path.join(tmp_dir, f"{label} ({n}).png")
                n += 1

            cached = cached_capture(w)
            if cached:
                shutil.copyfile(cached, img_path)
            elif capture_window(w, monitor, windows, img_path):
                save_to_cache(w, img_path)
            else:
                make_placeholder(title, img_path)

            mapping[img_path] = w

        result = subprocess.run(
            ["omarchy-menu-images", "--show-labels", "--filterable", tmp_dir],
            capture_output=True, text=True,
        )
        selected = result.stdout.strip()
        if not selected or selected not in mapping:
            return

        target = mapping[selected]
        addr = target["address"]

        if target.get("floating"):
            floating = [w for w in windows if w.get("floating")]
            center_x = monitor["x"] + monitor["width"] // 2
            center_y = monitor["y"] + monitor["height"] // 2
            pan_to_window(floating, addr, center_x, center_y, monitor["width"], monitor["height"])
        else:
            subprocess.run(
                ["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{addr}" }})'],
                capture_output=True,
            )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
