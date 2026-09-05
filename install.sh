#!/usr/bin/env bash
#
# Installer for omarchy-windows-free-position.
# Designed and tested specifically for Omarchy's Lua-based Hyprland config
# (~/.config/hypr/hyprland.lua, bindings.lua, autostart.lua).
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DEST="${HOME}/scripts"
HYPR_DIR="${HOME}/.config/hypr"

C_RESET="\033[0m"; C_BOLD="\033[1m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"; C_RED="\033[31m"; C_CYAN="\033[36m"

log()  { echo -e "${C_CYAN}==>${C_RESET} $*"; }
ok()   { echo -e "${C_GREEN}[OK]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARNING]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }

MARK_START="-- >>> omarchy-windows-free-position (auto-installed) START"
MARK_END="-- <<< omarchy-windows-free-position (auto-installed) END"

require_cmd() { command -v "$1" >/dev/null 2>&1; }

install_packages() {
    log "Installing python-evdev and jq..."
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="${ID:-unknown}"
    else
        DISTRO_ID="unknown"
    fi

    if [[ "$DISTRO_ID" == "arch" ]]; then
        sudo pacman -S --needed python-evdev jq
    else
        warn "This installer targets Omarchy (Arch-based). Install manually: python-evdev, jq"
    fi
    ok "Packages installed (or already present)."
}

setup_input_group() {
    log "Adding your user (${USER}) to the 'input' group..."
    if groups "$USER" | grep -qw input; then
        ok "Already a member of the 'input' group."
    else
        sudo usermod -aG input "$USER"
        warn "Added to the 'input' group. You must LOG OUT (or reboot) for this to take effect."
        NEED_RELOGIN=1
    fi
}

install_scripts() {
    log "Copying scripts to ${SCRIPTS_DEST}..."
    mkdir -p "${SCRIPTS_DEST}"
    cp -f "${REPO_DIR}/scripts/"*.py "${SCRIPTS_DEST}/"
    chmod +x "${SCRIPTS_DEST}/"*.py
    ok "Scripts installed."
}

append_block_if_missing() {
    local file="$1"
    local block="$2"
    mkdir -p "$(dirname "$file")"
    touch "$file"
    if grep -qF "$MARK_START" "$file"; then
        warn "$(basename "$file") already has an installed block, skipping (remove it manually to reinstall)."
        return
    fi
    cp -f "$file" "${file}.bak.$(date +%Y%m%d%H%M%S)"
    printf '\n%s\n' "$block" >> "$file"
    ok "Updated $(basename "$file") (backup created)."
}

patch_autostart() {
    append_block_if_missing "${HYPR_DIR}/autostart.lua" "$MARK_START
-- Infinite Desktop: Super+Alt+drag pans the whole canvas, Super+click+drag
-- near a screen edge pushes the other windows along. Requires python-evdev
-- and membership in the 'input' group (see README).
o.exec_on_start(\"python3 ~/scripts/infinite_desktop_core.py 1.6 > /tmp/infinite-desktop.log 2>&1\")
$MARK_END"
}

patch_hyprland_lua() {
    append_block_if_missing "${HYPR_DIR}/hyprland.lua" "$MARK_START
-- This tool only moves/navigates FLOATING windows, so make every new window
-- start floating instead of tiled. Also give it a sane default size: without
-- this, a floated window inherits the size it would have had as a tiled
-- window, which for the first/only window on a workspace is the full
-- monitor area (looks like fullscreen even though it isn't). Remove this
-- block if you want to keep Omarchy's default tiling behavior for new windows.
o.window(\".*\", { float = true, size = \"60% 60%\" })

-- Omarchy's own browser.lua force-tiles chromium/firefox-based browsers
-- (tag \"chromium-based-browser\" / \"firefox-based-browser\"), which otherwise
-- overrides the generic float rule above. Override it back to floating.
o.window({ tag = \"chromium-based-browser\" }, { float = true, size = \"60% 60%\" })
o.window({ tag = \"firefox-based-browser\" }, { float = true, size = \"60% 60%\" })
$MARK_END"
}

patch_bindings() {
    append_block_if_missing "${HYPR_DIR}/bindings.lua" "$MARK_START
-- These keys were checked against a stock Omarchy install and don't collide
-- with any default binding. If you have heavily customized your own
-- bindings.lua already, press Super+K afterwards to double check.

-- Workspace switching (prev/next)
o.bind(\"SUPER + Z\", \"Infinite Desktop: previous workspace\", hl.dsp.focus({ workspace = \"-1\" }))
o.bind(\"SUPER + PERIOD\", \"Infinite Desktop: next workspace\", hl.dsp.focus({ workspace = \"+1\" }))
o.bind(\"SUPER + SHIFT + Z\", \"Infinite Desktop: move window to previous workspace\", hl.dsp.window.move({ workspace = \"-1\" }))
o.bind(\"SUPER + SHIFT + PERIOD\", \"Infinite Desktop: move window to next workspace\", hl.dsp.window.move({ workspace = \"+1\" }))

-- Toggle floating/tiled for all windows on the active workspace
o.bind(\"SUPER + D\", \"Infinite Desktop: toggle floating/tiled (all windows)\", \"python3 ~/scripts/floating_tile_toggle.py\")

-- Manual escape hatch: reset the currently-enlarged window back to its original size
o.bind(\"SUPER + 0\", \"Infinite Desktop: reset enlarged window size\", \"python3 ~/scripts/reset_zoom.py\")

-- Navigate between windows: focuses the neighbor, pans the camera to center
-- it, and grows it (real resize, not a screen zoom) based on how small it is.
-- Replaces Omarchy's default \"move window to group\" bind on the same keys.
hl.unbind(\"SUPER + ALT + LEFT\")
hl.unbind(\"SUPER + ALT + RIGHT\")
hl.unbind(\"SUPER + ALT + UP\")
hl.unbind(\"SUPER + ALT + DOWN\")
o.bind(\"SUPER + ALT + LEFT\", \"Infinite Desktop: navigate window (left)\", \"python3 ~/scripts/navigate_windows.py left\")
o.bind(\"SUPER + ALT + RIGHT\", \"Infinite Desktop: navigate window (right)\", \"python3 ~/scripts/navigate_windows.py right\")
o.bind(\"SUPER + ALT + UP\", \"Infinite Desktop: navigate window (up)\", \"python3 ~/scripts/navigate_windows.py up\")
o.bind(\"SUPER + ALT + DOWN\", \"Infinite Desktop: navigate window (down)\", \"python3 ~/scripts/navigate_windows.py down\")

-- Move a tiled window
o.bind(\"SUPER + SHIFT + CTRL + LEFT\", \"Infinite Desktop: move tiled window (left)\", \"python3 ~/scripts/move_window_tiled.py left\")
o.bind(\"SUPER + SHIFT + CTRL + RIGHT\", \"Infinite Desktop: move tiled window (right)\", \"python3 ~/scripts/move_window_tiled.py right\")
o.bind(\"SUPER + SHIFT + CTRL + UP\", \"Infinite Desktop: move tiled window (up)\", \"python3 ~/scripts/move_window_tiled.py up\")
o.bind(\"SUPER + SHIFT + CTRL + DOWN\", \"Infinite Desktop: move tiled window (down)\", \"python3 ~/scripts/move_window_tiled.py down\")

-- Move a floating window
o.bind(\"SUPER + CTRL + ALT + H\", \"Infinite Desktop: move floating window (left)\", \"python3 ~/scripts/move_window.py left\", { repeating = true })
o.bind(\"SUPER + CTRL + ALT + L\", \"Infinite Desktop: move floating window (right)\", \"python3 ~/scripts/move_window.py right\", { repeating = true })
o.bind(\"SUPER + CTRL + ALT + K\", \"Infinite Desktop: move floating window (up)\", \"python3 ~/scripts/move_window.py up\", { repeating = true })
o.bind(\"SUPER + CTRL + ALT + J\", \"Infinite Desktop: move floating window (down)\", \"python3 ~/scripts/move_window.py down\", { repeating = true })

-- Resize the active floating window
o.bind(\"SUPER + SHIFT + ALT + H\", \"Infinite Desktop: resize window (left)\", \"python3 ~/scripts/resize_window.py left\", { repeating = true })
o.bind(\"SUPER + SHIFT + ALT + L\", \"Infinite Desktop: resize window (right)\", \"python3 ~/scripts/resize_window.py right\", { repeating = true })
o.bind(\"SUPER + SHIFT + ALT + K\", \"Infinite Desktop: resize window (up)\", \"python3 ~/scripts/resize_window.py up\", { repeating = true })
o.bind(\"SUPER + SHIFT + ALT + J\", \"Infinite Desktop: resize window (down)\", \"python3 ~/scripts/resize_window.py down\", { repeating = true })

-- Mouse-only, no keybind needed (raw evdev, autostarted via autostart.lua):
--   Super + Alt + drag mouse/touchpad -> pan the whole desktop
--   Super + click + drag a window to a screen edge -> push the other windows along
$MARK_END"
}

echo -e "${C_BOLD}omarchy-windows-free-position installer${C_RESET}"
echo ""

NEED_RELOGIN=0

install_packages
setup_input_group
install_scripts
patch_autostart
patch_hyprland_lua
patch_bindings

echo ""
ok "Installation complete."
echo ""
echo "Next steps:"
echo "  - Run 'hyprctl reload' or restart your session to apply the config changes."
if [ "${NEED_RELOGIN:-0}" -eq 1 ]; then
    warn "  - You must log out / reboot for the 'input' group membership to take effect."
fi
echo "  - Press Super+K to see all the new keybindings (and check for conflicts if you customized bindings.lua before)."
