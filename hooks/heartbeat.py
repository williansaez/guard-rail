#!/usr/bin/env python3
"""
Hook SessionStart: regista que o guard-rail arrancou.

Nao protege nada. Existe por uma razao so: provar quais hooks disparam
mesmo nesta superficie.

Um plugin de privacidade que falha em silencio e' pior que nao ter plugin
nenhum — passas a confiar numa protecao que nao existe. Se o log tiver
eventos `armed` mas nunca um `redacted` depois de usares ferramentas com
dados pessoais, entao o PostToolUse nao esta a disparar aqui.

`guard-rail doctor` le exatamente isso.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import auditlog  # noqa: E402


def detect_surface() -> str:
    """
    Cowork corre em ~/Library/Application Support/Claude/local-agent-mode-sessions.
    Nao ha variavel oficial que distinga as superficies, por isso isto e'
    heuristica declarada — se falhar, diz "desconhecida" em vez de mentir.
    """
    for var in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR"):
        value = os.environ.get(var, "")
        if "local-agent-mode-sessions" in value:
            return "cowork"
        if "/.claude/plugins" in value:
            return "claude-code-cli"
    return "desconhecida"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    auditlog.record(
        severity="INFO",
        action=auditlog.ARMED,
        point="SessionStart",
        session_id=data.get("session_id", ""),
        cwd=data.get("cwd", ""),
        note=f"superficie={detect_surface()} python={sys.version.split()[0]}",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)  # nunca estorvar o arranque da sessao
