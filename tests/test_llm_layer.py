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


def capture_request(fn, body: dict) -> dict:
    """Como capture_payload, mas devolve também os headers e serve `body` tal qual."""
    import classifier

    sent: dict = {}

    def fake_urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data.decode("utf-8"))
        sent["headers"] = {k.lower(): v for k, v in req.header_items()}
        sent["url"] = req.full_url
        return _FakeResponse(body)

    original = classifier.urllib.request.urlopen
    classifier.urllib.request.urlopen = fake_urlopen
    try:
        sent["result"] = fn()
    finally:
        classifier.urllib.request.urlopen = original
    return sent


JEV_CONFIDENT = {
    "answers": {
        "nivel": {"choice": "ALTO", "confidence": 0.97},
        "pessoa": {"noul": 0.93},
        "morada": {"noul": 0.02},
        "saude": {"noul": 0.01},
        "cliente": {"noul": 0.10},
    }
}


# ---------------------------------------------------------------------------
# 1b. Backend Jev: o pedido, a chave, a incerteza, as falhas
# ---------------------------------------------------------------------------

def test_jev_client() -> None:
    import classifier

    # Uma chave real no ambiente de quem corre os testes mudaria o resultado.
    os.environ.pop("CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY", None)
    os.environ.pop("TYPESAFE_API_KEY", None)

    print("\n=== classify com model=jev fala com o Jev, não com o Ollama ===")
    os.environ["TYPESAFE_API_KEY"] = "chave-de-teste"
    try:
        sent = capture_request(
            lambda: classifier.classify(CLEAN_PROMPT, model="jev", jev_host="http://127.0.0.1:9/jev"),
            JEV_CONFIDENT,
        )
    finally:
        os.environ.pop("TYPESAFE_API_KEY", None)
    level, findings, err, meta = sent["result"]
    check("vai para jev_host", sent["url"] == "http://127.0.0.1:9/jev", sent["url"])
    check("header Bearer com a chave", sent["headers"].get("authorization") == "Bearer chave-de-teste", str(sent["headers"]))
    payload = sent["payload"]
    check("state com delimitadores <texto>", payload.get("state", "").startswith("<texto>\n") and payload["state"].endswith("\n</texto>"), repr(payload.get("state"))[:80])
    check("modelo jev-latest por omissão", payload.get("model") == "jev-latest", str(payload.get("model")))
    check("cinco perguntas: nivel + 4 noul", set(payload.get("questions", {})) == {"nivel", "pessoa", "morada", "saude", "cliente"}, str(list(payload.get("questions", {}))))
    check("nivel é choice com ALTO/MEDIO/NENHUM", set(payload["questions"]["nivel"].get("criteria", {})) == {"ALTO", "MEDIO", "NENHUM"}, str(payload["questions"]["nivel"]))
    check("não envia campos do Ollama", "prompt" not in payload and "think" not in payload, str(list(payload)))
    check("nível ALTO", level == "ALTO", level)
    check("sem erro", err is None, str(err))
    check("meta diz backend jev e confiança", meta.get("backend") == "jev" and meta.get("confidence") == 0.97 and meta.get("uncertain") is False, str(meta))
    check("achado é categoria com probabilidade, sem literal", findings == ["nome de pessoa (0.93)"], str(findings))

    print("\n=== a chave vem primeiro da opção do plugin ===")
    os.environ["CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY"] = "do-plugin"
    os.environ["TYPESAFE_API_KEY"] = "do-ambiente"
    try:
        check("CLAUDE_PLUGIN_OPTION_ vence", classifier.jev_api_key() == "do-plugin", str(classifier.jev_api_key()))
        os.environ.pop("CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY")
        check("TYPESAFE_API_KEY como fallback", classifier.jev_api_key() == "do-ambiente", str(classifier.jev_api_key()))
        os.environ.pop("TYPESAFE_API_KEY")
        check("sem nenhuma: None", classifier.jev_api_key() is None, str(classifier.jev_api_key()))
    finally:
        os.environ.pop("CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY", None)
        os.environ.pop("TYPESAFE_API_KEY", None)

    print("\n=== sem chave: erro, sem rede ===")
    called = []

    def no_network(req, timeout=None):
        called.append(req.full_url)
        raise AssertionError("não devia ter chamado a rede")

    original = classifier.urllib.request.urlopen
    classifier.urllib.request.urlopen = no_network
    try:
        level, findings, err, meta = classifier.classify(CLEAN_PROMPT, model="jev")
    finally:
        classifier.urllib.request.urlopen = original
    check("erro diz que falta a chave", err is not None and "chave" in err and "Jev" in err, str(err))
    check("nível NENHUM", level == "NENHUM", level)
    check("nenhuma chamada de rede", called == [], str(called))

    print("\n=== confiança baixa: incerto ===")
    low = json.loads(json.dumps(JEV_CONFIDENT))
    low["answers"]["nivel"]["confidence"] = 0.30
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT, model="jev", api_key="k"), low)
    level, findings, err, meta = sent["result"]
    check("err começa por 'Jev incerto'", err is not None and err.startswith("Jev incerto"), str(err))
    check("meta.uncertain é True", meta.get("uncertain") is True, str(meta))
    check("o nível que daria vem na mesma", level == "ALTO", level)
    check("confiança no meta", meta.get("confidence") == 0.3, str(meta))

    print("\n=== respostas estranhas não rebentam ===")
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT, model="jev", api_key="k"), {"answers": {}})
    level, findings, err, meta = sent["result"]
    check("answers vazio: incerto, não excepção", err is not None and level == "NENHUM", f"{level} {err}")

    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT, model="jev", api_key="k"), {"nada": 1})
    level, findings, err, meta = sent["result"]
    check("sem answers: erro de JSON inválido", err is not None and "JSON" in err, str(err))

    weird = {"answers": {"nivel": {"choice": "ALTO", "confidence": "muito"}, "pessoa": {"noul": "sim"}}}
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT, model="jev", api_key="k"), weird)
    level, findings, err, meta = sent["result"]
    check("confiança não numérica: tratada como 0, incerto", meta.get("uncertain") is True and findings == [], f"{meta} {findings}")

    print("\n=== erros HTTP e de rede ===")
    import urllib.error

    def http_401(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    original = classifier.urllib.request.urlopen
    classifier.urllib.request.urlopen = http_401
    try:
        level, findings, err, meta = classifier.classify(CLEAN_PROMPT, model="jev", api_key="k")
    finally:
        classifier.urllib.request.urlopen = original
    check("HTTP 401 vira erro com o código", err is not None and "401" in err, str(err))

    level, findings, err, meta = classifier.classify(CLEAN_PROMPT, model="jev", api_key="k", jev_host="http://127.0.0.1:1/jev", timeout=2)
    check("ligação recusada vira 'Jev inacessivel'", err is not None and "inacess" in err, str(err))

    print("\n=== o caminho Ollama continua a devolver 4 valores ===")
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT), {"response": '{"nivel":"NENHUM","achados":[]}'})
    level, findings, err, meta = sent["result"]
    check("backend ollama, sem confiança", meta == {"backend": "ollama", "confidence": None, "uncertain": False}, str(meta))

    print("\n=== extract_entities com jev não vai à rede ===")
    classifier.urllib.request.urlopen = no_network
    try:
        out = classifier.extract_entities("a Maria Silva mora na Rua X", model="jev")
    finally:
        classifier.urllib.request.urlopen = original
    check("devolve lista vazia", out == [], str(out))
    check("nenhuma chamada", called == [], str(called))


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
    test_jev_client()
    test_visible_warning()
    print(f"\n{results['pass']} ok, {results['fail']} falhas")
    sys.exit(1 if results["fail"] else 0)
