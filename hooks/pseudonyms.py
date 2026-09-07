"""
Mapa de pseudonimos, estavel dentro da sessao e reversivel.

Porque estavel: se o mesmo email virar EMAIL_001 em toda a sessao, o Claude
consegue perceber que duas linhas de uma query sao da mesma pessoa e raciocinar
sobre isso. Pseudonimos aleatorios por ocorrencia destruiriam essa relacao e
tornariam os resultados inuteis.

Porque reversivel: quando o Claude responde "corrige o registo de PESSOA_003",
tu precisas de saber quem e. O mapa vive so em disco local, com 0600.
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "guard-rail"
PSEUDONYM_RE = re.compile(r"\b([A-Z]{2,10})_(\d{3,})\b")


class PseudonymMap:
    def __init__(self, session_id: str):
        # Nunca deixar o session_id decidir o caminho no disco.
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "default")[:64]
        self.path = CACHE_DIR / f"map-{safe}.json"
        self._forward: dict[str, str] = {}  # "KIND\x00valor" -> pseudonimo
        self._reverse: dict[str, str] = {}  # pseudonimo -> valor
        self._counters: dict[str, int] = {}
        self._dirty = False
        self._load()

    # -- persistencia -------------------------------------------------------

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self._forward = data.get("forward", {})
        self._reverse = data.get("reverse", {})
        self._counters = data.get("counters", {})

    def save(self) -> None:
        if not self._dirty:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "forward": self._forward,
            "reverse": self._reverse,
            "counters": self._counters,
        }
        # Escrita atomica: um hook interrompido a meio nao corrompe o mapa.
        fd, tmp = tempfile.mkstemp(dir=str(CACHE_DIR), prefix=".map-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._dirty = False

    # -- uso ----------------------------------------------------------------

    def pseudonym_for(self, prefix: str, value: str) -> str:
        """Devolve sempre o mesmo rotulo para o mesmo valor."""
        key = f"{prefix}\x00{self._normalise(value)}"
        if key in self._forward:
            return self._forward[key]

        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        label = f"{prefix}_{self._counters[prefix]:03d}"
        self._forward[key] = label
        self._reverse[label] = value
        self._dirty = True
        return label

    def resolve(self, label: str) -> str | None:
        return self._reverse.get(label.upper())

    def entries(self) -> list[tuple[str, str]]:
        return sorted(self._reverse.items(), key=_sort_label)

    def restore(self, text: str) -> str:
        """Troca pseudonimos pelos valores reais. Para o comando guard-rail map."""
        return PSEUDONYM_RE.sub(
            lambda m: self._reverse.get(m.group(0), m.group(0)),
            text,
        )

    @staticmethod
    def _normalise(value: str) -> str:
        """
        Colapsa formatacoes diferentes do mesmo dado, para 529.982.247-25 e
        52998224725 partilharem pseudonimo.
        """
        stripped = re.sub(r"[\s.\-/()]", "", value)
        return stripped.lower() if stripped else value.lower()


def _sort_label(item: tuple[str, str]) -> tuple[str, int]:
    match = PSEUDONYM_RE.match(item[0])
    return (match.group(1), int(match.group(2))) if match else (item[0], 0)
