#!/usr/bin/env python3
"""
Testes do interruptor ligado/desligado.

O que interessa aqui não é o ficheiro em si: é que desligar desligue mesmo
(os hooks deixam de agir), que ligar volte a ligar, e que nenhuma das duas
coisas aconteça em silêncio — um plugin de privacidade desligado sem deixar
rasto é indistinguível de um plugin que falhou.

Corre com: python3 tests/test_state.py
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

PII_PROMPT = "Preciso de ajuda com o cliente joao.silva@exemplo.pt, CPF 529.982.247-25, por favor analisa."


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
    env.pop("GUARD_RAIL_OFF", None)
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


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)

        print("\n=== estado por omissão ===")
        code, out = cli(["status"], home)
        check("status arranca LIGADO", code == 0 and "LIGADO" in out and "DESLIGADO" not in out, out)

        print("\n=== guard-rail off ===")
        code, out = cli(["off"], home)
        check("off devolve 0", code == 0, out)
        check("off anuncia o que deixa de acontecer", "passam em claro" in out, out)
        cfg = user_config(home)
        check("escreve enabled=false no ficheiro pessoal", cfg.get("enabled") is False, str(cfg))

        mode = oct((home / ".config" / "guard-rail.json").stat().st_mode)[-3:]
        check(f"ficheiro com permissões 0600 (são {mode})", mode == "600")

        code, out = cli(["status"], home)
        check("status reflecte DESLIGADO", "DESLIGADO" in out, out)

        print("\n=== hooks desligados não agem ===")
        code, _, err = hook("guard.py", {"prompt": PII_PROMPT, "session_id": "t", "cwd": tmp}, home)
        check("guard.py deixa passar prompt com PII", code == 0 and "bloqueado" not in err.lower(), err)

        code, out, _ = hook(
            "redact.py",
            {"tool_name": "Read", "tool_response": "contacto: joao.silva@exemplo.pt", "session_id": "t", "cwd": tmp},
            home,
        )
        check("redact.py não reescreve o resultado", "updatedToolOutput" not in out, out)

        print("\n=== o arranque diz que está desligado ===")
        code, out, _ = hook("heartbeat.py", {"session_id": "t", "cwd": tmp}, home)
        check("SessionStart avisa no contexto", "DESLIGADO" in out, out)
        log = (home / ".cache" / "guard-rail" / "violations.jsonl").read_text(encoding="utf-8")
        check("evento armed regista estado=DESLIGADO", "estado=DESLIGADO" in log, log[-300:])

        print("\n=== desligar e ligar ficam no log ===")
        check("o off ficou registado como `toggled`", '"action": "toggled"' in log, log[:300])

        print("\n=== preserva o resto do ficheiro pessoal ===")
        path = home / ".config" / "guard-rail.json"
        path.write_text(json.dumps({"enabled": False, "client_terms": ["Acme"]}), encoding="utf-8")
        cli(["on"], home)
        cfg = user_config(home)
        check("client_terms sobrevive ao toggle", cfg.get("client_terms") == ["Acme"], str(cfg))
        check("enabled voltou a true", cfg.get("enabled") is True, str(cfg))

        print("\n=== ligado volta a proteger ===")
        code, _, err = hook("guard.py", {"prompt": PII_PROMPT, "session_id": "t", "cwd": tmp}, home)
        check("guard.py volta a bloquear PII", code == 2 and "bloqueado" in err.lower(), err)

        print("\n=== GUARD_RAIL_OFF sobrepõe-se ao ficheiro ===")
        code, out = cli(["status"], home, GUARD_RAIL_OFF="1")
        check("status diz que a origem é o ambiente", "DESLIGADO" in out and "GUARD_RAIL_OFF" in out, out)
        code, _, err = hook("guard.py", {"prompt": PII_PROMPT, "session_id": "t", "cwd": tmp}, home, GUARD_RAIL_OFF="1")
        check("guard.py obedece à variável de ambiente", code == 0, err)

        print("\n=== ficheiro pessoal corrompido não derruba nada ===")
        path.write_text("{isto não é json", encoding="utf-8")
        code, out = cli(["status"], home)
        check("status sobrevive a JSON inválido", code == 0 and "LIGADO" in out, out)
        code, _, err = hook("guard.py", {"prompt": PII_PROMPT, "session_id": "t", "cwd": tmp}, home)
        check("guard.py continua a proteger (fica ligado)", code == 2, err)

    print(f"\n{results['pass']} passaram, {results['fail']} falharam")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
