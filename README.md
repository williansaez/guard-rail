# guard-rail

Guarda-corpos de dados pessoais (LGPD / RGPD) para o Claude Code, com o teu `qwen3.5:9b` local.

| Camada | Hook | O que faz |
|---|---|---|
| **Redação** | `PostToolUse` | Troca dados reais nos resultados das ferramentas por pseudónimos estáveis, antes do Claude os ver. Não bloqueia nada. |
| **Bloqueio** | `UserPromptSubmit` | Bloqueia o prompt que *tu* escreves se contiver PII. É a única opção — este hook não consegue reescrever. |
| **Auditoria** | ambos | Regista cada violação: data/hora com fuso, gravidade, ponto exato e tipo de dado. |

## O que acontece na prática

Corres uma query no SAP que devolve dados reais:

```
LIFNR      | NAME1              | EMAIL                  | CPF            | BELNR
0010000006 | Comercio Atlantico | joao.silva@cliente.pt  | 529.982.247-25 | 5105600787
0010000006 | Comercio Atlantico | joao.silva@cliente.pt  | 52998224725    | 5105600788
0010000012 | Norte Distribuicao | ana.costa@cliente.pt   | 111.444.777-35 | 5105600790
```

O Claude recebe isto:

```
LIFNR      | NAME1              | EMAIL      | CPF     | BELNR
0010000006 | Comercio Atlantico | EMAIL_001  | CPF_001 | 5105600787
0010000006 | Comercio Atlantico | EMAIL_001  | CPF_001 | 5105600788
0010000012 | Norte Distribuicao | EMAIL_002  | CPF_002 | 5105600790
```

- **Os IDs SAP sobrevivem intactos.** `0010000006`, `5105600787`, os nomes das colunas. Sem isso o resultado era inútil.
- **Os pseudónimos são estáveis.** O mesmo email nas duas primeiras linhas é `EMAIL_001` nas duas — o Claude percebe que são a mesma entidade. `529.982.247-25` e `52998224725` partilham rótulo: a normalização ignora formatação.
- **Tu consegues voltar atrás.**

```bash
$ guard-rail map EMAIL_001
joao.silva@cliente.pt

$ guard-rail map -t "Corrige o registo de EMAIL_001, o CPF_001 está mal"
Corrige o registo de joao.silva@cliente.pt, o 529.982.247-25 está mal
```

## O log de violações

Cada intervenção fica registada em `~/.cache/guard-rail/violations.jsonl` — uma linha JSON por evento, appendável, greppável, pronta para um SIEM.

```bash
$ guard-rail log

🔴 2026-09-07 08:12:15  redigido           mcp__abap-adt__runQuery
     • Email: 2×  EMAIL_001, EMAIL_002
     • CPF: 2×  CPF_001, CPF_002
🔴 2026-09-07 08:12:15  BLOQUEADO          UserPromptSubmit
     • CPF: 1×  —
🔴 2026-09-07 08:12:15  PASSOU EM CLARO    mcp__abap-adt__tableContents
     ↳ resultado com 965000 chars excede max_output_chars=400000; passou sem inspecao
```

```bash
$ guard-rail log --summary

Por ponto de violação

  mcp__abap-adt__runQuery       redigido 1
  UserPromptSubmit              BLOQUEADO 1
  mcp__abap-adt__tableContents  PASSOU EM CLARO 1

Por tipo de dado

  CPF    3
  Email  2

⚠️  1 evento(s) em que dados passaram EM CLARO — ver `guard-rail log --leaks`
```

### O log nunca contém o valor real

Guarda o **pseudónimo**, não o dado. Se guardasse o valor, o ficheiro de auditoria passaria a ser ele próprio um depósito de PII — pior que o original, porque cresce sem limite e ninguém se lembra dele. Para chegar ao valor real cruzas com o mapa: `guard-rail map EMAIL_001`. Há um teste dedicado a garantir isto.

### Quatro tipos de evento

| Ação | Significado |
|---|---|
| `redacted` | Dado substituído por pseudónimo. O trabalho continuou. |
| `blocked` | Prompt travado. Nada saiu da máquina. |
| `not_redacted` | **Dado passou EM CLARO.** É o evento que interessa auditar — vê `--leaks`. |
| `degraded` | Controlo a funcionar abaixo do previsto (Ollama em baixo). Gravidade `INFO`, não é violação, mas permite dizer depois "nesta janela o modelo local esteve offline". |

### Filtros

```bash
guard-rail log --today
guard-rail log --since 2026-09-01
guard-rail log --severity ALTO
guard-rail log --leaks          # só o que passou em claro
guard-rail log --summary
guard-rail log --json           # saída crua
guard-rail log -n 100
```

## Estado: o que está verificado e o que não está

Isto importa mais que a lista de funcionalidades. Um plugin de privacidade que falha em silêncio é **pior que não ter plugin nenhum**, porque passas a confiar numa proteção que não existe.

| | Estado |
|---|---|
| Deteção, redação, pseudónimos, log | ✅ **85 testes automáticos**, verdes |
| Compatível com Python 3.9 (o do macOS) | ✅ verificado — `from __future__ import annotations` em todos os módulos |
| Hooks disparam no Claude Code CLI | ⚠️ **não verificado por mim** — corre `guard-rail doctor` |
| Hooks disparam no Cowork | ⚠️ **parcialmente** — ver abaixo |
| `updatedToolOutput` honrado pela tua versão | ⚠️ **não verificado** — o `doctor` diz-te |
| Camada Ollama / qwen3.5:9b | ❌ **nunca correu** — não tinha Ollama no ambiente de testes |

### Sobre o Cowork

Evidência directa: hooks `SessionStart` e `UserPromptSubmit` **funcionam** no Cowork — outro plugin instalado usa-os e vê-se a disparar. Por isso este plugin declara os hooks **inline no `plugin.json`**, que é o formato observado a funcionar, e não num `hooks/hooks.json` separado.

O que continua por confirmar é o `PostToolUse` — nenhum plugin que pude inspecionar o usa. Não invento a resposta: o plugin regista um evento `armed` a cada arranque, e o `doctor` compara isso com os eventos de redação. Se vires `armed` mas nunca `redacted` depois de leres ficheiros com dados pessoais, o `PostToolUse` não dispara nessa superfície.

Nomes de ferramentas diferem: no Cowork o shell é `mcp__workspace__bash` (não `Bash`). Ambos estão cobertos.

## Instalação

### 1. Põe a pasta num sítio permanente

A pasta de saída da sessão não serve — o plugin tem de continuar lá amanhã.

```bash
mkdir -p ~/claude-plugins
cp -R guard-rail ~/claude-plugins/
chmod +x ~/claude-plugins/guard-rail/bin/guard-rail
```

### 2. Claude Code CLI

A pasta é o seu próprio marketplace (`.claude-plugin/marketplace.json` com `source: "./"`), por isso aponta-se directamente a ela:

```bash
claude plugin marketplace add ~/claude-plugins/guard-rail
claude plugin install guard-rail@guard-rail
```

O ID é `plugin@marketplace` — ambos se chamam `guard-rail`.

### 3. Cowork

Pelo gestor de plugins da aplicação, apontando a `~/claude-plugins/guard-rail`. O Cowork não partilha `~/.claude/` com o CLI: são duas instalações independentes, com dois logs separados.

### 4. Reinicia a sessão

Hooks só carregam no arranque. Sem isto, o plugin aparece instalado e não faz nada.

### 5. Resto

```bash
ln -s ~/claude-plugins/guard-rail/bin/guard-rail /usr/local/bin/guard-rail
ollama run qwen3.5:9b ""   # mantém o modelo quente
```

Depois preenche `client_terms` no `config.json`. **Não é opcional** — ver limitação nº 1.

## Comandos dentro do Claude

Depois de instalado, sem sair da conversa:

| Comando | O que faz |
|---|---|
| `/guard-rail:doctor` | Diagnóstico — ambiente, Ollama, e se os hooks disparam mesmo |
| `/guard-rail:log` | Violações registadas. Aceita `--today`, `--leaks`, `--summary` |
| `/guard-rail:map EMAIL_001` | Traduz um pseudónimo de volta ao valor real |

**Ressalva no Cowork:** o shell do Claude no Cowork é um Linux isolado, não o teu Mac — não vê o teu Ollama nem o teu ambiente Python. Os comandos detetam isso e dizem-to, em vez de reportarem falsos negativos. Para diagnóstico completo, corre no Terminal do Mac. No Claude Code CLI não há esta limitação.

O `/guard-rail:map` nunca despeja o mapa completo na conversa — isso traria os dados reais para o histórico e desfazia o que o plugin existe para fazer. Resolve rótulos pontuais, só.

## Primeiro uso: prova que funciona

```bash
guard-rail doctor
```

Antes de confiares, faz este teste de 2 minutos:

1. Instala, **reinicia a sessão** (os hooks só carregam no arranque).
2. Cria um ficheiro com um email lá dentro: `echo "contacto: teste@exemplo.pt" > /tmp/t.txt`
3. Pede ao Claude para o ler.
4. `guard-rail doctor` — se disser **"PostToolUse disparou e redigiu"**, está a proteger-te a sério. Se disser que nunca redigiu, não está.

```
── Hooks: dispararam mesmo? ──

  ✅ SessionStart disparou (3×)
       superficie=cowork python=3.9.6
  ✅ PostToolUse disparou e redigiu
       ferramentas: mcp__workspace__bash, Read
```

## Limites — lê antes de confiar

### 1. Nomes só são apanhados se os declarares

A regex apanha o que tem estrutura: CPF, NIF, email, telefone, IBAN, cartão, morada, código postal. **Não apanha nomes.** No exemplo acima, `Comercio Atlantico` e `Norte Distribuicao` passaram intactos — e um `NAME1` com nome de pessoa singular passaria na mesma.

- **`client_terms`** no `config.json` — determinístico e auditável, mas só apanha o que escreveste lá.
- **`llm_on_tool_output: true`** — o qwen extrai nomes de pessoas. Apanha o que não previste, mas é probabilístico e acrescenta latência a **cada** resultado MCP. Desligado por defeito; liga e mede.

Não há terceira opção honesta. É a fronteira real do que esta ferramenta faz.

### 2. Resultados grandes passam sem ser inspecionados

Acima de `max_output_chars` (400 000) o hook desiste. **Regista a violação como `not_redacted`** e avisa no stderr, mas o dado passa. Vê `guard-rail log --leaks` de vez em quando.

### 3. O mapa em disco contém os dados reais

`~/.cache/guard-rail/map-*.json`, permissões `0600`. É a contrapartida de ser reversível.

```bash
guard-rail purge 7     # apaga mapas e prompts com mais de 7 dias
```

`purge` apaga mapas e prompts guardados, mas **poda o log em vez de o apagar** — manter o histórico de violações é o objetivo dele.

### 4. O prompt que tu escreves só pode ser bloqueado

`UserPromptSubmit` não suporta reescrita — confirmado na documentação, é feature request aberta (issues #34390, #27365, #53330). Essa camada bloqueia com `exit 2` e entrega-te o comando para correres offline. Escape consciente: prefixa com `!ok`.

### 5. NOTA-COLISÃO: números de 10 dígitos

Documento SAP (`5105600787`) e telefone fixo BR sem formatação (`1132654321`) são ambos 10 dígitos. Números crus são tratados como ID de sistema — senão o teu trabalho normal era redigido todo. Telefone **formatado** (`(11) 3265-4321`) é apanhado.

### 6. Não cobre tudo

Matchers: `mcp__*__*`, `Read`, `Grep`, `Bash`. `WebFetch`, `Write` e ferramentas futuras ficam de fora até as pores em `redact_matchers`. Os **argumentos** de saída (`PreToolUse`) também não são filtrados — um CPF dentro de um `WHERE` enviado a um MCP remoto passa.

## Latência medida

Redação, output sintético denso em PII, sem LLM:

| Tamanho | Tempo |
|---|---|
| 1 KB | 18 ms |
| 10 KB | 20 ms |
| 50 KB | 28 ms |
| 100 KB | 40 ms |
| 200 KB | 62 ms |
| 500 KB | 19 ms *(acima do limite — não inspecionado)* |

~18 ms é o arranque do Python; a redação é linear no tamanho. Camada regex isolada: **0.02 ms**.

## Testes

```bash
python3 tests/test_detectors.py   # 21 — deteção e falsos positivos
python3 tests/test_redact.py      # 28 — redação, estabilidade, latência
python3 tests/test_auditlog.py    # 36 — log, filtros, e o log sem valores reais
```

85 asserções. Correm com `HOME` temporário, não tocam nos teus dados.

## Desligar

```bash
GUARD_RAIL_OFF=1 claude
```

Ou no `config.json`: `redact_tool_output: false`, `block_at: "ALTO"`, `use_llm: false`.

## Estrutura

```
guard-rail/
├── .claude-plugin/plugin.json  ← hooks declarados inline, aqui
├── config.json                 ← preenche client_terms
├── hooks/
│   ├── heartbeat.py            ← SessionStart: prova que os hooks disparam
│   ├── guard.py                ← UserPromptSubmit: bloqueia
│   ├── redact.py               ← PostToolUse: redige
│   ├── detectors.py            ← regex + dígitos de controlo, spans
│   ├── pseudonyms.py           ← mapa estável e reversível
│   ├── auditlog.py             ← registo JSONL de violações
│   └── classifier.py           ← Ollama
├── commands/                   ← /guard-rail:doctor · :log · :map
│   ├── doctor.md
│   ├── log.md
│   └── map.md
├── bin/guard-rail              ← doctor · log · map · local · purge
└── tests/
```
