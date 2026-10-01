"""
Estado ligado/desligado do guard-rail, e qual o modelo escolhido.

Nenhum dos dois vive no config.json do plugin: esse ficheiro esta versionado
em git e e' substituido a cada actualizacao. Vivem em ~/.config/guard-rail.json,
o ficheiro pessoal que os hooks ja leem DEPOIS do config.json e que por isso
sobrepoe qualquer chave.

Precedencia, da mais forte para a mais fraca:
  1. GUARD_RAIL_OFF=1 / GUARD_RAIL_MODEL=x  -- so aquele processo
  2. ~/.config/guard-rail.json              -- o que a CLI escreve
  3. config.json do plugin
  4. ligado / qwen3.5:9b
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import json
import os
from pathlib import Path

USER_CONFIG = Path.home() / ".config" / "guard-rail.json"

# O valor de `model` que escolhe o backend cloud. Qualquer outro valor e'
# um nome de modelo Ollama.
JEV = "jev"
DEFAULT_MODEL = "qwen3.5:9b"

# De onde veio a decisao. Serve para o `status` e o `doctor` dizerem
# ao utilizador onde mexer para a mudar.
SOURCE_ENV = "env"
SOURCE_USER = "user"
SOURCE_PLUGIN = "plugin"
SOURCE_DEFAULT = "default"


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def read_user_config() -> dict:
    return _read_json(USER_CONFIG)


def _write_user_key(key: str, value) -> Path:
    """
    Grava so uma chave, preservando o resto do ficheiro pessoal.
    Ler-modificar-escrever, nunca reescrever de raiz: o utilizador guarda
    ali os client_terms, e perde-los seria calar a proteccao que mais custou
    a configurar.
    """
    cfg = read_user_config()
    cfg[key] = value
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(USER_CONFIG)
    return USER_CONFIG


def set_enabled(enabled: bool) -> Path:
    return _write_user_key("enabled", enabled)


def set_model(name: str) -> Path:
    return _write_user_key("model", name.strip())


def status(plugin_root: Path | None = None) -> tuple[bool, str]:
    """Devolve (ligado, origem_da_decisao)."""
    if os.environ.get("GUARD_RAIL_OFF") == "1":
        return False, SOURCE_ENV

    user = read_user_config()
    if "enabled" in user:
        return bool(user["enabled"]), SOURCE_USER

    if plugin_root is not None:
        plugin = _read_json(Path(plugin_root) / "config.json")
        if "enabled" in plugin:
            return bool(plugin["enabled"]), SOURCE_PLUGIN

    return True, SOURCE_DEFAULT


def _clean(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def model_status(plugin_root: Path | None = None) -> tuple[str, str]:
    """Devolve (modelo, origem_da_decisao). `jev` e' o backend cloud."""
    env = _clean(os.environ.get("GUARD_RAIL_MODEL"))
    if env:
        return env, SOURCE_ENV

    user = _clean(read_user_config().get("model"))
    if user:
        return user, SOURCE_USER

    if plugin_root is not None:
        plugin = _clean(_read_json(Path(plugin_root) / "config.json").get("model"))
        if plugin:
            return plugin, SOURCE_PLUGIN

    return DEFAULT_MODEL, SOURCE_DEFAULT


SOURCE_LABEL = {
    SOURCE_ENV: "variável de ambiente GUARD_RAIL_OFF=1 (só neste processo)",
    SOURCE_USER: str(USER_CONFIG),
    SOURCE_PLUGIN: "config.json do plugin",
    SOURCE_DEFAULT: "por omissão",
}

MODEL_SOURCE_LABEL = {
    SOURCE_ENV: "variável de ambiente GUARD_RAIL_MODEL (só neste processo)",
    SOURCE_USER: str(USER_CONFIG),
    SOURCE_PLUGIN: "config.json do plugin",
    SOURCE_DEFAULT: "por omissão",
}
