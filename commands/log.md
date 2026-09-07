---
description: Mostra o log de violações do guard-rail — o que foi bloqueado, redigido, ou passou em claro
allowed-tools: Bash, Read
---

Mostra ao utilizador as violações registadas pelo guard-rail.

Argumentos recebidos: `$ARGUMENTS`
Filtros aceites: `--today`, `--since AAAA-MM-DD`, `--severity ALTO|MEDIO`, `--leaks`, `--summary`, `-n N`. Sem argumentos, mostra os eventos recentes.

## Como obter os dados

Tenta primeiro o comando:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/guard-rail" log $ARGUMENTS
```

Se o shell for um sandbox isolado (Linux, sem `~/.cache/guard-rail`), esse comando não vê o log real do utilizador. Nesse caso lê o ficheiro directamente com a ferramenta Read, que alcança a máquina dele:

- `~/.cache/guard-rail/violations.jsonl`

É JSONL: uma linha JSON por evento. Aplica tu os filtros pedidos e apresenta em tabela legível.

## Como apresentar

Ordena do mais recente para o mais antigo. Para cada evento mostra hora, gravidade, ação e o ponto de violação.

Significado das ações:

- `redacted` — dado substituído por pseudónimo; o trabalho continuou. Normal.
- `blocked` — prompt travado; nada saiu da máquina. Normal.
- `not_redacted` — **dado passou EM CLARO.** É o evento que interessa. Destaca-o sempre, mesmo quando o utilizador não pediu `--leaks`.
- `armed` / `degraded` — sinais de funcionamento, não violações. Não os apresentes como alarme.

## Regra sobre valores

O log guarda pseudónimos (`EMAIL_001`), nunca o dado real — é intencional, para o ficheiro de auditoria não se tornar ele próprio um depósito de dados pessoais.

Se o utilizador quiser saber a quem corresponde um rótulo, aponta-lhe `/guard-rail:map EMAIL_001`. Não tentes deduzir o valor real a partir do contexto nem lhe peças que to revele.

Termina com uma leitura do padrão, não só a lista: se houver eventos `not_redacted`, diz onde estão a escapar dados e o que os causou.
