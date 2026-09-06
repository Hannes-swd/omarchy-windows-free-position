#!/usr/bin/env python3
"""
smart_placement.py
Escucha el socket2 de Hyprland y, cada vez que se abre una ventana flotante
nueva, la coloca junto al centro del canvas (el centro de tus ventanas
flotantes ya abiertas, no necesariamente lo que se ve en pantalla ahora
mismo) sin superponerse (con un margen) a ninguna. Despues mueve TODA la
camara (todas las ventanas flotantes de ese workspace) para que la nueva
ventana quede visible en pantalla, en vez de perderse fuera de vista.
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

# Mismos valores que navigate_windows.py: si el tamano ya coincide con esta
# formula, navegar hacia/desde la ventana despues no le cambia el tamano.
FILL_RATIO = 0.65
MIN_ZOOM = 1.0
MAX_ZOOM = 2.2


def zoom_for_window_size(window_w, window_h, monitor_w, monitor_h):
    if window_w <= 0 or window_h <= 0:
        return MIN_ZOOM
    zoom_x = (monitor_w * FILL_RATIO) / window_w
    zoom_y = (monitor_h * FILL_RATIO) / window_h
    return max(MIN_ZOOM, min(MAX_ZOOM, min(zoom_x, zoom_y)))


def hyprctl_json(args, timeout=1):
    try:
        r = subprocess.run(["hyprctl"] + args + ["-j"], capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout) if r.stdout.strip() else None
    except Exception:
        return None


def move_window_lua(x, y, address):
    return f'hl.dsp.window.move({{ window = "address:{address}", x = {int(x)}, y = {int(y)}, relative = false }})'


def move_window_exact(x, y, address, timeout=1):
    try:
        subprocess.run(["hyprctl", "dispatch", move_window_lua(x, y, address)], capture_output=True, timeout=timeout)
    except Exception:
        pass


def resize_window_lua(w, h, address):
    return f'hl.dsp.window.resize({{ window = "address:{address}", x = {int(w)}, y = {int(h)}, relative = false }})'


def move_windows_batch(moves, resizes=(), timeout=2):
    """moves: lista de (x, y, address). resizes: lista de (w, h, address).
    Un solo hyprctl --batch para que la camara (y el resize de la ventana
    nueva) se apliquen de golpe en vez de uno por uno. Resize va primero:
    cambia el tamano anclado en la esquina actual, y el move de despues deja
    la posicion final exacta sin importar como ancle el resize."""
    exprs = [resize_window_lua(w, h, addr) for w, h, addr in resizes]
    exprs += [move_window_lua(x, y, addr) for x, y, addr in moves]
    if not exprs:
        return
    cmd = " ; ".join(f"dispatch {e}" for e in exprs)
    try:
        subprocess.run(["hyprctl", "--batch", cmd], capture_output=True, timeout=timeout)
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


def packing_candidates(width, height, occupied):
    """Una posicion pegada a cada lado de cada ventana ya abierta (con el gap),
    alineada con ese borde. Es donde realmente hay hueco libre junto a algo
    que ya esta ahi, en vez de un patron geometrico ciego."""
    for o in occupied:
        yield o["right"] + GAP, o["top"]
        yield o["right"] + GAP, o["bottom"] - height
        yield o["left"] - width - GAP, o["top"]
        yield o["left"] - width - GAP, o["bottom"] - height
        yield o["left"], o["bottom"] + GAP
        yield o["right"] - width, o["bottom"] + GAP
        yield o["left"], o["top"] - height - GAP
        yield o["right"] - width, o["top"] - height - GAP


def spiral_candidates(cx, cy):
    """Anillos crecientes de 8 direcciones alrededor del centro, como red de
    seguridad si ninguna posicion junto a una ventana existente sirve."""
    for ring in range(1, MAX_RINGS + 1):
        r = ring * STEP
        for angle_deg in (0, 45, 90, 135, 180, 225, 270, 315):
            angle = math.radians(angle_deg)
            yield cx + r * math.cos(angle), cy + r * math.sin(angle)


def canvas_center(width, height, monitor, occupied):
    """El centro que importa es el de TUS ventanas ya abiertas en el canvas
    infinito, no el del recorte de pantalla actual (que puede estar viendo
    cualquier otra parte del canvas tras un pan). Con canvas vacio, el unico
    punto de referencia razonable es el centro del monitor."""
    if not occupied:
        return monitor["left"] + monitor["width"] / 2 - width / 2, monitor["top"] + monitor["height"] / 2 - height / 2

    left = min(o["left"] for o in occupied)
    right = max(o["right"] for o in occupied)
    top = min(o["top"] for o in occupied)
    bottom = max(o["bottom"] for o in occupied)
    return (left + right) / 2 - width / 2, (top + bottom) / 2 - height / 2


def find_position(width, height, monitor, occupied):
    cx, cy = canvas_center(width, height, monitor, occupied)

    def dist_to_center(pos):
        return (pos[0] - cx) ** 2 + (pos[1] - cy) ** 2

    # Sin limite a la pantalla actual a proposito: el punto de referencia es
    # el canvas, no el recorte visible, asi que la posicion elegida puede
    # perfectamente caer fuera de vista si es ahi donde esta el hueco.
    candidates = [(cx, cy)]
    candidates += sorted(packing_candidates(width, height, occupied), key=dist_to_center)
    candidates += list(spiral_candidates(cx, cy))

    best = None
    best_overlap = None

    for x, y in candidates:
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
        occupied.append({
            "address": w["address"],
            "left": x, "top": y, "right": x + ww, "bottom": y + wh,
        })

    native_w, native_h = target["size"][0], target["size"][1]

    # Aplicar ya el mismo zoom que navigate_windows.py usaria al enfocarla,
    # para que ir a otra ventana y volver a esta despues no le cambie el
    # tamano de sorpresa (si ya esta al tamano "de foco", la formula da 1.0).
    zoom = zoom_for_window_size(native_w, native_h, monitor["width"], monitor["height"])
    width, height = native_w * zoom, native_h * zoom

    x, y = find_position(width, height, monitor, occupied)

    # Llevar la camara (= todas las ventanas flotantes de este workspace) a
    # donde quedo la nueva ventana, para que aparezca visible en pantalla en
    # vez de perderse en una parte del canvas fuera de vista.
    view_cx = monitor["left"] + monitor["width"] / 2
    view_cy = monitor["top"] + monitor["height"] / 2
    dx = view_cx - (x + width / 2)
    dy = view_cy - (y + height / 2)

    moves = [(x + dx, y + dy, address)]
    moves += [(o["left"] + dx, o["top"] + dy, o["address"]) for o in occupied]
    resizes = [(width, height, address)] if zoom != 1.0 else []
    move_windows_batch(moves, resizes)


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
