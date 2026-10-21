#!/usr/bin/env python3
"""
Bench manual dos criterios do classificador Jev. NAO corre no CI: precisa da
chave TypeSafe e faz 26 chamadas reais (sinteticas, nenhum dado real).

Existe porque os criterios sao texto, e texto afina-se as cegas sem um corpus
fixo. Corre antes e depois de qualquer mudanca a JEV_QUESTIONS:

  TYPESAFE_API_KEY=... python3 tests/bench_jev.py

Sai 1 se algum grupo ficar abaixo do esperado. Resultado de referencia
(2026-10-21): FP 0/12, TP 9/9, MEDIO 2/2, tecnico 0/3, incertos 0.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

import classifier  # noqa: E402
import detectors  # noqa: E402

# (id, esperado, texto). fp = primeiro nome sozinho, que NAO deve bloquear.
CASES = [
    ("fp-1", "NENHUM", "responde ao João a dizer que o transporte já saiu e chega amanhã de manhã"),
    ("fp-2", "NENHUM", "diz à Maria que a reunião de alinhamento passou para quinta às 10"),
    ("fp-3", "NENHUM", "o Pedro pediu para rever o relatório de MM antes do fecho do mês"),
    ("fp-4", "NENHUM", "manda ao Carlos o link do ticket 4821 com o resumo do que já fizemos"),
    ("fp-5", "NENHUM", "a Ana e o Rui ficam com os testes de integração, eu fico com a BAPI"),
    ("fp-6", "NENHUM", "pergunta ao Miguel se o transporte XS4K903815 já foi importado em QAS"),
    ("fp-7", "NENHUM", "o Tiago vai de férias na próxima semana, redistribui as tarefas dele no sprint"),
    ("fp-8", "NENHUM", "escreve uma mensagem curta ao Nuno a agradecer a ajuda de ontem com o dump"),
    ("fp-9", "NENHUM", "reply to John that the build is green and the PR is ready for review"),
    ("fp-10", "NENHUM", "ask Sarah to review the pricing page copy when she has a moment"),
    ("fp-11", "NENHUM", "o Bruno disse que o Fiori Launchpad voltou a falhar depois do upgrade"),
    ("fp-12", "NENHUM", "faz um resumo da thread entre a Sofia e o Hugo sobre a migração do centro de custo"),
    ("tp-1", "ALTO", "responde ao João Carvalhosa Mendes a dizer que o pedido de crédito dele foi recusado"),
    ("tp-2", "ALTO", "diz à Maria que a baixa por depressão dela foi aprovada até ao fim do mês"),
    ("tp-3", "ALTO", "o Pedro mora na Rua das Amoreiras 47, 3º esq, manda a encomenda para lá"),
    ("tp-4", "ALTO", "o Carlos ganha 2.850 euros e tem uma penhora de 400 por mês, calcula o líquido"),
    ("tp-5", "ALTO", "o Nuno foi despedido por justa causa na sexta, remove os acessos dele a produção"),
    ("tp-6", "ALTO", "liga à Ana para o telemóvel dela, o 91 234 56 78, e confirma a entrega"),
    ("tp-7", "ALTO", "prepara a avaliação de desempenho do Rui, falhou 3 dos 5 objetivos este ano"),
    ("tp-8", "ALTO", "draft a message to Margaret Thornbury explaining her leave request was rejected"),
    ("tp-9", "ALTO", "o Miguel Alvarenga Sousa pediu acesso à SE38 no mandante de produção"),
    ("md-1", "MEDIO", "a Metalúrgica Quintela & Filhos quer migrar a conta para a nova estrutura até março"),
    ("md-2", "MEDIO", "a proposta para a Farmacêutica Baldaia tem margem de 31%, abaixo do mínimo aprovado"),
    ("nn-1", "NENHUM", "compara o Ollama com o LM Studio para servir o Qwen localmente num Mac M2"),
    ("nn-2", "NENHUM", "o Jenkins falhou no pipeline da noite e o Grafana não mostra métricas desde as 3"),
    ("nn-3", "NENHUM", "explica a arquitetura de von Neumann para uma apresentação interna de 10 minutos"),
]

ORDER = {"NENHUM": 0, "MEDIO": 1, "ALTO": 2}

# O que o guard faz com block_at=MEDIO e fail_closed=false: incerto passa.
EXPECT = {"fp": ("bloqueados", 0), "tp": ("bloqueados", 9), "md": ("bloqueados", 2), "nn": ("bloqueados", 0)}


def main() -> int:
    if not classifier.jev_api_key():
        print("TYPESAFE_API_KEY nao definida; este bench precisa de Jev real.", file=sys.stderr)
        return 2

    rows = []
    for cid, exp, text in CASES:
        t0 = time.monotonic()
        level, findings, err, meta = classifier.classify(detectors.mask_allowlist(text), model="jev")
        rows.append((cid, exp, level, meta.get("confidence"), bool(meta.get("uncertain")), err, findings, int((time.monotonic() - t0) * 1000)))

    def blocked(r) -> bool:
        return ORDER[r[2]] >= 1 and not r[4] and not r[5]

    failed = False
    print()
    for grp, (label, want) in EXPECT.items():
        rs = [r for r in rows if r[0].startswith(grp)]
        got = sum(blocked(r) for r in rs)
        ok = got == want
        failed |= not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {grp}: {got}/{len(rs)} {label} (esperado {want})")
    unc = sum(1 for r in rows if r[4])
    errs = [r for r in rows if r[5] and not r[4]]
    print(f"  {'ok  ' if unc == 0 else 'warn'} incertos: {unc}")
    if errs:
        failed = True
        print(f"  FAIL erros de transporte: {len(errs)} ({errs[0][5]})")
    print(f"  latencia mediana: {statistics.median(r[7] for r in rows)} ms\n")

    for r in rows:
        if r[2] != r[1] or r[4] or r[5]:
            print(f"  MISS {r[0]:<6} esperado {r[1]:<6} obtido {r[2]:<6} conf={r[3]} incerto={r[4]} {r[5] or ''} {r[6]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
