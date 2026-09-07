#!/usr/bin/env python3
"""
Testes do log de violações.

A asserção mais importante desta suite é a última: o log NUNCA pode conter
o valor real de um dado pessoal. Se contiver, o ficheiro de auditoria passa
a ser um vazamento em si mesmo.

Corre com: python3 tests/test_auditlog.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

results = {"pass": 0, "fail": 0}

# Valores reais usados nos testes. Nenhum destes pode aparecer no log.
REAL_VALUES = [
    "joao.silva@cliente.pt",
    "ana.costa@cliente.pt",
    "529.982.247-25",
    "52998224725",
    "111.444.777-35",
]


def _has_tz(ts: str) -> bool:
    """Um timestamp de auditoria sem fuso é inútil para reconstruir factos."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(ts).tzinfo is not None
    except ValueError:
        return False


def check(desc: str, ok: bool, detail: str = "") -> None:
    if ok:
        results["pass"] += 1
        print(f"  ok   {desc}")
    else:
        results["fail"] += 1
        print(f"  FAIL {desc}")
        if detail:
            print(f"       {detail}")


def run(script: str, payload: dict, home: Path) -> tuple[int, str, str]:
    env = {**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def cli(args: list[str], home: Path) -> str:
    env = {**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run(
        [sys.executable, str(ROOT / "bin" / "guard-rail"), *args],
        capture_output=True,
        text=True,
        env=env,
    ).stdout


def log_lines(home: Path) -> list[dict]:
    path = home / ".cache" / "guard-rail" / "violations.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


QUERY = (
    "LIFNR      | EMAIL                  | CPF            | BELNR\n"
    "0010000006 | joao.silva@cliente.pt  | 529.982.247-25 | 5105600787\n"
    "0010000012 | ana.costa@cliente.pt   | 111.444.777-35 | 5105600790\n"
)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)

        # --- ponto de violação 1: resultado de ferramenta redigido ---------
        print("\n=== ponto 1: resultado de ferramenta redigido ===")
        run("redact.py", {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "cwd": "/projeto/sap",
            "tool_name": "mcp__abap-adt__runQuery",
            "tool_response": QUERY,
        }, home)

        events = log_lines(home)
        check("evento registado", len(events) == 1, str(events))
        if events:
            e = events[0]
            check("ação = redacted", e["action"] == "redacted", str(e))
            check("gravidade = ALTO", e["severity"] == "ALTO", str(e))
            check("ponto = nome da ferramenta", e["point"] == "mcp__abap-adt__runQuery", str(e))
            check("timestamp ISO 8601 com fuso", _has_tz(e["ts"]), e["ts"])
            check("cwd registado", e.get("cwd") == "/projeto/sap", str(e))
            check("total de achados = 4", e["total"] == 4, str(e))
            check("achados trazem pseudónimo", all("pseudonym" in f for f in e["findings"]), str(e))
            kinds = {f["kind"] for f in e["findings"]}
            check("tipos identificados", kinds == {"Email", "CPF"}, str(kinds))

        # --- ponto de violação 2: prompt bloqueado -------------------------
        print("\n=== ponto 2: prompt do utilizador bloqueado ===")
        code, _, _ = run("guard.py", {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "cwd": "/projeto/sap",
            "prompt": "corrige o registo do titular com CPF 529.982.247-25 por favor",
        }, home)
        check("hook bloqueou (exit 2)", code == 2)

        events = log_lines(home)
        blocked = [e for e in events if e["action"] == "blocked"]
        check("bloqueio registado", len(blocked) == 1, str(events))
        if blocked:
            check("ponto = UserPromptSubmit", blocked[0]["point"] == "UserPromptSubmit", str(blocked[0]))
            check("gravidade = ALTO", blocked[0]["severity"] == "ALTO", str(blocked[0]))
            check(
                "bloqueio não tem pseudónimo (nada foi redigido)",
                all("pseudonym" not in f for f in blocked[0]["findings"]),
                str(blocked[0]),
            )

        # --- ponto de violação 3: output grande passou em claro ------------
        print("\n=== ponto 3: output acima do limite passou em claro ===")
        run("redact.py", {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "tool_name": "mcp__abap-adt__tableContents",
            "tool_response": QUERY * 5000,
        }, home)

        leaks = [e for e in log_lines(home) if e["action"] == "not_redacted"]
        check("vazamento registado", len(leaks) == 1, str(leaks))
        if leaks:
            check("gravidade = ALTO", leaks[0]["severity"] == "ALTO", str(leaks[0]))
            check("nota explica o motivo", "max_output_chars" in leaks[0].get("note", ""), str(leaks[0]))

        # --- degradação: Ollama em baixo -----------------------------------
        # Precisa de um prompt LIMPO e com ≥40 chars: só aí a camada LLM é
        # consultada. Com PII a regex decide sozinha e o Ollama nem é chamado.
        print("\n=== controlo degradado (Ollama ausente) ===")
        code, _, err = run("guard.py", {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "explica-me como funciona a activação de objectos no transporte XS4K903815",
        }, home)
        check("prompt limpo passa mesmo com Ollama em baixo (exit 0)", code == 0, err)
        check("avisa no stderr que ficou só com a regex", "regex" in err, err)

        degraded = [e for e in log_lines(home) if e["action"] == "degraded"]
        check("degradação registada", len(degraded) >= 1, str(degraded))
        if degraded:
            check("gravidade INFO, não é violação", degraded[0]["severity"] == "INFO", str(degraded[0]))
            check("nota diz o que falhou", "Ollama" in degraded[0].get("note", ""), str(degraded[0]))

        # --- A ASSERÇÃO QUE INTERESSA --------------------------------------
        print("\n=== o log não pode conter valores reais ===")
        raw = (home / ".cache" / "guard-rail" / "violations.jsonl").read_text(encoding="utf-8")
        for value in REAL_VALUES:
            check(f"'{value}' ausente do log", value not in raw)
        check("pseudónimos presentes no log", "EMAIL_001" in raw, raw[:400])

        # --- permissões -----------------------------------------------------
        mode = oct((home / ".cache" / "guard-rail" / "violations.jsonl").stat().st_mode)[-3:]
        check(f"log com permissões 0600 (são {mode})", mode == "600")

        # --- CLI -------------------------------------------------------------
        print("\n=== CLI: guard-rail log ===")
        out = cli(["log"], home)
        check("lista eventos", "BLOQUEADO" in out and "redigido" in out, out)
        check("mostra PASSOU EM CLARO", "PASSOU EM CLARO" in out, out)
        check("CLI não expõe valores reais", all(v not in out for v in REAL_VALUES), out)

        out = cli(["log", "--leaks"], home)
        check("filtro --leaks só mostra vazamentos", "BLOQUEADO" not in out, out)

        out = cli(["log", "--severity", "ALTO"], home)
        check("filtro --severity funciona", "controlo degradado" not in out, out)

        print("\n--- guard-rail log --summary ---")
        summary = cli(["log", "--summary"], home)
        print("\n".join("    " + l for l in summary.splitlines()))
        check("resumo agrega por ponto", "mcp__abap-adt__runQuery" in summary, summary)
        check("resumo avisa de vazamentos", "EM CLARO" in summary, summary)

        print("\n--- guard-rail log (vista normal) ---")
        print("\n".join("    " + l for l in cli(["log"], home).splitlines()[:12]))

    print(f"\n{results['pass']} passaram, {results['fail']} falharam")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
