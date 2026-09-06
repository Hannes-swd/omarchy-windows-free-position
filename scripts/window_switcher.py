#!/usr/bin/env python3
"""
window_switcher.py
Reutiliza el selector de imagenes propio de Omarchy (omarchy-menu-images /
omarchy-shell image-selector) - la MISMA interfaz que el selector de fondos
de pantalla - para elegir entre las ventanas abiertas en el workspace activo,
mostrando una captura EN VIVO de cada una (no un icono generico).

Para las ventanas parcial u totalmente tapadas por otra, se enfocan una por
una brevemente (eso las trae al frente en Hyprland) antes de capturarlas, y
al final se restaura el foco original. Una ventana totalmente fuera de la
pantalla actual (en otra parte del canvas infinito) no tiene nada visible
que capturar - para esa se usa una tarjeta con el titulo en su lugar.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import hyprctl_json
from navigate_windows import pan_to_window, get_focused_monitor

THUMB_SIZE = "440x300"
FOCUS_SETTLE = 0.05  # segundos a esperar tras enfocar antes de capturar


def sanitize(name, limit=60):
    name = re.sub(r"[^\w\- ]", "", name).strip()
    return (name or "window")[:limit]


def intersect(ax, ay, aw, ah, bx, by, bw, bh):
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def capture_window(win, monitor, out_path):
    """Intenta una captura en vivo de la porcion de la ventana que cae dentro
    del monitor actual. None si la ventana no tiene nada visible ahi."""
    x, y = win["at"][0], win["at"][1]
    w, h = win["size"][0], win["size"][1]
    region = intersect(x, y, w, h, monitor["x"], monitor["y"], monitor["width"], monitor["height"])
    if not region:
        return False

    rx, ry, rw, rh = region
    try:
        r = subprocess.run(
            ["grim", "-g", f"{rx},{ry} {rw}x{rh}", out_path],
            capture_output=True, timeout=2,
        )
        return r.returncode == 0 and os.path.isfile(out_path)
    except Exception:
        return False


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
    focused = hyprctl_json(["activewindow"]) or {}
    original_focus = focused.get("address")

    tmp_dir = tempfile.mkdtemp(prefix="window-switcher-")
    mapping = {}
    try:
        for i, w in enumerate(windows):
            cls = w.get("class") or "window"
            title = w.get("title") or cls
            label = sanitize(f"{title}" if title.lower() != cls.lower() else cls)
            img_path = os.path.join(tmp_dir, f"{i:03d} {label}.png")

            # Enfocar trae la ventana al frente en Hyprland, asi la captura no
            # muestra lo que sea que estaba tapandola. Sin efecto visible si
            # ya estaba enfocada/al frente.
            subprocess.run(
                ["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{w["address"]}" }})'],
                capture_output=True,
            )
            time.sleep(FOCUS_SETTLE)

            if not capture_window(w, monitor, img_path):
                make_placeholder(title, img_path)

            mapping[img_path] = w

        if original_focus:
            subprocess.run(
                ["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{original_focus}" }})'],
                capture_output=True,
            )

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
