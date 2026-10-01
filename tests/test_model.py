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


def main() -> int:
    test_state_module()
    print(f"\n{results['pass']} passaram, {results['fail']} falharam")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
