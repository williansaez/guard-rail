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


def run(payload: dict, home: Path, **extra) -> tuple[int, str, str]:
    env = {**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    for var in ("GUARD_RAIL_OFF", "GUARD_RAIL_MODEL", "TYPESAFE_API_KEY", "CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY"):
        env.pop(var, None)
    env.update(extra)
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


import http.server
import threading


class _JevHandler(http.server.BaseHTTPRequestHandler):
    """Jev falso: devolve `answers` fixas e guarda tudo o que recebeu."""

    answers: dict = {}
    status: int = 200
    location = None  # str ou None; sem anotacao `X | Y`, que rebenta em 3.9
    received: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        type(self).received.append({"path": self.path, "auth": self.headers.get("Authorization", ""), "body": body})
        data = json.dumps({"answers": type(self).answers}).encode("utf-8")
        self.send_response(type(self).status)
        if type(self).location:
            self.send_header("Location", type(self).location)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silencio no output dos testes
        pass


def fake_jev(answers: dict, status: int = 200) -> tuple[http.server.HTTPServer, str]:
    _JevHandler.answers = answers
    _JevHandler.status = status
    _JevHandler.received = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _JevHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/v1/systemone"


def jev_config(home: Path, jev_url: str, **extra) -> None:
    """
    model=jev apontado ao Jev falso. O ollama_host aponta ao MESMO servidor:
    se algum hook falar com o Ollama, o pedido aparece em `received` com um
    campo `prompt`, e o teste apanha-o.
    """
    path = home / ".config" / "guard-rail.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {"model": "jev", "jev_host": jev_url, "ollama_host": jev_url.rsplit("/v1", 1)[0]}
    cfg.update(extra)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def events(home: Path) -> list[dict]:
    path = home / ".cache" / "guard-rail" / "violations.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def ollama_requests() -> list[dict]:
    return [r for r in _JevHandler.received if "prompt" in r["body"]]


def jev_requests() -> list[dict]:
    return [r for r in _JevHandler.received if "questions" in r["body"]]


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

    # O caminho Ollama usa urlopen; o Jev usa o seu opener sem redirects.
    original = classifier.urllib.request.urlopen
    original_jev = classifier._jev_open
    classifier.urllib.request.urlopen = fake_urlopen
    classifier._jev_open = fake_urlopen
    try:
        sent["result"] = fn()
    finally:
        classifier.urllib.request.urlopen = original
        classifier._jev_open = original_jev
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

    original = classifier._jev_open
    classifier._jev_open = no_network
    try:
        level, findings, err, meta = classifier.classify(CLEAN_PROMPT, model="jev")
    finally:
        classifier._jev_open = original
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
    # Sem `nivel` utilizavel nao e' "incerto" (que nao avisa): e' resposta
    # invalida, caminho degradado, que avisa uma vez por sessao.
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT, model="jev", api_key="k"), {"answers": {}})
    level, findings, err, meta = sent["result"]
    check("answers vazio: degradado, não incerto", err is not None and level == "NENHUM" and meta.get("uncertain") is False, f"{level} {err} {meta}")

    null_choice = {"answers": {"nivel": {"choice": None, "confidence": 0.9}, "pessoa": {"noul": 0.9}}}
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT, model="jev", api_key="k"), null_choice)
    level, findings, err, meta = sent["result"]
    check("choice nulo com confiança alta: degradado, nunca NENHUM silencioso", err is not None and meta.get("uncertain") is False, f"{level} {err} {meta}")

    foo_choice = {"answers": {"nivel": {"choice": "FOO", "confidence": 0.95}}}
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT, model="jev", api_key="k"), foo_choice)
    level, findings, err, meta = sent["result"]
    check("choice desconhecido: degradado", err is not None and meta.get("uncertain") is False, f"{level} {err} {meta}")

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

    original = classifier._jev_open
    classifier._jev_open = http_401
    try:
        level, findings, err, meta = classifier.classify(CLEAN_PROMPT, model="jev", api_key="k")
    finally:
        classifier._jev_open = original
    check("HTTP 401 vira erro com o código", err is not None and "401" in err, str(err))

    print("\n=== um redirect não leva a chave nem o texto a outro host ===")
    server, url = fake_jev({}, status=302)
    _JevHandler.location = "http://127.0.0.1:1/outro-sitio"
    try:
        level, findings, err, meta = classifier.classify(CLEAN_PROMPT, model="jev", api_key="k", jev_host=url, timeout=3)
    finally:
        _JevHandler.location = None
        server.shutdown()
    check("302 é recusado como erro HTTP", err is not None and "302" in err, str(err))
    check("só um pedido saiu, nenhum para o destino do redirect", len(_JevHandler.received) == 1, str(_JevHandler.received)[:200])

    level, findings, err, meta = classifier.classify(CLEAN_PROMPT, model="jev", api_key="k", jev_host="http://127.0.0.1:1/jev", timeout=2)
    check("ligação recusada vira 'Jev inacessivel'", err is not None and "inacess" in err, str(err))

    print("\n=== o caminho Ollama continua a devolver 4 valores ===")
    sent = capture_request(lambda: classifier.classify(CLEAN_PROMPT), {"response": '{"nivel":"NENHUM","achados":[]}'})
    level, findings, err, meta = sent["result"]
    check("backend ollama, sem confiança", meta == {"backend": "ollama", "confidence": None, "uncertain": False}, str(meta))

    print("\n=== extract_entities com jev não vai à rede ===")
    original_urlopen = classifier.urllib.request.urlopen
    classifier.urllib.request.urlopen = no_network
    classifier._jev_open = no_network
    try:
        out = classifier.extract_entities("a Maria Silva mora na Rua X", model="jev")
    finally:
        classifier.urllib.request.urlopen = original_urlopen
        classifier._jev_open = original
    check("devolve lista vazia", out == [], str(out))
    check("nenhuma chamada", called == [], str(called))


# ---------------------------------------------------------------------------
# 1c. guard.py com model=jev: etiquetas, incerteza, fail_closed, falhas
# ---------------------------------------------------------------------------

KEY = {"CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY": "chave-de-teste"}
MEDIO_PROMPT = "o cliente Northwind quer migrar a conta para a nova estrutura de centros de custo até março"


def test_guard_with_jev() -> None:
    print("\n=== guard.py com model=jev: ALTO confiante bloqueia com etiqueta (jev) ===")
    server, url = fake_jev(JEV_CONFIDENT["answers"])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jev_config(home, url)
            code, out, err = run(prompt("s1"), home, **KEY)
            check("bloqueia (exit 2)", code == 2, f"{code} {err}")
            check("achado etiquetado (jev)", "nome de pessoa (0.93) (jev)" in err, err)
            check("sem a etiqueta antiga (modelo local)", "modelo local" not in err, err)
            check("Bearer chegou ao servidor", bool(jev_requests()) and jev_requests()[0]["auth"] == "Bearer chave-de-teste", str(_JevHandler.received)[:200])
            check("Ollama nunca foi contactado", ollama_requests() == [], str(ollama_requests()))
            blocked = [e for e in events(home) if e["action"] == "blocked"]
            check("evento blocked com kind Jev", bool(blocked) and any(f["kind"] == "Jev" for f in blocked[-1]["findings"]), str(blocked[-1:]))
    finally:
        server.shutdown()

    print("\n=== incerto com fail_closed=false: passa e fica no log ===")
    low = json.loads(json.dumps(JEV_CONFIDENT["answers"]))
    low["nivel"]["confidence"] = 0.30
    server, url = fake_jev(low)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jev_config(home, url)
            code, out, err = run(prompt("s1"), home, **KEY)
            check("passa (exit 0)", code == 0, f"{code} {err}")
            check("sem systemMessage: incerto não é degradação", system_message(out) == "", repr(out))
            unc = [e for e in events(home) if e["action"] == "uncertain"]
            check("evento uncertain com a confiança na nota", bool(unc) and "0.30" in unc[-1].get("note", ""), str(unc))
            check("a nota diz para que nível o Jev pendia", bool(unc) and "nivel=ALTO" in unc[-1].get("note", ""), str(unc))
            check("nenhum evento degraded", degraded_count(home) == 0, str(degraded_count(home)))

            print("\n=== incerto com fail_closed=true: bloqueia a MEDIO ===")
            jev_config(home, url, fail_closed=True)
            code, out, err = run(prompt("s1"), home, **KEY)
            check("bloqueia (exit 2)", code == 2, f"{code} {err}")
            check("mensagem diz MEDIO", "(MEDIO)" in err, err)
            check("achado explica o fail_closed", "Jev incerto (fail_closed)" in err, err)
            check("achado mostra confiança e nível", "0.30" in err and "ALTO" in err, err)
            check("!ok continua a destrancar", run({**prompt("s1"), "prompt": "!ok " + CLEAN_PROMPT}, home, **KEY)[0] == 0)

            print("\n=== incerto nunca baixa o nível que a regex já deu ===")
            jev_config(home, url, fail_closed=True, client_terms=["Northwind"])
            code, out, err = run({**prompt("s1"), "prompt": MEDIO_PROMPT}, home, **KEY)
            check("MEDIO da regex mantém-se e bloqueia", code == 2 and "(MEDIO)" in err, err)
    finally:
        server.shutdown()

    print("\n=== model=jev sem chave: degradado, aviso visível, Ollama intocado ===")
    server, url = fake_jev(JEV_CONFIDENT["answers"])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jev_config(home, url)
            code, out, err = run(prompt("s1"), home)  # sem KEY
            check("passa (exit 0)", code == 0, f"{code} {err}")
            msg = system_message(out)
            check("aviso diz que falta a chave e ficou só a regex", "chave" in msg and "regex" in msg, msg)
            check("evento degraded", degraded_count(home) == 1, str(degraded_count(home)))
            check("nem Jev nem Ollama contactados", _JevHandler.received == [], str(_JevHandler.received)[:200])

            print("\n=== GUARD_RAIL_MODEL=jev no ambiente também conta ===")
            (home / ".config" / "guard-rail.json").write_text(json.dumps({"jev_host": url, "ollama_host": url.rsplit("/v1", 1)[0]}), encoding="utf-8")
            code, out, err = run(prompt("s2"), home, GUARD_RAIL_MODEL="jev")
            check("degradado por falta de chave, não foi ao Ollama", degraded_count(home) == 2 and ollama_requests() == [], f"{degraded_count(home)} {ollama_requests()}")
    finally:
        server.shutdown()

    print("\n=== ALTO confiante sem nenhum noul acima de 0.5: o bloqueio diz quem decidiu ===")
    bare = {"nivel": {"choice": "ALTO", "confidence": 0.97}, "pessoa": {"noul": 0.4}, "morada": {"noul": 0.1}, "saude": {"noul": 0.1}, "cliente": {"noul": 0.1}}
    server, url = fake_jev(bare)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jev_config(home, url)
            code, out, err = run(prompt("s1"), home, **KEY)
            check("bloqueia (exit 2)", code == 2, f"{code} {err}")
            check("sem '(sem detalhe)'", "(sem detalhe)" not in err, err)
            check("achado sintético nomeia nível e backend", "nível ALTO (jev)" in err, err)
            blocked = [e for e in events(home) if e["action"] == "blocked"]
            check("evento blocked com um achado Jev", bool(blocked) and blocked[-1].get("total", 0) >= 1 and any(f["kind"] == "Jev" for f in blocked[-1].get("findings", [])), str(blocked[-1:]))
    finally:
        server.shutdown()

    print("\n=== HTTP 401: degradado como o Ollama em baixo ===")
    server, url = fake_jev({}, status=401)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jev_config(home, url)
            code, out, err = run(prompt("s1"), home, **KEY)
            check("passa (exit 0)", code == 0, f"{code} {err}")
            notes = [e.get("note", "") for e in events(home) if e["action"] == "degraded"]
            check("nota do degraded tem o 401", any("401" in n for n in notes), str(notes))
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# 1d. redact.py e heartbeat.py com model=jev
# ---------------------------------------------------------------------------

def run_hook(script: str, payload: dict, home: Path, **extra) -> tuple[int, str, str]:
    env = {**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    for var in ("GUARD_RAIL_OFF", "GUARD_RAIL_MODEL", "TYPESAFE_API_KEY", "CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY"):
        env.pop(var, None)
    env.update(extra)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_redact_and_heartbeat_with_jev() -> None:
    print("\n=== redact.py com model=jev: extração desligada, Ollama intocado ===")
    server, url = fake_jev(JEV_CONFIDENT["answers"])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jev_config(home, url, llm_on_tool_output=True, llm_tool_matchers=["Read"])
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
                "tool_response": "responsável: Tomás Alvarenga, contacto joao.silva@exemplo.pt",
                "session_id": "s1",
                "cwd": tmp,
            }
            code, out, err = run_hook("redact.py", payload, home, **KEY)
            check("exit 0", code == 0, err)
            check("a regex continua a redigir o email", "EMAIL_001" in out, out[:300])
            check("nenhum pedido ao Ollama nem ao Jev", _JevHandler.received == [], str(_JevHandler.received)[:200])
            check("sem evento degraded", degraded_count(home) == 0, str(degraded_count(home)))

            print("\n=== GUARD_RAIL_MODEL=jev no ambiente desliga a extração na mesma ===")
            (home / ".config" / "guard-rail.json").write_text(
                json.dumps({"ollama_host": url.rsplit("/v1", 1)[0], "llm_on_tool_output": True, "llm_tool_matchers": ["Read"]}),
                encoding="utf-8",
            )
            code, out, err = run_hook("redact.py", payload, home, GUARD_RAIL_MODEL="jev", **KEY)
            check("nenhum pedido", _JevHandler.received == [], str(_JevHandler.received)[:200])
    finally:
        server.shutdown()

    print("\n=== heartbeat.py regista o modelo ===")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        code, out, err = run_hook("heartbeat.py", {"session_id": "s1", "cwd": tmp}, home)
        armed = [e for e in events(home) if e["action"] == "armed"]
        check("armed por omissão diz model=qwen3.5:9b", bool(armed) and "model=qwen3.5:9b" in armed[-1]["note"], str(armed[-1:]))
        check("sem aviso no contexto", out.strip() == "", repr(out))

        (home / ".config" / "guard-rail.json").parent.mkdir(parents=True, exist_ok=True)
        (home / ".config" / "guard-rail.json").write_text(json.dumps({"model": "jev"}), encoding="utf-8")
        code, out, err = run_hook("heartbeat.py", {"session_id": "s2", "cwd": tmp}, home)
        armed = [e for e in events(home) if e["action"] == "armed"]
        check("armed diz model=jev", "model=jev" in armed[-1]["note"], str(armed[-1:]))
        check("jev sem chave: uma linha no contexto", "model=jev" in out and "chave" in out, repr(out))

        code, out, err = run_hook("heartbeat.py", {"session_id": "s3", "cwd": tmp}, home, **KEY)
        check("jev com chave: silêncio", out.strip() == "", repr(out))


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
    test_guard_with_jev()
    test_redact_and_heartbeat_with_jev()
    test_visible_warning()
    print(f"\n{results['pass']} ok, {results['fail']} falhas")
    sys.exit(1 if results["fail"] else 0)
