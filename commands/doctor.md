---
description: Diagnostica o guard-rail — ambiente, Ollama, e se os hooks estão mesmo a disparar
allowed-tools: Bash, Read, Glob
---

Corre o diagnóstico do guard-rail e reporta o resultado ao utilizador.

## Passo 1 — descobre onde o teu shell corre

Antes de mais, determina se a ferramenta Bash corre na máquina do utilizador ou num sandbox isolado:

```bash
uname -s && echo "HOME=$HOME" && ls "$HOME/.cache/guard-rail" 2>/dev/null || echo "sem cache do guard-rail neste sistema"
```

- **`Darwin`** → é o Mac do utilizador (Claude Code CLI). Segue para o Passo 2A.
- **`Linux`** → é um sandbox isolado (Cowork). O Ollama e o histórico real do utilizador **não estão aqui**. Segue para o Passo 2B.

Esta distinção não é um detalhe: no sandbox o diagnóstico diria "Ollama não responde" mesmo com o Ollama a correr perfeitamente no Mac. Reportar isso como avaria seria mentira.

## Passo 2A — Mac (diagnóstico completo)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/guard-rail" doctor $ARGUMENTS
```

Mostra a saída tal como veio. Depois interpreta as três coisas que importam:

- **Python < 3.9** → o plugin não arranca. É bloqueante.
- **Ollama em baixo ou sem o modelo** → a camada LLM está desligada; a regex continua a proteger. Diz isso claramente em vez de alarmar.
- **`PostToolUse` nunca redigiu, mas `SessionStart` disparou** → o hook de redação não está activo nesta superfície. É o pior cenário, porque falha em silêncio: o utilizador julga estar protegido e não está. Sinaliza-o com destaque.

## Passo 2B — Cowork (diagnóstico parcial, sem fingir)

Diz ao utilizador, numa frase, que o teu shell é um sandbox isolado e por isso não consegues verificar o Ollama nem o ambiente Python dele.

O que **consegues** verificar: o log de violações vive na máquina dele, e a ferramenta Read alcança-o. Lê-o directamente:

- `~/.cache/guard-rail/violations.jsonl`

Com esse ficheiro responde à única pergunta que interessa no Cowork:

- Há eventos `armed`? → os hooks de plugin disparam nesta superfície.
- Há eventos `redacted`? → o `PostToolUse` funciona e a redação está mesmo activa.
- Há `armed` mas nenhum `redacted`, e o utilizador já leu ficheiros com dados pessoais? → **o `PostToolUse` não dispara no Cowork.** Diz-lho sem rodeios e sugere que corra o diagnóstico completo no Terminal do Mac.
- Ficheiro inexistente? → o plugin ainda não foi instalado ou a sessão não foi reiniciada desde a instalação.

## Regras

Não inventes o estado de nada que não conseguiste observar. Se não pudeste verificar uma camada, diz que não pudeste — um plugin de privacidade que parece verde sem o estar é pior que nenhum.
