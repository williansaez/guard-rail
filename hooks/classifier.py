"""
Camada residual: classificacao por LLM local (Ollama).

So corre quando a regex nao decidiu sozinha. Serve para o que digito de
controlo nao apanha: nomes de pessoas soltos no texto, moradas mal formatadas,
descricoes de saude, relacoes laborais.

Saida limitada a JSON curto e num_predict baixo — o custo aqui e latencia em
todas as mensagens, por isso o modelo nunca reescreve texto, so classifica.
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import json
import urllib.error
import urllib.request

SYSTEM = """Es um classificador de privacidade. Analisas um texto e decides se contem dados pessoais na acepcao da LGPD (Brasil) ou do RGPD (Portugal).

ALTO = identifica ou permite identificar uma PESSOA SINGULAR:
nome proprio de pessoa real, morada, contacto pessoal, dados de saude,
situacao financeira pessoal, relacao laboral nominal, identificadores civis.

MEDIO = identifica uma EMPRESA cliente ou dado comercial sensivel,
sem identificar pessoa singular.

NENHUM = apenas tecnica: codigo, identificadores de sistema, numeros de
documento, ordens de compra, transportes, tabelas, mensagens de erro,
nomes de produtos de software, nomes de fornecedores de tecnologia.

Nomes de tecnologia (SAP, Fiori, ABAP, Ollama, Qwen, Notion) NAO sao pessoas.
Marcadores <ID> ja foram anonimizados: ignora-os.

Responde APENAS com JSON: {"nivel":"ALTO|MEDIO|NENHUM","achados":["..."]}
Maximo 3 achados, cada um com no maximo 8 palavras."""


def classify(
    text: str,
    model: str = "qwen3.5:9b",
    host: str = "http://localhost:11434",
    timeout: int = 8,
    keep_alive: str = "30m",
) -> tuple[str, list[str], str | None]:
    """
    Devolve (nivel, achados, erro).

    Se `erro` nao for None, a classificacao falhou e o chamador decide
    se abre ou fecha o portao.
    """
    payload = {
        "model": model,
        "system": SYSTEM,
        # Delimitadores: o conteudo e dado a classificar, nunca instrucao.
        "prompt": f"<texto>\n{text}\n</texto>",
        "stream": False,
        "format": "json",
        "keep_alive": keep_alive,
        "options": {
            "num_predict": 128,
            "temperature": 0,
            "top_p": 0.1,
        },
    }

    req = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return "NENHUM", [], f"Ollama inacessivel ({exc.reason})"
    except TimeoutError:
        return "NENHUM", [], f"Ollama excedeu {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return "NENHUM", [], f"Ollama falhou ({type(exc).__name__})"

    try:
        verdict = json.loads(body.get("response", "{}"))
    except json.JSONDecodeError:
        return "NENHUM", [], "Resposta do modelo nao era JSON valido"

    level = str(verdict.get("nivel", "NENHUM")).upper()
    if level not in {"ALTO", "MEDIO", "NENHUM"}:
        level = "NENHUM"

    findings = verdict.get("achados") or []
    if not isinstance(findings, list):
        findings = []
    findings = [str(f)[:80] for f in findings[:3]]

    return level, findings, None


# ---------------------------------------------------------------------------
# Extracao de entidades, para o PostToolUse substituir por pseudonimos.
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM = """Extrais entidades pessoais de um texto, para serem anonimizadas.

Devolve APENAS os literais EXATOS como aparecem no texto, copiados caracter a
caracter. Nao corrijas, nao traduzas, nao reformates.

- "pessoas": nomes de pessoas singulares reais
- "moradas": moradas e enderecos postais

NAO incluas: nomes de empresas, produtos de software, tecnologias
(SAP, Fiori, ABAP, Ollama, Notion), nomes de tabelas, campos, colunas,
transacoes, ou qualquer identificador tecnico.
Rotulos ja anonimizados (EMAIL_001, CPF_002) devem ser ignorados.

Se nao houver nada, devolve listas vazias.
Responde so com JSON: {"pessoas":["..."],"moradas":["..."]}"""


def extract_entities(
    text: str,
    model: str = "qwen3.5:9b",
    host: str = "http://localhost:11434",
    timeout: int = 8,
    keep_alive: str = "30m",
) -> list[tuple[str, str]]:
    """Devolve [(prefixo_pseudonimo, literal), ...]. Lista vazia se falhar."""
    payload = {
        "model": model,
        "system": EXTRACT_SYSTEM,
        "prompt": f"<texto>\n{text}\n</texto>",
        "stream": False,
        "format": "json",
        "keep_alive": keep_alive,
        "options": {"num_predict": 256, "temperature": 0, "top_p": 0.1},
    }

    req = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        result = json.loads(body.get("response", "{}"))
    except Exception:  # noqa: BLE001
        return []

    out: list[tuple[str, str]] = []
    for prefix, key in (("PESSOA", "pessoas"), ("MORADA", "moradas")):
        values = result.get(key) or []
        if isinstance(values, list):
            out += [(prefix, str(v)) for v in values[:20] if isinstance(v, (str, int))]
    return out
