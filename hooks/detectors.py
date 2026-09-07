"""
Camada deterministica de deteccao de dados pessoais (LGPD / RGPD).

Devolve SPANS posicionais, nao so um veredicto — e isso que permite ao
PostToolUse substituir o valor real por um pseudonimo em vez de bloquear.

Estrategia: alta precisao. Todo detector numerico valida digito de controlo.
Falso positivo aqui e caro de duas formas: bloqueia o utilizador a toda a hora,
e corrompe resultados de query ao trocar numeros de documento por pseudonimos.
"""

# Anotacoes preguicosas: mantem compatibilidade com o Python 3.9 que
# vem no macOS. Sem isto, `list[str] | None` e' SyntaxError no arranque.
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Allowlist: identificadores de sistema.
# Nao sao redigidos (o Claude precisa deles) e nao podem ser confundidos
# com PII — por isso os seus spans ficam "protegidos".
# ---------------------------------------------------------------------------

ALLOWLIST = [
    # Transporte SAP: XS4K903815
    re.compile(r"\b[A-Z][A-Z0-9]{2}K\d{6}\b"),
    # Documento / ordem de compra / fornecedor: 10 digitos exatos.
    # Ver NOTA-COLISAO no README.
    re.compile(r"\b\d{10}\b"),
    # Objeto ABAP no espaco de nomes do cliente
    re.compile(r"\b(?:Z|Y)[A-Z0-9_]{2,29}\b"),
    # Ticket
    re.compile(r"\bTKT-\d+\b"),
    # Datas ISO — nao sao data de nascimento sem contexto
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
]


def protected_spans(text: str) -> list[tuple[int, int]]:
    """Intervalos que representam identificadores de sistema."""
    spans: list[tuple[int, int]] = []
    for pattern in ALLOWLIST:
        spans += [m.span() for m in pattern.finditer(text)]
    return spans


def mask_allowlist(text: str) -> str:
    """Versao textual, usada pelo classificador LLM."""
    for pattern in ALLOWLIST:
        text = pattern.sub("<ID>", text)
    return text


# ---------------------------------------------------------------------------
# Validadores de digito de controlo
# ---------------------------------------------------------------------------


def _digits(value: str) -> list[int]:
    return [int(c) for c in value if c.isdigit()]


def valid_cpf(value: str) -> bool:
    d = _digits(value)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    dv1 = (sum(d[i] * (10 - i) for i in range(9)) * 10 % 11) % 10
    dv2 = (sum(d[i] * (11 - i) for i in range(10)) * 10 % 11) % 10
    return dv1 == d[9] and dv2 == d[10]


def valid_cnpj(value: str) -> bool:
    d = _digits(value)
    if len(d) != 14 or len(set(d)) == 1:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    r1 = sum(d[i] * w1[i] for i in range(12)) % 11
    dv1 = 0 if r1 < 2 else 11 - r1
    r2 = sum(d[i] * w2[i] for i in range(13)) % 11
    dv2 = 0 if r2 < 2 else 11 - r2
    return dv1 == d[12] and dv2 == d[13]


_NIF_PREFIXES = ("1", "2", "3", "5", "6", "8")
_NIF_PREFIXES_2 = ("45", "70", "71", "72", "74", "75", "77", "79", "90", "91", "98", "99")


def valid_nif(value: str) -> bool:
    d = _digits(value)
    if len(d) != 9 or len(set(d)) == 1:
        return False
    s = "".join(str(x) for x in d)
    if not (s[0] in _NIF_PREFIXES or s[:2] in _NIF_PREFIXES_2):
        return False
    check = sum(d[i] * (9 - i) for i in range(8)) % 11
    dv = 0 if check < 2 else 11 - check
    return dv == d[8]


def valid_luhn(value: str) -> bool:
    d = _digits(value)
    if not 13 <= len(d) <= 19:
        return False
    total, parity = 0, len(d) % 2
    for i, n in enumerate(d):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def valid_iban(value: str) -> bool:
    s = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    return int(numeric) % 97 == 1


# ---------------------------------------------------------------------------
# Detectores. `prefix` e o que aparece no pseudonimo (CPF_001, EMAIL_002...)
# ---------------------------------------------------------------------------

DETECTORS = [
    ("CPF", "CPF", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), valid_cpf, "ALTO"),
    (
        "CNPJ",
        "CNPJ",
        re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
        valid_cnpj,
        "MEDIO",
    ),
    ("NIF/NIPC (PT)", "NIF", re.compile(r"\b\d{9}\b"), valid_nif, "ALTO"),
    (
        "IBAN",
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}[\s-]?(?:[A-Z0-9][\s-]?){10,30}\b"),
        valid_iban,
        "ALTO",
    ),
    (
        "Cartao de pagamento",
        "CARTAO",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        valid_luhn,
        "ALTO",
    ),
    (
        "Email",
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        None,
        "ALTO",
    ),
    (
        "Telefone (BR)",
        "TEL",
        re.compile(r"(?:\+55[\s-]?)?\(\d{2}\)[\s-]?9?\d{4}[-\s]?\d{4}\b"),
        None,
        "ALTO",
    ),
    (
        "Telefone (PT)",
        "TEL",
        re.compile(r"\+351[\s-]?[239]\d{2}[\s-]?\d{3}[\s-]?\d{3}\b"),
        None,
        "ALTO",
    ),
    (
        "Cartao de Cidadao (PT)",
        "CC",
        re.compile(r"\b\d{8}[\s-]?\d[\s-]?[A-Z]{2}\d\b"),
        None,
        "ALTO",
    ),
    (
        "Data de nascimento",
        "NASC",
        re.compile(
            r"\b(?:nasc(?:imento|\.)?|d\.?o\.?b\.?|data de nasc\w*)\s*:?\s*"
            r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            re.IGNORECASE,
        ),
        None,
        "ALTO",
    ),
    (
        "Morada / endereco",
        "MORADA",
        re.compile(
            r"\b(?:rua|avenida|av\.|travessa|largo|praceta|alameda|estrada)\s+"
            r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w\sáéíóúâêôãõç.]{3,40},?\s*(?:n[.º°]?\s*)?\d{1,5}\b",
            re.IGNORECASE,
        ),
        None,
        "ALTO",
    ),
    ("Codigo postal (PT)", "CP", re.compile(r"\b\d{4}-\d{3}\b"), None, "MEDIO"),
]

LEVEL_ORDER = {"NENHUM": 0, "MEDIO": 1, "ALTO": 2}


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    kind: str  # nome legivel, para a mensagem de bloqueio
    prefix: str  # prefixo do pseudonimo
    value: str
    level: str


def find_pii(text: str, client_terms: list[str] | None = None) -> list[Finding]:
    """
    Todos os achados, com posicao. Ordenados por posicao.

    Achados que se sobrepoem a identificadores de sistema sao descartados —
    e isso que impede o numero de documento SAP de virar pseudonimo.

    A ocupacao e marcada num bytearray em vez de uma lista de intervalos:
    comparar cada achado contra a lista crescente era quadratico e custava
    ~550 ms num resultado de 200 KB. Assim e linear no tamanho do texto.
    """
    occupied = bytearray(len(text))
    for start, end in protected_spans(text):
        occupied[start:end] = b"\x01" * (end - start)

    def take(start: int, end: int) -> bool:
        if b"\x01" in occupied[start:end]:
            return False
        occupied[start:end] = b"\x01" * (end - start)
        return True

    found: list[Finding] = []

    for kind, prefix, pattern, validator, level in DETECTORS:
        for match in pattern.finditer(text):
            start, end = match.span()
            raw = match.group(0)
            if validator and not validator(raw):
                continue
            if not take(start, end):
                continue
            found.append(Finding(start, end, kind, prefix, raw, level))

    for term in client_terms or []:
        for match in re.finditer(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
            start, end = match.span()
            if not take(start, end):
                continue
            found.append(
                Finding(start, end, "Nome de cliente", "EMPRESA", match.group(0), "MEDIO")
            )

    return sorted(found, key=lambda f: f.start)


def scan(text: str, client_terms: list[str] | None = None) -> tuple[str, list[str]]:
    """Veredicto agregado, para o bloqueio de prompt."""
    findings = find_pii(text, client_terms)
    level = "NENHUM"
    seen: set[str] = set()
    labels: list[str] = []

    for f in findings:
        if LEVEL_ORDER[f.level] > LEVEL_ORDER[level]:
            level = f.level
        if f.kind not in seen:
            seen.add(f.kind)
            labels.append(f"{f.kind}: {redact_preview(f.value)}")

    return level, labels


def redact_preview(value: str) -> str:
    """Mostra so o suficiente para o utilizador localizar o trecho."""
    clean = value.strip()
    if len(clean) <= 4:
        return "*" * len(clean)
    return f"{clean[:2]}{'*' * (len(clean) - 4)}{clean[-2:]}"


def max_level(a: str, b: str) -> str:
    return a if LEVEL_ORDER[a] >= LEVEL_ORDER[b] else b
