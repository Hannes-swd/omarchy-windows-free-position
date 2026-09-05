#!/usr/bin/env python3
"""
reset_zoom.py
Restaura manualmente al tamano original la ventana que el Infinite Desktop
haya agrandado (ver navigate_windows.py), por si el estado se desincroniza.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import hyprctl_json, resize_window_exact, move_window_exact

ZOOM_STATE_FILE = "/tmp/infinite-desktop-zoom-state.json"


def main():
    try:
        with open(ZOOM_STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        return

    clients = hyprctl_json(["clients"]) or []
    window = next((w for w in clients if w["address"] == state["addr"]), None)
    if window:
        cx = window["at"][0] + window["size"][0] // 2
        cy = window["at"][1] + window["size"][1] // 2
        w, h = state["orig_w"], state["orig_h"]
        resize_window_exact(w, h, state["addr"])
        move_window_exact(cx - w // 2, cy - h // 2, state["addr"])

    try:
        os.remove(ZOOM_STATE_FILE)
    except Exception:
        pass


if __name__ == "__main__":
    main()
