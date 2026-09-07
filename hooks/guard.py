#!/usr/bin/env python3
"""
Hook UserPromptSubmit: bloqueia prompts com dados pessoais (LGPD / RGPD).

Contrato do hook (confirmado na doc do Claude Code):
  - exit 0            -> prompt segue para a Anthropic
  - exit 2 + stderr   -> prompt BLOQUEADO, stderr mostrado ao utilizador
  - NAO existe forma de reescrever o prompt. Por isso este hook so decide
    passa/nao passa; a sanitizacao e sempre um ato consciente do utilizador.

Fluxo:
  1. Escape hatch `!ok` -> passa sem verificar
  2. Mascara identificadores de sistema (SAP, ABAP, tickets)
  3. Regex com digito de controlo -> decide sozinha na maioria dos casos
  4. So se a regex nao deu ALTO, consulta o qwen3.5:9b local
  5. ALTO ou MEDIO -> bloqueia e entrega o comando para correr offline
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import auditlog  # noqa: E402
import classifier  # noqa: E402
import detectors  # noqa: E402

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).parent.parent))
CACHE_DIR = Path.home() / ".cache" / "guard-rail"

DEFAULTS = {
    "enabled": True,
    "model": "qwen3.5:9b",
    "ollama_host": "http://localhost:11434",
    "timeout_seconds": 8,
    "keep_alive": "30m",
    "use_llm": True,
    # Se o Ollama estiver em baixo: True bloqueia por precaucao,
    # False confia so na regex. Ver README, seccao "Modo de falha".
    "fail_closed": False,
    # Nivel minimo que bloqueia. "MEDIO" bloqueia tambem nomes de cliente.
    "block_at": "MEDIO",
    # Termos que identificam clientes teus. Preenche isto.
    "client_terms": [],
    # Nao chamar o LLM em prompts curtos: raramente contem PII em prosa
    # e a latencia notava-se em toda a interacao.
    "min_chars_for_llm": 40,
}

LEVEL_ORDER = {"NENHUM": 0, "MEDIO": 1, "ALTO": 2}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    for path in (PLUGIN_ROOT / "config.json", Path.home() / ".config" / "guard-rail.json"):
        if path.is_file():
            try:
                cfg.update(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    if os.environ.get("GUARD_RAIL_OFF") == "1":
        cfg["enabled"] = False
    return cfg


def stash_prompt(prompt: str) -> Path:
    """Guarda o prompt bloqueado em disco local para consulta offline."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"blocked-{int(time.time())}.txt"
    path.write_text(prompt, encoding="utf-8")
    path.chmod(0o600)
    return path


def build_block_message(level: str, findings: list[str], stash: Path, warning: str | None) -> str:
    icon = "🔴" if level == "ALTO" else "🟡"
    label = "dados pessoais" if level == "ALTO" else "dados de cliente"

    lines = [
        f"{icon} Prompt bloqueado — {label} detectados ({level}).",
        "",
        "Achados:",
    ]
    lines += [f"  • {f}" for f in findings] or ["  • (sem detalhe)"]
    lines += [
        "",
        "Opções:",
        f"  1. Correr offline (nada sai da máquina):",
        f"       guard-rail local {stash}",
        "  2. Reescrever sem os dados acima e reenviar.",
    ]
    if level == "MEDIO":
        lines.append('  3. Forçar envio: prefixa a mensagem com "!ok ".')
    if warning:
        lines += ["", f"⚠️  {warning}"]
    return "\n".join(lines)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # nao percebemos o input: nao estorvar o utilizador

    prompt = data.get("prompt") or ""
    cfg = load_config()

    if not cfg["enabled"] or not prompt.strip():
        return 0

    # 1. Escape hatch consciente
    if prompt.lstrip().startswith("!ok"):
        return 0

    session_id = data.get("session_id", "")
    cwd = data.get("cwd", "")

    # 2. Identificadores de sistema saem de cena antes da varredura
    masked = detectors.mask_allowlist(prompt)

    # 3. Camada deterministica
    hits = detectors.find_pii(masked, cfg["client_terms"])
    level = "NENHUM"
    seen: set[str] = set()
    findings: list[str] = []
    audit_items: list[tuple[str, str | None]] = []

    for hit in hits:
        level = detectors.max_level(level, hit.level)
        audit_items.append((hit.kind, None))
        if hit.kind not in seen:
            seen.add(hit.kind)
            findings.append(f"{hit.kind}: {detectors.redact_preview(hit.value)}")

    # 4. Camada LLM: so quando a regex nao fechou o caso
    warning = None
    if (
        cfg["use_llm"]
        and level != "ALTO"
        and len(masked) >= cfg["min_chars_for_llm"]
    ):
        llm_level, llm_findings, err = classifier.classify(
            masked,
            model=cfg["model"],
            host=cfg["ollama_host"],
            timeout=cfg["timeout_seconds"],
            keep_alive=cfg["keep_alive"],
        )
        if err:
            warning = f"{err} — decisão tomada só pela regex."
            # Um controlo a funcionar abaixo do previsto e' facto auditavel:
            # permite dizer depois "nesta janela o modelo local esteve em baixo".
            auditlog.record(
                severity="INFO",
                action=auditlog.DEGRADED,
                point="UserPromptSubmit",
                session_id=session_id,
                cwd=cwd,
                note=err,
            )
            if cfg["fail_closed"]:
                level = detectors.max_level(level, "MEDIO")
                findings.append("Classificador local indisponível (fail_closed)")
                audit_items.append(("Classificador indisponível", None))
        else:
            level = detectors.max_level(level, llm_level)
            findings += [f"{f} (modelo local)" for f in llm_findings]
            audit_items += [("Modelo local", None) for _ in llm_findings]

    # 5. Decisao
    if LEVEL_ORDER[level] >= LEVEL_ORDER[cfg["block_at"]]:
        stash = stash_prompt(prompt)
        logged, _ = auditlog.summarise_findings(audit_items)
        auditlog.record(
            severity=level,
            action=auditlog.BLOCKED,
            point="UserPromptSubmit",
            session_id=session_id,
            cwd=cwd,
            findings=logged,
            total=len(audit_items),
        )
        print(build_block_message(level, findings, stash, warning), file=sys.stderr)
        return 2

    if warning:
        print(f"⚠️  guard-rail: {warning}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # Um hook rebentado nunca deve deixar o utilizador sem Claude Code.
        print(f"guard-rail falhou: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)  # exit 1 = erro nao bloqueante
