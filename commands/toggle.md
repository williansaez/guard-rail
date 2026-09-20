---
description: Liga ou desliga o guard-rail, e diz em que estado está
allowed-tools: Bash, Read
---

Liga, desliga ou mostra o estado do guard-rail.

Argumento recebido: `$ARGUMENTS` — `on`, `off`, ou vazio (mostra só o estado).

## Como agir

Sem argumento, ou com `status`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/guard-rail" status
```

Com `on` ou `off`, corre o subcomando correspondente:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/guard-rail" off
```

O estado fica em `~/.config/guard-rail.json` e vale para todas as sessões até
ser mudado — não é uma pausa temporária. Mostra a saída tal como veio.

## Regras

**Desligar tem efeito na sessão seguinte, não a meio desta.** Os hooks lêem a
configuração quando disparam, por isso o próximo prompt já apanha o estado novo;
mas diz ao utilizador que, se quiser garantia, reinicie a sessão.

**Nunca desligues por iniciativa própria.** Se um prompt foi bloqueado ou um
resultado redigido, a resposta certa é reformular sem o dado ou usar
`guard-rail local` — não desarmar a protecção. Só corre `off` quando o
utilizador o pede explicitamente.

**Quando desligares, diz o que deixa de acontecer**, numa frase: prompts com
dados pessoais deixam de ser bloqueados e resultados de ferramentas passam ao
modelo em claro. E diz como voltar: `/guard-rail:toggle on`.

**Se o utilizador só quer silenciar um caso concreto**, aponta-lhe as opções
mais estreitas antes de desligar tudo: o prefixo `!ok ` passa um prompt de nível
MÉDIO, e `block_at: "ALTO"` na configuração interrompe menos.

O interruptor fica no log de violações como evento `toggled` — é intencional,
para depois se conseguir dizer se uma janela sem redações foi ausência de dados
ou ausência de protecção.
