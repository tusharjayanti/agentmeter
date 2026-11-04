"""Minimal interactive prompts (stdlib only): select, multiselect, text, confirm.

Arrow keys / j k move, space toggles, enter confirms, q or ctrl-c aborts.
Falls back to numbered input when stdin is not a terminal.
"""
from __future__ import annotations

import os
import sys

try:
    import termios
    import tty
except ImportError:  # Windows
    termios = tty = None

CSI = "\x1b["
BOLD, DIM, CYAN, GREEN, RESET = "\x1b[1m", "\x1b[2m", "\x1b[36m", "\x1b[32m", "\x1b[0m"


class Abort(Exception):
    pass


def _tty() -> bool:
    return termios is not None and sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def _key() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch += sys.stdin.read(2)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch in ("\x03", "q"):
        raise Abort
    return {"\x1b[A": "up", "\x1b[B": "down", "k": "up", "j": "down", "\r": "enter", "\n": "enter", " ": "space"}.get(ch, ch)


def _draw(lines: list[str], first: bool):
    if not first:
        sys.stdout.write(f"{CSI}{len(lines)}A")
    for ln in lines:
        sys.stdout.write(f"{CSI}2K{ln}\n")
    sys.stdout.flush()


def select(question: str, options: list[str], default: int = 0, hint: str = "") -> int:
    """Single choice; returns index."""
    print(f"{BOLD}{question}{RESET}" + (f"  {DIM}{hint}{RESET}" if hint else ""))
    if not _tty():
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}")
        while True:
            raw = _input(f"  choose [1-{len(options)}] ({default + 1}): ").strip()
            if not raw:
                return default
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1
    cur, first = default, True
    while True:
        _draw([f"  {CYAN + '❯' if i == cur else ' '} {o}{RESET}" for i, o in enumerate(options)], first)
        first = False
        k = _key()
        if k == "up":
            cur = (cur - 1) % len(options)
        elif k == "down":
            cur = (cur + 1) % len(options)
        elif k == "enter":
            print()
            return cur


def multiselect(question: str, options: list[str], checked: set[int] | None = None, hint: str = "space toggles · enter confirms") -> list[int]:
    """Several choices; returns sorted indices."""
    checked = set(checked or ())
    print(f"{BOLD}{question}{RESET}  {DIM}{hint}{RESET}")
    if not _tty():
        for i, o in enumerate(options, 1):
            print(f"  {i}. [{'x' if i - 1 in checked else ' '}] {o}")
        raw = _input("  numbers, comma-separated (enter keeps the defaults): ").strip()
        if raw:
            checked = {int(x) - 1 for x in raw.replace(" ", "").split(",") if x.isdigit() and 1 <= int(x) <= len(options)}
        return sorted(checked)
    cur, first = 0, True
    while True:
        lines = [f"  {CYAN + '❯' if i == cur else ' '} {GREEN + '◉' if i in checked else '○'} {o}{RESET}" for i, o in enumerate(options)]
        _draw(lines, first)
        first = False
        k = _key()
        if k == "up":
            cur = (cur - 1) % len(options)
        elif k == "down":
            cur = (cur + 1) % len(options)
        elif k == "space":
            checked ^= {cur}
        elif k == "enter":
            print()
            return sorted(checked)


def _input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise Abort


def text(question: str, default: str = "", validate=None) -> str:
    while True:
        raw = _input(f"{BOLD}{question}{RESET} {DIM}({default}){RESET}: " if default else f"{BOLD}{question}{RESET}: ").strip()
        val = raw or default
        if validate:
            err = validate(val)
            if err:
                print(f"  {err}")
                continue
        return val


def confirm(question: str, default: bool = True) -> bool:
    return select(question, ["Yes", "No"], default=0 if default else 1) == 0
