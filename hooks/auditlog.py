"""
Registo de violacoes, append-only, uma linha JSON por evento.

REGRA DE OURO: este ficheiro NUNCA contem o valor real do dado pessoal.
Guarda o pseudonimo (EMAIL_001). Se o log guardasse o valor, passaria a ser
ele proprio um deposito de PII — e um deposito pior que o original, porque
cresce sem limite e ninguem se lembra dele. Para chegar ao valor real
cruza-se com o mapa: `guard-rail map EMAIL_001`.

Formato JSONL: uma linha por evento, appendavel sem ler o ficheiro todo,
greppavel, e legivel por qualquer ferramenta de SIEM.
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path.home() / ".cache" / "guard-rail"
LOG_PATH = LOG_DIR / "violations.jsonl"

# Acoes possiveis, por ordem de gravidade operacional
BLOCKED = "blocked"  # prompt travado, nada saiu
REDACTED = "redacted"  # dado substituido por pseudonimo, trabalho continuou
NOT_REDACTED = "not_redacted"  # PASSOU EM CLARO — o caso que interessa auditar
DEGRADED = "degraded"  # controlo a funcionar abaixo do previsto (ex.: Ollama em baixo)
ARMED = "armed"  # sessao arrancou; serve para provar que os hooks disparam

MAX_FINDINGS_PER_EVENT = 50


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def record(
    *,
    severity: str,
    action: str,
    point: str,
    session_id: str = "",
    findings: list[dict] | None = None,
    total: int = 0,
    cwd: str = "",
    note: str = "",
) -> None:
    """
    Escreve um evento. Nunca levanta excecao: um log que rebenta nao pode
    tirar o Claude Code do ar.

    point  -- onde ocorreu: "UserPromptSubmit" ou o nome da ferramenta
    findings -- [{"kind": "Email", "pseudonym": "EMAIL_001"}, ...]
    """
    entry = {
        "ts": _now(),
        "severity": severity,
        "action": action,
        "point": point,
        "total": total,
        "session": session_id[:64],
    }
    if cwd:
        entry["cwd"] = cwd
    if note:
        entry["note"] = note
    if findings:
        entry["findings"] = findings[:MAX_FINDINGS_PER_EVENT]
        if len(findings) > MAX_FINDINGS_PER_EVENT:
            entry["findings_truncated"] = len(findings) - MAX_FINDINGS_PER_EVENT

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        existed = LOG_PATH.exists()
        # Append em modo linha: escritas curtas de processos concorrentes
        # nao se entrelacam em POSIX.
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if not existed:
            os.chmod(LOG_PATH, 0o600)
    except OSError:
        pass


def summarise_findings(items) -> tuple[list[dict], dict[str, int]]:
    """
    Converte achados em entradas de log e conta por tipo.

    `items` sao pares (kind, pseudonimo). O pseudonimo pode ser None quando
    o dado foi bloqueado em vez de redigido — nesse caso nao existe rotulo.
    """
    findings: list[dict] = []
    counts: dict[str, int] = {}
    for kind, pseudonym in items:
        counts[kind] = counts.get(kind, 0) + 1
        entry = {"kind": kind}
        if pseudonym:
            entry["pseudonym"] = pseudonym
        findings.append(entry)
    return findings, counts


def read_events(
    path: Path | None = None,
    since: str | None = None,
    severity: str | None = None,
    action: str | None = None,
) -> list[dict]:
    """Le o log com filtros. Linhas corrompidas sao saltadas em silencio."""
    target = path or LOG_PATH
    if not target.is_file():
        return []

    out: list[dict] = []
    with open(target, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since and entry.get("ts", "") < since:
                continue
            if severity and entry.get("severity") != severity:
                continue
            if action and entry.get("action") != action:
                continue
            out.append(entry)
    return out
