---
description: Mostra ou muda o modelo que classifica os prompts — Ollama local, ou Jev na cloud
allowed-tools: Bash, Read
---

Mostra o modelo activo e os disponíveis, ou muda para outro.

Argumento recebido: `$ARGUMENTS` — vazio (mostra), `jev`, ou o nome de um
modelo Ollama como `qwen3.5:9b`.

## Como agir

Sem argumento:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/guard-rail" model
```

Com argumento, passa-o tal qual:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/guard-rail" model jev
```

A escolha fica em `~/.config/guard-rail.json` e vale para todas as sessões até
ser mudada. Mostra a saída tal como veio.

## Regras

**Ao mudar para `jev`, diz numa frase o que muda:** os prompts que a regex não
conseguiu decidir sozinha passam a ser enviados à TypeSafe para classificação.
Até aqui nada saía da máquina. E diz como voltar: `/guard-rail:model qwen3.5:9b`.

**Nunca mudes de modelo por iniciativa própria.** Só corre com argumento quando o
utilizador o pede explicitamente. Se um prompt foi bloqueado, a resposta é
reformular, não trocar de classificador.

**Se o utilizador escolhe `jev` sem chave**, a saída avisa. Explica que a chave
se define nas opções do plugin (Claude Code guarda-a no Keychain) e que, até lá,
só a regex decide.

**Com `jev` a extração de nomes em resultados de ferramentas fica desligada**,
mesmo que `llm_on_tool_output` esteja a `true`: o Jev não devolve texto. Se o
utilizador precisa dessa camada, precisa de um modelo Ollama.

A mudança fica no log de violações como evento `toggled` com a transição
(`model: qwen3.5:9b → jev`) — é intencional, para se saber depois em que
janela o texto residual saiu da máquina.
