#!/usr/bin/env python3
"""
Testes da escolha do modelo: `guard-rail model`.

O que interessa: a precedência (ambiente > ficheiro pessoal > config do
plugin > omissão), que mudar de modelo não apague o resto do ficheiro
pessoal, e que escolher `jev` fique registado — porque a partir daí o texto
residual dos prompts sai da máquina.

Corre com: python3 tests/test_model.py
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


def check(desc: str, ok: bool, detail: str = "") -> None:
    if ok:
        results["pass"] += 1
        print(f"  ok   {desc}")
    else:
        results["fail"] += 1
        print(f"  FAIL {desc}")
        if detail:
            print(f"       {detail}")


def _env(home: Path, **extra) -> dict:
    env = {**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    for var in ("GUARD_RAIL_OFF", "GUARD_RAIL_MODEL", "TYPESAFE_API_KEY", "CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY"):
        env.pop(var, None)
    env.update(extra)
    return env


def cli(args: list, home: Path, **extra) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "guard-rail"), *args],
        capture_output=True,
        text=True,
        env=_env(home, **extra),
    )
    return proc.returncode, proc.stdout + proc.stderr


def hook(script: str, payload: dict, home: Path, **extra) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=_env(home, **extra),
    )
    return proc.returncode, proc.stdout, proc.stderr


def user_config(home: Path) -> dict:
    path = home / ".config" / "guard-rail.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def write_user_config(home: Path, data: dict) -> None:
    path = home / ".config" / "guard-rail.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def log_text(home: Path) -> str:
    path = home / ".cache" / "guard-rail" / "violations.jsonl"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_state_module() -> None:
    """Precedência em processo, com HOME e plugin_root temporários."""
    print("\n=== state.model_status: precedência ===")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        plugin = Path(tmp) / "plugin"
        home.mkdir()
        plugin.mkdir()
        os.environ["HOME"] = str(home)
        os.environ.pop("GUARD_RAIL_MODEL", None)
        import importlib
        import state
        importlib.reload(state)

        model, source = state.model_status(plugin)
        check("sem nada: default qwen3.5:9b", model == "qwen3.5:9b" and source == state.SOURCE_DEFAULT, f"{model} {source}")

        (plugin / "config.json").write_text(json.dumps({"model": "llama3:8b"}), encoding="utf-8")
        model, source = state.model_status(plugin)
        check("config do plugin vence o default", model == "llama3:8b" and source == state.SOURCE_PLUGIN, f"{model} {source}")

        write_user_config(home, {"enabled": True, "client_terms": ["Northwind"], "model": "qwen3.5:9b"})
        model, source = state.model_status(plugin)
        check("ficheiro pessoal vence o plugin", model == "qwen3.5:9b" and source == state.SOURCE_USER, f"{model} {source}")

        os.environ["GUARD_RAIL_MODEL"] = "jev"
        model, source = state.model_status(plugin)
        check("GUARD_RAIL_MODEL vence tudo", model == "jev" and source == state.SOURCE_ENV, f"{model} {source}")
        os.environ.pop("GUARD_RAIL_MODEL")

        print("\n=== state.set_model preserva o resto ===")
        path = state.set_model("jev")
        cfg = user_config(home)
        check("escreve model=jev", cfg.get("model") == "jev", str(cfg))
        check("client_terms sobrevive", cfg.get("client_terms") == ["Northwind"], str(cfg))
        check("enabled sobrevive", cfg.get("enabled") is True, str(cfg))
        mode = oct(path.stat().st_mode)[-3:]
        check(f"ficheiro com permissões 0600 (são {mode})", mode == "600")

        state.set_model("qwen3.5:9b")
        cfg = user_config(home)
        check("volta a qwen3.5:9b e mantém o resto", cfg.get("model") == "qwen3.5:9b" and cfg.get("client_terms") == ["Northwind"], str(cfg))

        print("\n=== ficheiro pessoal corrompido ===")
        (home / ".config" / "guard-rail.json").write_text("{isto não é json", encoding="utf-8")
        model, source = state.model_status(plugin)
        check("JSON inválido cai para o plugin", model == "llama3:8b" and source == state.SOURCE_PLUGIN, f"{model} {source}")

        write_user_config(home, {"model": "   "})
        model, source = state.model_status(plugin)
        check("model vazio no ficheiro é ignorado", model == "llama3:8b", f"{model} {source}")


def test_cli() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        # Ollama inacessivel de imediato, sem timeout.
        write_user_config(home, {"ollama_host": "http://127.0.0.1:1"})

        print("\n=== guard-rail model sem argumento ===")
        code, out = cli(["model"], home)
        check("exit 0 com Ollama em baixo e sem chave", code == 0, out)
        check("mostra o modelo activo", "qwen3.5:9b" in out, out)
        # O config.json do plugin envia `model`, por isso a origem e' ele, nao o default.
        check("diz a origem", "config.json do plugin" in out, out)
        check("lista jev como cloud", "jev" in out and "sai da máquina" in out, out)
        check("jev marcado sem chave", "sem chave" in out, out)
        check("diz que o Ollama não responde", "Ollama" in out and "não responde" in out, out)

        print("\n=== guard-rail model jev ===")
        code, out = cli(["model", "jev"], home)
        check("exit 0", code == 0, out)
        check("grava model=jev no ficheiro pessoal", user_config(home).get("model") == "jev", str(user_config(home)))
        check("preserva ollama_host", user_config(home).get("ollama_host") == "http://127.0.0.1:1", str(user_config(home)))
        check("avisa que o texto residual sai da máquina", "sai da máquina" in out, out)
        check("avisa que falta a chave", "chave" in out, out)
        log = log_text(home)
        check("evento toggled com a transição", '"action": "toggled"' in log and "model: qwen3.5:9b → jev" in log, log[-400:])

        code, out = cli(["model"], home)
        check("status agora diz jev", "jev" in out.split("Disponíveis")[0], out)

        print("\n=== guard-rail model com chave no ambiente ===")
        code, out = cli(["model"], home, CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY="segredo-xyz-123")
        check("jev sem a marca 'sem chave'", "sem chave" not in out, out)
        check("a chave nunca aparece no output", "segredo-xyz-123" not in out, out)

        print("\n=== voltar a um modelo Ollama que o Ollama não lista ===")
        code, out = cli(["model", "llama3:8b"], home)
        check("exit 0", code == 0, out)
        check("grava na mesma", user_config(home).get("model") == "llama3:8b", str(user_config(home)))
        check("avisa que não está no Ollama", "não" in out and "Ollama" in out, out)

        print("\n=== GUARD_RAIL_MODEL no ambiente ===")
        code, out = cli(["model"], home, GUARD_RAIL_MODEL="jev")
        check("origem é a variável de ambiente", "GUARD_RAIL_MODEL" in out, out)

        print("\n=== argumento vazio ou inválido ===")
        code, out = cli(["model", "   "], home)
        check("nome vazio é recusado", code == 1, out)

        print("\n=== doctor com jev sem chave ===")
        write_user_config(home, {"ollama_host": "http://127.0.0.1:1", "model": "jev", "llm_on_tool_output": True})
        code, out = cli(["doctor"], home)
        check("secção Modelo", "── Modelo ──" in out, out)
        check("diz jev sem chave como problema", "jev" in out and "sem chave" in out and code == 1, out)
        check("diz que a extração em output está desligada", "extração" in out and "desligada" in out, out)

        print("\n=== doctor com qwen e Ollama em baixo: aviso, não problema ===")
        write_user_config(home, {"ollama_host": "http://127.0.0.1:1"})
        code, out = cli(["doctor"], home)
        check("Ollama não responde é aviso", "Ollama não responde" in out, out)


def main() -> int:
    test_state_module()
    test_cli()
    print(f"\n{results['pass']} passaram, {results['fail']} falharam")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
