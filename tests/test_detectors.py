#!/usr/bin/env python3
"""Suite de casos. Corre com: python3 tests/test_detectors.py"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

import detectors  # noqa: E402

# (descricao, texto, nivel_esperado)
CASES = [
    # --- Devem PASSAR: trabalho tecnico SAP puro -----------------------------
    (
        "SAP: fatura + fornecedor + PO + transporte",
        "A fatura 5105600787 do fornecedor 0010000006 referencia a PO "
        "4500001030. Transporte XS4K903815 ja foi libertado.",
        "NENHUM",
    ),
    (
        "SAP: tabela Z e ticket",
        "A tabela ZSD_SUP_INV_JOB tem linhas falhadas no TKT-20068.",
        "NENHUM",
    ),
    (
        "ABAP: codigo puro",
        "SELECT * FROM zsd_sup_inv_job WHERE status = 'A' INTO TABLE @DATA(lt).",
        "NENHUM",
    ),
    (
        "Numeros que nao sao documentos validos",
        "O job processou 1234567890 registos em 12345678901 milissegundos.",
        "NENHUM",
    ),
    # --- Devem BLOQUEAR em ALTO: pessoa singular -----------------------------
    ("CPF valido", "O CPF do titular e 529.982.247-25.", "ALTO"),
    ("CPF sem pontuacao", "titular 52998224725 confirmado", "ALTO"),
    ("NIF portugues valido", "NIF 501964843 associado a conta.", "ALTO"),
    ("Email", "Contactar joao.silva@empresa.pt sobre o assunto.", "ALTO"),
    ("Telefone BR formatado", "Ligar para (11) 98765-4321 hoje.", "ALTO"),
    ("Telefone PT", "O numero e +351 912 345 678.", "ALTO"),
    ("IBAN", "Transferir para GB82 WEST 1234 5698 7654 32.", "ALTO"),
    ("Cartao (Luhn valido)", "Cartao 4111 1111 1111 1111 expirado.", "ALTO"),
    ("Morada", "Mora na Rua das Flores, 128 em Lisboa.", "ALTO"),
    ("Data de nascimento", "Nascimento: 12/03/1985 conforme registo.", "ALTO"),
    # --- Devem BLOQUEAR em MEDIO: empresa ------------------------------------
    ("CNPJ valido", "CNPJ 11.222.333/0001-81 do cliente.", "MEDIO"),
    ("Nome de cliente configurado", "O sistema Northwind-TEST esta em baixo.", "MEDIO"),
    ("Codigo postal PT", "Entrega para 1050-123 na zona.", "MEDIO"),
    # --- Falsos positivos que a validacao deve matar -------------------------
    ("CPF com digito errado", "Referencia 529.982.247-99 no sistema.", "NENHUM"),
    ("CNPJ com digito errado", "Codigo 11.222.333/0001-99 invalido.", "NENHUM"),
    ("9 digitos que nao sao NIF", "O contador chegou a 111111111 unidades.", "NENHUM"),
    ("Cartao com Luhn invalido", "Sequencia 4111111111111112 no log.", "NENHUM"),
]

CLIENT_TERMS = ["Northwind"]


def run() -> int:
    passed = failed = 0
    durations = []

    for desc, text, expected in CASES:
        start = time.perf_counter()
        masked = detectors.mask_allowlist(text)
        level, findings = detectors.scan(masked, CLIENT_TERMS)
        durations.append((time.perf_counter() - start) * 1000)

        if level == expected:
            passed += 1
            print(f"  ok   {desc:42} -> {level}")
        else:
            failed += 1
            print(f"  FAIL {desc:42} -> {level} (esperado {expected})")
            print(f"       texto:   {text}")
            print(f"       mascara: {masked}")
            print(f"       achados: {findings}")

    print()
    print(f"{passed} passaram, {failed} falharam")
    print(
        f"latencia regex: media {sum(durations)/len(durations):.2f} ms, "
        f"max {max(durations):.2f} ms"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
