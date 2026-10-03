#!/usr/bin/env python3
"""Animated ASCII dashboard for the Docker — Unified Base demo (panel mode)."""
import sys
import time
from datetime import datetime

# ANSI escape codes
CLEAR = "\033[2J\033[H"      # clear screen + home cursor
HIDE_CUR = "\033[?25l"      # hide cursor
SHOW_CUR = "\033[?25h"      # show cursor
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
DIM = "\033[2m"

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
WHALE = "🐳"
BAR_WIDTH = 28


def out(text):
    sys.stdout.write(text)


def render(frame, start):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uptime = int(time.time() - start)
    spin = SPINNER[frame % len(SPINNER)]

    # Moving progress bar (ping-pong sweep)
    pos = frame % (2 * BAR_WIDTH)
    if pos >= BAR_WIDTH:
        pos = 2 * BAR_WIDTH - pos - 1
    bar = "".join("█" if i == pos else "─" for i in range(BAR_WIDTH))

    out(CLEAR)
    out(f"{BOLD}{CYAN}╔══════════════════════════════════════════════╗{RESET}\n")
    out(f"{BOLD}{CYAN}║{RESET}  {WHALE} {BOLD}Docker — Unified Base demo{RESET}"
        f"          {BOLD}{CYAN}║{RESET}\n")
    out(f"{BOLD}{CYAN}╚══════════════════════════════════════════════╝{RESET}\n")
    out("\n")
    out(f"  {DIM}clock  {RESET}{GREEN}{now}{RESET}\n")
    out(f"  {DIM}uptime {RESET}{YELLOW}{uptime:>6}s{RESET}\n")
    out(f"  {DIM}counter{RESET}{MAGENTA}{frame:>6}{RESET}\n")
    out(f"  {DIM}status {RESET}{BLUE}{spin} running{RESET}\n")
    out("\n")
    out(f"  {DIM}[{RESET}{GREEN}{bar}{RESET}{DIM}]{RESET}\n")
    out("\n")
    out(f"  {DIM}container alive — Ctrl+C to stop{RESET}\n")
    sys.stdout.flush()


def main():
    start = time.time()
    out(HIDE_CUR)
    frame = 0
    try:
        while True:
            render(frame, start)
            frame += 1
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        out(SHOW_CUR + RESET + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
