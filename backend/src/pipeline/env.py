from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# backend/ — the same anchor db.py uses to find migrations/.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_CANDIDATES = (_BACKEND_DIR / ".env", _BACKEND_DIR.parent / ".env")


def load_env() -> list[Path]:
    """Load .env into the process environment; return the files that were read.

    Call this from entry points only, never at import of a library module — a
    test or an embedding application has to stay in control of its own
    environment.

    `override=False` means a real environment variable always beats the file,
    so CI and deployment can inject values without a .env existing at all.

    Secrets live here rather than in the machine's environment on purpose: an
    exported ANTHROPIC_API_KEY is visible to every process on the box,
    including other Anthropic tooling, which would then bill this project's API
    account instead of its own subscription.
    """
    loaded: list[Path] = []
    for path in _CANDIDATES:
        if path.is_file():
            # utf-8-sig, not utf-8: Notepad, Out-File, and PowerShell 5.1's
            # `Set-Content -Encoding utf8` all write a BOM, which python-dotenv
            # would otherwise fold into the first key — ANTHROPIC_API_KEY
            # silently becomes "﻿ANTHROPIC_API_KEY" and reads as missing.
            load_dotenv(path, override=False, encoding="utf-8-sig")
            loaded.append(path)
    return loaded
