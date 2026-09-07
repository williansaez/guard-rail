#!/usr/bin/env python3
"""
Hook PostToolUse: substitui dados pessoais no resultado da ferramenta
por pseudonimos estaveis, ANTES de o Claude ver.

Contrato (confirmado na doc):
  hookSpecificOutput.updatedToolOutput  -> substitui tool_response
Ao contrario do UserPromptSubmit, aqui da mesmo para reescrever. Por isso
este hook nunca bloqueia: redige e deixa passar.

Nota de desempenho: isto corre em TODA a chamada de ferramenta, incluindo
Bash e Read. Por isso o caminho normal e so regex (~0.02 ms). O modelo local
so entra em resultados MCP abaixo de um limite de tamanho, e por opcao.
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import auditlog  # noqa: E402
import detectors  # noqa: E402
import pseudonyms  # noqa: E402

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).parent.parent))

DEFAULTS = {
    "enabled": True,
    "redact_tool_output": True,
    "client_terms": [],
    # Ferramentas cujo resultado e inspecionado.
    "redact_matchers": ["mcp__*__*", "Read", "Grep", "Bash"],
    # Acima disto nem tentamos: um dump gigante custaria mais a varrer
    # do que vale, e e sinal de que o dado nao devia estar aqui.
    "max_output_chars": 400_000,
    # Modelo local sobre output de ferramenta: apanha nomes de pessoas que a
    # regex nao apanha, mas paga latencia em cada chamada. Ver README.
    "llm_on_tool_output": False,
    "llm_tool_matchers": ["mcp__abap-adt__*"],
    "llm_max_chars": 4000,
    "model": "qwen3.5:9b",
    "ollama_host": "http://localhost:11434",
    "timeout_seconds": 8,
    "keep_alive": "30m",
}


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


def matches(tool_name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(tool_name, p) for p in patterns)


def redact_text(
    text: str,
    pmap: pseudonyms.PseudonymMap,
    client_terms: list[str],
    audit: list[tuple[str, str, str]],
) -> str:
    """
    Uma unica passagem por ordem de leitura, montando os pedacos numa lista.

    A versao obvia — substituir de tras para a frente com `out[:s] + label +
    out[e:]` — copia a string inteira a cada achado. Num resultado de 200 KB
    com milhares de achados isso e quadratico: media-se em 552 ms. Assim
    fica linear, e a numeracao sai na ordem em que se le o texto.

    `audit` recebe (tipo, pseudonimo, gravidade). Nunca o valor real.
    """
    findings = detectors.find_pii(text, client_terms)
    if not findings:
        return text

    parts: list[str] = []
    cursor = 0
    for f in findings:
        label = pmap.pseudonym_for(f.prefix, f.value)
        audit.append((f.kind, label, f.level))
        parts.append(text[cursor : f.start])
        parts.append(label)
        cursor = f.end
    parts.append(text[cursor:])

    return "".join(parts)


def walk(node, pmap, client_terms, audit: list[tuple[str, str, str]]):
    """Percorre a arvore do tool_response e redige todas as strings."""
    if isinstance(node, str):
        return redact_text(node, pmap, client_terms, audit)
    if isinstance(node, dict):
        return {k: walk(v, pmap, client_terms, audit) for k, v in node.items()}
    if isinstance(node, list):
        return [walk(v, pmap, client_terms, audit) for v in node]
    return node


def apply_llm(text: str, pmap, cfg, audit: list[tuple[str, str, str]]) -> str:
    """
    Camada opcional: pede ao modelo local os nomes de pessoas e moradas que
    a regex nao apanha, e substitui-os literalmente.
    """
    import classifier

    names = classifier.extract_entities(
        text,
        model=cfg["model"],
        host=cfg["ollama_host"],
        timeout=cfg["timeout_seconds"],
        keep_alive=cfg["keep_alive"],
    )
    for prefix, value in names:
        if not value or len(value) < 3 or value not in text:
            continue
        label = pmap.pseudonym_for(prefix, value)
        text = text.replace(value, label)
        audit.append((f"{prefix.title()} (modelo local)", label, "ALTO"))
    return text


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    cfg = load_config()
    if not cfg["enabled"] or not cfg["redact_tool_output"]:
        return 0

    tool_name = data.get("tool_name") or ""
    response = data.get("tool_response")

    if response is None or not matches(tool_name, cfg["redact_matchers"]):
        return 0

    session_id = data.get("session_id", "default")
    cwd = data.get("cwd", "")

    serialised = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
    if len(serialised) > cfg["max_output_chars"]:
        # Este e' o evento mais importante do log: dado passou EM CLARO.
        auditlog.record(
            severity="ALTO",
            action=auditlog.NOT_REDACTED,
            point=tool_name,
            session_id=session_id,
            cwd=cwd,
            note=(
                f"resultado com {len(serialised)} chars excede max_output_chars="
                f"{cfg['max_output_chars']}; passou sem inspecao"
            ),
        )
        print(
            f"guard-rail: resultado de {tool_name} tem {len(serialised)} chars "
            f"(limite {cfg['max_output_chars']}) — NAO foi redigido.",
            file=sys.stderr,
        )
        return 0

    pmap = pseudonyms.PseudonymMap(session_id)
    audit: list[tuple[str, str, str]] = []
    redacted = walk(response, pmap, cfg["client_terms"], audit)

    if (
        cfg["llm_on_tool_output"]
        and isinstance(redacted, str)
        and len(redacted) <= cfg["llm_max_chars"]
        and matches(tool_name, cfg["llm_tool_matchers"])
    ):
        try:
            redacted = apply_llm(redacted, pmap, cfg, audit)
        except Exception as exc:  # noqa: BLE001
            auditlog.record(
                severity="INFO",
                action=auditlog.DEGRADED,
                point=tool_name,
                session_id=session_id,
                cwd=cwd,
                note=f"camada LLM falhou: {type(exc).__name__}",
            )
            print(f"guard-rail: camada LLM falhou ({type(exc).__name__})", file=sys.stderr)

    if not audit:
        return 0  # nada mudou: nao mexer no resultado

    pmap.save()

    severity = "NENHUM"
    for _, _, level in audit:
        severity = detectors.max_level(severity, level)

    logged, _ = auditlog.summarise_findings([(k, p) for k, p, _ in audit])
    auditlog.record(
        severity=severity,
        action=auditlog.REDACTED,
        point=tool_name,
        session_id=session_id,
        cwd=cwd,
        findings=logged,
        total=len(audit),
    )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedToolOutput": redacted,
                    "additionalContext": (
                        f"[guard-rail] {len(audit)} valor(es) pessoal(is) neste resultado foram "
                        f"substituidos por pseudonimos estaveis (ex.: EMAIL_001). "
                        f"Trata-os como identificadores opacos: sao consistentes dentro da sessao, "
                        f"por isso o mesmo rotulo significa sempre a mesma entidade. "
                        f"Nao tentes adivinhar o valor real nem pedir ao utilizador que o revele."
                    ),
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # Falhar aqui nunca pode partir a ferramenta: sem output = sem alteracao.
        print(f"guard-rail redact falhou: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
