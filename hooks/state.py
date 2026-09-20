"""
Estado ligado/desligado do guard-rail.

O interruptor nao vive no config.json do plugin: esse ficheiro esta versionado
em git e e' substituido a cada actualizacao. Vive em ~/.config/guard-rail.json,
o ficheiro pessoal que os hooks ja leem DEPOIS do config.json e que por isso
sobrepoe qualquer chave.

Precedencia, da mais forte para a mais fraca:
  1. GUARD_RAIL_OFF=1        -- desliga so aquele processo
  2. ~/.config/guard-rail.json  -- o que `guard-rail off` escreve
  3. config.json do plugin
  4. ligado
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import json
import os
from pathlib import Path

USER_CONFIG = Path.home() / ".config" / "guard-rail.json"

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


def set_enabled(enabled: bool) -> Path:
    """
    Grava so a chave `enabled`, preservando o resto do ficheiro pessoal.
    Ler-modificar-escrever, nunca reescrever de raiz: o utilizador guarda
    ali os client_terms, e perde-los seria calar a proteccao que mais custou
    a configurar.
    """
    cfg = read_user_config()
    cfg["enabled"] = enabled
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(USER_CONFIG)
    return USER_CONFIG


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


SOURCE_LABEL = {
    SOURCE_ENV: "variável de ambiente GUARD_RAIL_OFF=1 (só neste processo)",
    SOURCE_USER: str(USER_CONFIG),
    SOURCE_PLUGIN: "config.json do plugin",
    SOURCE_DEFAULT: "por omissão",
}
