---
description: Traduz pseudónimos do guard-rail (EMAIL_001) de volta aos valores reais
allowed-tools: Bash
---

Resolve pseudónimos do guard-rail para o utilizador.

Argumento: `$ARGUMENTS`

- Vazio → lista o mapa da sessão mais recente.
- Um rótulo (`EMAIL_001`, `CPF_002`) → mostra o valor real correspondente.
- Uma frase com rótulos lá dentro → traduz a frase toda.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/guard-rail" map $ARGUMENTS
```

Se o shell for um sandbox isolado, o mapa real não está acessível por lá. Diz ao utilizador que corra o comando no Terminal do Mac dele — **não uses a ferramenta Read para despejar o ficheiro do mapa na conversa.**

A razão é directa: o mapa contém os dados pessoais em claro. Trazê-lo inteiro para o histórico da conversa desfaz exactamente aquilo que o plugin existe para fazer. Resolver um rótulo pontual porque o utilizador pediu é legítimo; despejar o mapa completo não é.

Depois de traduzir, se o utilizador estava a seguir uma instrução minha que mencionava um pseudónimo, reformula-a com o valor real para ele poder agir.
