#!/usr/bin/env python3
"""
smart_placement.py
Escucha el socket2 de Hyprland y, cada vez que se abre una ventana flotante
nueva, la coloca lo mas cerca posible del centro de pantalla sin superponerse
(con un margen) a otras ventanas flotantes ya abiertas en el mismo workspace.
Si el centro esta libre la usa directamente; si no, prueba posiciones en
espiral alrededor del centro hasta encontrar un hueco.
"""

import json
import math
import os
import socket
import subprocess
import sys
import time

GAP = 28          # espacio minimo entre ventanas, para que no se "peguen"/snapeen
STEP = 70          # separacion entre anillos de la espiral
MAX_RINGS = 14     # limite de intentos antes de rendirse y usar el mejor candidato


def hyprctl_json(args, timeout=1):
    try:
        r = subprocess.run(["hyprctl"] + args + ["-j"], capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout) if r.stdout.strip() else None
    except Exception:
        return None


def move_window_exact(x, y, address, timeout=1):
    try:
        subprocess.run(
            ["hyprctl", "dispatch", f'hl.dsp.window.move({{ window = "address:{address}", x = {int(x)}, y = {int(y)}, relative = false }})'],
            capture_output=True, timeout=timeout,
        )
    except Exception:
        pass


def get_socket_path():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return f"{runtime}/hypr/{sig}/.socket2.sock"


def monitor_bounds_for_workspace(workspace_id):
    monitors = hyprctl_json(["monitors"]) or []
    workspaces = hyprctl_json(["workspaces"]) or []
    monitor_id = None
    for w in workspaces:
        if w.get("id") == workspace_id:
            monitor_id = w.get("monitorID")
            break

    for m in monitors:
        if monitor_id is not None and m.get("id") == monitor_id:
            scale = m.get("scale") or 1
            return {
                "left": m["x"], "top": m["y"],
                "width": m["width"] / scale, "height": m["height"] / scale,
            }
    # Fallback: el monitor enfocado
    for m in monitors:
        if m.get("focused"):
            scale = m.get("scale") or 1
            return {
                "left": m["x"], "top": m["y"],
                "width": m["width"] / scale, "height": m["height"] / scale,
            }
    return {"left": 0, "top": 0, "width": 1920, "height": 1080}


def rects_overlap(a, b, gap):
    return not (
        a["right"] + gap <= b["left"] or a["left"] >= b["right"] + gap or
        a["bottom"] + gap <= b["top"] or a["top"] >= b["bottom"] + gap
    )


def overlap_area(a, b):
    ox = max(0, min(a["right"], b["right"]) - max(a["left"], b["left"]))
    oy = max(0, min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]))
    return ox * oy


def spiral_candidates(cx, cy):
    """Centro primero, despues anillos crecientes de 8 direcciones alrededor."""
    yield cx, cy
    for ring in range(1, MAX_RINGS + 1):
        r = ring * STEP
        for angle_deg in (0, 45, 90, 135, 180, 225, 270, 315):
            angle = math.radians(angle_deg)
            yield cx + r * math.cos(angle), cy + r * math.sin(angle)


def find_position(width, height, monitor, occupied):
    cx = monitor["left"] + monitor["width"] / 2 - width / 2
    cy = monitor["top"] + monitor["height"] / 2 - height / 2

    best = None
    best_overlap = None

    for x, y in spiral_candidates(cx, cy):
        # Mantener la ventana mayormente dentro del monitor.
        x = max(monitor["left"] - width * 0.25, min(x, monitor["left"] + monitor["width"] - width * 0.75))
        y = max(monitor["top"] - height * 0.25, min(y, monitor["top"] + monitor["height"] - height * 0.75))

        rect = {"left": x, "top": y, "right": x + width, "bottom": y + height}

        total_overlap = sum(overlap_area(rect, o) for o in occupied)
        if total_overlap == 0:
            return x, y

        if best_overlap is None or total_overlap < best_overlap:
            best, best_overlap = (x, y), total_overlap

    return best if best else (cx, cy)


def place_new_window(address):
    # Pequena espera: el windowrule (float + tamano) recien se aplica al
    # mapear la ventana, y hyprctl clients tarda un instante en reflejarlo.
    time.sleep(0.15)

    clients = hyprctl_json(["clients"]) or []
    target = next((w for w in clients if w.get("address") == address), None)
    if not target or not target.get("floating"):
        return

    workspace_id = target.get("workspace", {}).get("id")
    monitor = monitor_bounds_for_workspace(workspace_id)

    occupied = []
    for w in clients:
        if w.get("address") == address:
            continue
        if not w.get("floating"):
            continue
        if w.get("workspace", {}).get("id") != workspace_id:
            continue
        x, y = w["at"][0], w["at"][1]
        ww, wh = w["size"][0], w["size"][1]
        occupied.append({"left": x, "top": y, "right": x + ww, "bottom": y + wh})

    width, height = target["size"][0], target["size"][1]
    x, y = find_position(width, height, monitor, occupied)
    move_window_exact(x, y, address)


def main():
    path = get_socket_path()
    while True:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
        except Exception:
            time.sleep(1)
            continue

        print("smart_placement activo", flush=True)
        buf = b""
        try:
            while True:
                data = s.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode(errors="ignore")
                    if text.startswith("openwindow>>"):
                        addr = "0x" + text[len("openwindow>>"):].split(",", 1)[0]
                        place_new_window(addr)
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        time.sleep(1)  # Hyprland se reinicio o el socket se cerro: reconectar


if __name__ == "__main__":
    main()
