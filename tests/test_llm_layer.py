#!/usr/bin/env python3
"""
Testes da camada LLM: o pedido que sai para o Ollama e o aviso quando ela falha.

Dois bugs que estes testes fixam:

1. O qwen3.5 é um modelo de raciocínio. Sem `"think": false`, o Ollama põe a
   saída no campo `thinking` e deixa `response` vazio — o classificador lia
   uma string vazia e registava "Resposta do modelo nao era JSON valido" em
   todos os prompts, desde o primeiro dia.

2. O aviso de degradação ia para stderr com exit 0, que o Claude Code não
   mostra ao utilizador. 245 degradações passaram sem ninguém ver. Agora sai
   como `systemMessage` em stdout, no máximo uma vez por sessão (de novo ao
   fim de 30 minutos, se a falha continuar).

Corre com: python3 tests/test_llm_layer.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

results = {"pass": 0, "fail": 0}

# Prompt limpo e com ≥40 chars: só assim a camada LLM é consultada.
CLEAN_PROMPT = "explica-me como funciona a activação de objectos no transporte XS4K903815"


def check(desc: str, ok: bool, detail: str = "") -> None:
    if ok:
        results["pass"] += 1
        print(f"  ok   {desc}")
    else:
        results["fail"] += 1
        print(f"  FAIL {desc}")
        if detail:
            print(f"       {detail}")


def run(payload: dict, home: Path) -> tuple[int, str, str]:
    env = {**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "guard.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def force_ollama_down(home: Path) -> None:
    """Porta 1: privilegiada, a ligação é recusada de imediato, sem timeout."""
    path = home / ".config" / "guard-rail.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ollama_host": "http://127.0.0.1:1"}), encoding="utf-8")


def prompt(session: str) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": CLEAN_PROMPT}


def system_message(stdout: str) -> str:
    """O texto do systemMessage, ou "" se o stdout não for esse JSON."""
    try:
        return json.loads(stdout).get("systemMessage", "") if stdout.strip() else ""
    except json.JSONDecodeError:
        return ""


def degraded_count(home: Path) -> int:
    path = home / ".cache" / "guard-rail" / "violations.jsonl"
    if not path.is_file():
        return 0
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return sum(1 for e in lines if e["action"] == "degraded")


# ---------------------------------------------------------------------------
# 1. O pedido ao Ollama desliga o raciocínio
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body: dict):
        self._raw = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def capture_payload(fn, response_text: str) -> dict:
    """Corre `fn` com o urlopen interceptado e devolve o payload que enviou."""
    import classifier

    sent: dict = {}

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data.decode("utf-8")))
        return _FakeResponse({"response": response_text})

    original = classifier.urllib.request.urlopen
    classifier.urllib.request.urlopen = fake_urlopen
    try:
        fn()
    finally:
        classifier.urllib.request.urlopen = original
    return sent


def test_payload() -> None:
    import classifier

    print("\n=== o pedido desliga o raciocínio do modelo ===")
    sent = capture_payload(
        lambda: classifier.classify(CLEAN_PROMPT),
        '{"nivel":"NENHUM","achados":[]}',
    )
    check("classify envia think: false", sent.get("think") is False, str(sent.get("think")))

    sent = capture_payload(
        lambda: classifier.extract_entities(CLEAN_PROMPT),
        '{"pessoas":[],"moradas":[]}',
    )
    check("extract_entities envia think: false", sent.get("think") is False, str(sent.get("think")))


# ---------------------------------------------------------------------------
# 2. A degradação é visível, sem inundar a sessão
# ---------------------------------------------------------------------------

def test_visible_warning() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        force_ollama_down(home)

        print("\n=== primeira degradação da sessão: aviso visível ===")
        code, out, err = run(prompt("s1"), home)
        msg = system_message(out)
        check("prompt passa (exit 0)", code == 0, err)
        check("stdout é JSON com systemMessage", bool(msg), repr(out))
        check("o aviso diz que ficou só com a regex", "regex" in msg, msg)
        check("o aviso já não vai para stderr", "regex" not in err, err)

        print("\n=== segunda degradação na mesma sessão: sem repetir ===")
        code, out, err = run(prompt("s1"), home)
        check("prompt passa (exit 0)", code == 0, err)
        check("sem systemMessage", system_message(out) == "", repr(out))

        print("\n=== o log continua a registar todas ===")
        check("duas degradações no log", degraded_count(home) == 2, str(degraded_count(home)))

        print("\n=== outra sessão avisa de novo ===")
        _, out, _ = run(prompt("s2"), home)
        check("sessão s2 recebe o aviso", bool(system_message(out)), repr(out))

        print("\n=== a falha continua 30 min depois: avisa de novo ===")
        marker = home / ".cache" / "guard-rail" / "degraded-s1"
        check("marcador da sessão existe", marker.is_file(), str(marker))
        if marker.is_file():
            old = time.time() - 31 * 60
            os.utime(marker, (old, old))
        _, out, _ = run(prompt("s1"), home)
        check("sessão s1 recebe o aviso outra vez", bool(system_message(out)), repr(out))


if __name__ == "__main__":
    test_payload()
    test_visible_warning()
    print(f"\n{results['pass']} ok, {results['fail']} falhas")
    sys.exit(1 if results["fail"] else 0)
