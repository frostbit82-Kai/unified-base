#!/usr/bin/env bash
# One-time system setup for Unified Base on a fresh Ubuntu install.
# Installs the apt-level dependencies; run.sh handles the venv + pip side.
set -e

sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip \
    libgl1 libegl1 libopengl0 \
    libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
    libxcb-shape0 libxcb-xinerama0 libxcb-randr0 libxcb-render-util0 \
    libfontconfig1 libdbus-1-3 \
    libxcomposite1 libxdamage1 libxrandr2 libxtst6 \
    xdotool

echo
echo "Done. Now run:  ./run.sh"
echo "Note: window embedding needs an X11 session (Xorg), not Wayland —"
echo "pick 'Ubuntu on Xorg' at the login screen if tabs won't embed."
