---
name: guard-rail
description: Como interpretar dados redigidos pelo guard-rail. Use quando um resultado de ferramenta contiver pseudónimos como EMAIL_001, CPF_002, PESSOA_003 ou EMPRESA_001, quando aparecer um aviso "[guard-rail]" num resultado, quando o utilizador perguntar por que motivo um prompt foi bloqueado, ou quando pedir para ver o log de violações ou traduzir um pseudónimo de volta ao valor real.
---

# Trabalhar com dados redigidos

O guard-rail substitui dados pessoais por pseudónimos antes de chegarem a ti. Vais ver `EMAIL_001` onde havia um email, `CPF_002` onde havia um CPF.

## O que os pseudónimos significam

São **identificadores opacos e estáveis dentro da sessão**. O mesmo rótulo significa sempre a mesma entidade, o que permite raciocinar sobre relações:

```
0010000006 | EMAIL_001 | CPF_001 | 5105600787
0010000006 | EMAIL_001 | CPF_001 | 5105600788
0010000012 | EMAIL_002 | CPF_002 | 5105600790
```

Aqui os dois primeiros documentos pertencem à mesma pessoa e o terceiro a outra. Isso é analisável — duplicados, agregações, ligações entre tabelas — sem nunca saberes quem são.

Prefixos: `EMAIL`, `CPF`, `CNPJ`, `NIF`, `TEL`, `IBAN`, `CARTAO`, `CC`, `MORADA`, `NASC`, `CP`, `PESSOA`, `EMPRESA`.

## Regras

**Não tentes descobrir o valor real.** Não o infiras do contexto, não o adivinhes, não peças ao utilizador que to revele. Se o utilizador precisar do valor, o comando dele é `guard-rail map EMAIL_001` — corre na máquina dele e não passa por ti.

**Usa os pseudónimos nas tuas respostas.** Escreve "o registo de EMAIL_001 está duplicado", não "o registo do cliente está duplicado". O utilizador consegue traduzir; texto vago não ajuda ninguém.

**Identificadores de sistema não são redigidos** e continuam fiáveis: números de fornecedor, documento, ordem de compra, transportes, nomes de tabelas e campos. Usa-os à vontade.

**Um pseudónimo não é um dado em falta.** Não trates `EMAIL_001` como nulo nem sugiras que a query falhou.

## Quando um prompt é bloqueado

O utilizador vê uma mensagem a dizer o que foi detectado, com o comando para correr a pergunta no modelo local dele. Não lhe peças que cole o dado outra vez em texto — foi precisamente isso que o guarda impediu. Ajuda-o a reformular sem o dado, ou aponta-lhe o caminho offline.

Bloqueios de nível MÉDIO podem ser ultrapassados com o prefixo `!ok`, se ele decidir que é seguro. Menciona essa opção, mas não insistas nela.

## Ler o log

`~/.cache/guard-rail/violations.jsonl`, uma linha JSON por evento. Ações:

| Ação | Significado |
|---|---|
| `redacted` | Dado substituído. Normal. |
| `blocked` | Prompt travado. Normal. |
| `not_redacted` | **Dado passou em claro.** É o evento que interessa investigar. |
| `degraded` | Modelo local indisponível; só a regex esteve activa nessa janela. |
| `armed` | Sessão arrancou com os hooks activos. |

O log guarda pseudónimos, nunca valores reais — de propósito, para não se tornar ele próprio um depósito de dados pessoais. Ao resumires o log, mantém-no assim.

## Limites que deves saber

A deteção por regex só apanha o que tem estrutura e dígito de controlo. **Nomes de pessoas em texto livre passam**, a não ser que o utilizador tenha ligado a camada do modelo local ou declarado os termos em `client_terms`.

Ou seja: a ausência de pseudónimos num resultado **não prova** que ele está limpo. Se notares o que parece ser um nome de pessoa real num resultado não redigido, diz ao utilizador em vez de assumires que o guarda o aprovou.
