# omarchy-windows-free-position

Turn [Omarchy](https://omarchy.org/)'s Hyprland desktop into an "infinite canvas": pan all your floating windows around freely with the mouse or touchpad, jump between them with a keybind that smoothly centers and enlarges the one you land on, and keep your normal tiling workflow for everything else.

This is an **Omarchy-specific port and rewrite** of [sarodscommits/hyprland-infinite-desktop-v2](https://github.com/sarodscommits/hyprland-infinitie-desktop-v2), rebuilt to actually work with Omarchy's Lua-based Hyprland config (`hl.bind`, `o.bind`, `hl.config`, ...) instead of the classic `hyprland.conf` format. Several real bugs from the original were found and fixed along the way (see [What's different from the original](#whats-different-from-the-original-repo) below).

> **Note:** This project was built largely with AI assistance — [Claude Code](https://claude.com/claude-code) (Anthropic's AI coding assistant) did most of the porting, debugging and writing here, guided and reviewed by a human, and tested on a real Omarchy laptop before publishing.

## Screenshots

**Free positioning** — floating windows placed anywhere, overlapping, not confined to a tiling grid:

![Free positioning](screenshots/free-positioning.png)

**Navigate & auto-focus** — jumping to a window centers the camera on it and grows it to a comfortable size (a real window resize, not a screen zoom — the bar, wallpaper and cursor are never touched):

![Navigate and focus](screenshots/navigate-and-focus.png)

## What it does

- **Super+Alt+drag** (mouse or touchpad) — pan the whole canvas: every floating window moves together, like scrolling around a big desk.
- **Super+click+drag** a window to a screen edge — the other floating windows slide out of its way.
- **Super+Alt+arrow** — focus the next window in that direction. The camera re-centers on it and it grows to fill roughly two-thirds of the screen (small windows zoom in more, large windows barely change) — a real `resize`, so nothing outside that one window is affected.
- **Super+D** — toggle every window on the workspace between floating and tiled.
- **Super+0** — manual escape hatch: snaps the currently-enlarged window back to its original size.
- **Super+M** — toggle new windows back to Omarchy's normal automatic tiling (and back again). Takes effect after your next login/reboot, not instantly — see [note below](#a-note-on-superm).
- New windows open floating by default, so they immediately join the canvas — placed near screen center, spreading out in a spiral instead of stacking exactly on top of each other if the center's already taken.

Everything else (tiled windows, workspaces, the rest of Omarchy) works exactly as before.

## Requirements

- Omarchy (Arch-based, Hyprland with the Lua config — this does *not* work on classic `hyprland.conf` setups)
- `python-evdev`, `jq` (installed by the script)
- Your user needs to be in the `input` group (the installer does this; you must log out/reboot once for it to take effect)

## Install

```bash
git clone https://github.com/Hannes-swd/omarchy-windows-free-position.git
cd omarchy-windows-free-position
./install.sh
```

The installer:
1. Installs `python-evdev` and `jq` via `pacman`
2. Adds your user to the `input` group (needed to read raw mouse/touchpad/keyboard events)
3. Copies the scripts to `~/scripts/`
4. Appends a clearly-marked, backed-up block to `~/.config/hypr/autostart.lua`, `~/.config/hypr/hyprland.lua` and `~/.config/hypr/bindings.lua`

**After installing:** log out and back in (needed for the `input` group), then press **Super+K** to see all the new keybindings listed with descriptions.

The keybindings used were checked against a stock Omarchy install and don't collide with any default bind. If you've heavily customized your own `bindings.lua` already, double-check Super+K afterwards and adjust `~/.config/hypr/bindings.lua` if something collides — Hyprland doesn't reliably warn you about duplicate binds.

### Uninstall

Remove the block marked `>>> omarchy-windows-free-position (auto-installed) START` / `END` from the three config files listed above (or restore the `.bak.<timestamp>` files the installer created next to them), then `rm -rf ~/scripts` if you don't need the scripts anymore, and `sudo gpasswd -d $USER input` if you want to leave the `input` group.

## Keybindings

| Keys | Action |
|---|---|
| `Super+Alt` + drag mouse/touchpad | Pan the whole canvas |
| `Super` + click + drag to screen edge | Push other windows out of the way |
| `Super+Alt+←/→/↑/↓` | Focus + center + auto-resize the neighboring window |
| `Super+Shift+Ctrl+←/→/↑/↓` | Move the focused tiled window |
| `Super+Ctrl+Alt+H/J/K/L` | Move the focused floating window |
| `Super+Shift+Alt+H/J/K/L` | Resize the focused floating window |
| `Super+Z` / `Super+.` | Previous / next workspace |
| `Super+Shift+Z` / `Super+Shift+.` | Move window to previous / next workspace |
| `Super+D` | Toggle floating/tiled for every window on the workspace |
| `Super+0` | Reset the currently-enlarged window back to its original size |
| `Super+M` | Toggle auto-float for *new* windows on/off (applies after next login/reboot) |

### A note on Super+M

Hyprland's Lua window rules are additive and never get cleared on `hyprctl reload` — unlike keybinds, which do reset cleanly. That means flipping this toggle can't take effect immediately; it just flips a flag file (`~/.local/state/omarchy/toggles/infinite-desktop-autofloat-disabled`, using Omarchy's own `omarchy-toggle` flag convention) that's checked once, the next time `hyprland.lua` runs from scratch (login or reboot). The keybind sends a notification saying so instead of pretending it's instant. If you just want your *current* windows tiled again right now, use **Super+D** instead — that one is instant.

## How it works

- `scripts/infinite_desktop_core.py` runs in the background (autostarted), reads raw input events for keyboards, mice **and touchpads** (via `evdev`, auto-detected by device capabilities, no hardcoded device paths), and drives the pan/edge-push behavior directly through `hyprctl`.
- `scripts/navigate_windows.py` picks the next window in a direction, pans the canvas so it's centered, and resizes it based on how much of the screen it should fill.
- `scripts/smart_placement.py` runs in the background too (autostarted), listening on Hyprland's own event socket (`.socket2.sock`) for `openwindow` events. When a new floating window appears, it looks at the bounding box of the other floating windows already on that workspace — that's "the canvas", which can be anywhere after you've panned around, not necessarily the current view — and places the new one right up against one of them (with a small gap), picking whichever free spot is closest to the center of that bounding box. With no other windows open yet, it just falls back to the monitor's center.
- Everything else (`move_window.py`, `move_window_tiled.py`, `resize_window.py`, `floating_tile_toggle.py`, `reset_zoom.py`, `hypr_ipc.py`) are small focused helpers called from the keybindings.

## What's different from the original repo

The original project (a solid idea) targeted vanilla Hyprland and had a few issues that show up specifically on Omarchy:

- **Wrong config format**: it wrote to `hyprland.lua` using raw `hl.bind()` calls without descriptions and its own conflict-checker only scanned that one file — it never saw Omarchy's real default binds (which live in `/usr/share/omarchy/`), so several of its default keys silently collided with existing Omarchy shortcuts (arrow-key window focus, `Super+X`, etc). This port uses Omarchy's own `o.bind(keys, description, ...)` helper (so binds show up correctly under Super+K) and picks keys verified against a real Omarchy install.
- **No touchpad support**: the mouse-pan logic only understood `REL_X/REL_Y` (regular mice). Laptop touchpads report finger position as *absolute* coordinates (`ABS_X/ABS_Y`) through a separate device node — the original code silently never saw touchpad movement at all. This port detects touchpad devices by capability and converts absolute positions to relative deltas.
- **No HiDPI/fractional-scaling awareness**: window centering used the monitor's raw pixel resolution from `hyprctl monitors`, but window positions in Hyprland are in *logical* coordinates (`pixels / scale`). On any monitor with fractional scaling (e.g. 1.25x, 1.5x) windows would center off to one side instead of the true middle of the screen. Fixed by dividing by `scale` everywhere a monitor size is used.
- **Screen zoom instead of window resize**: an earlier version of the "zoom in on focus" feature used Hyprland's `cursor:zoom_factor`, which magnifies the *entire output* — bar, wallpaper, cursor, everything. It now does a real per-window resize instead, so nothing outside the target window is ever touched.
- **A stray "protected apps" list silently blocked focus**: a leftover safeguard from the original camera-pan design (meant to avoid disorienting jumps into browsers) made the navigate keybind quietly refuse to focus Chromium/Firefox/etc. Removed since it no longer applies once the camera-follow logic changed.
- **New windows opened full-screen-sized / browsers stayed tiled**: floating a window with no explicit size makes it inherit the size it would have had while tiled — for the first window on a workspace, that's the whole monitor. And Omarchy's own `browser.lua` force-tiles Chromium/Firefox-based windows, which silently overrode the float rule. Fixed with an explicit default size (`60% 60%`) and an override rule for the browser tags specifically.

## Credits

Based on [sarodscommits/hyprland-infinitie-desktop-v2](https://github.com/sarodscommits/hyprland-infinitie-desktop-v2) — original idea and mouse-pan implementation. This repo is an Omarchy-specific port with the fixes described above.

## License

MIT — see [LICENSE](LICENSE). Based on [sarodscommits/hyprland-infinitie-desktop-v2](https://github.com/sarodscommits/hyprland-infinitie-desktop-v2) (MIT).
