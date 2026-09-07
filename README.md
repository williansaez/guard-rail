<a href="https://www.buymeacoffee.com/williansaez" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

# guard-rail

**Keep personal data out of the model, without stopping your work.**

[![CI](https://github.com/williansaez/guard-rail/actions/workflows/ci.yml/badge.svg)](https://github.com/williansaez/guard-rail/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

guard-rail is a plugin for Claude Code. It hooks the point where tool results
reach the model and replaces personal data — national IDs, emails, phone numbers,
IBANs, addresses — with stable, reversible pseudonyms. The model sees
`EMAIL_001`; you keep a local map back to the real value. Prompts you write
yourself are checked too, and blocked when they carry personal data, because that
hook cannot rewrite text.

Detection is regex with check-digit validation, so document numbers and system
identifiers survive untouched. An optional local model, served by Ollama, covers
free-text names the regex cannot reach. Nothing leaves your machine.

> **Redaction is not a guarantee.** Names in free text pass through by default,
> results above a size limit pass uninspected, and a plugin whose hooks never fire
> protects nothing while looking installed. Read
> [What this tool does not protect](SECURITY.md#what-this-tool-does-not-protect)
> before you rely on it, and run `guard-rail doctor` after installing.

## Table of contents

- [What it looks like](#what-it-looks-like)
- [The audit log](#the-audit-log)
- [Status](#status)
- [Install](#install)
- [Prove it works](#prove-it-works)
- [Commands](#commands)
- [Configuration](#configuration)
- [Performance](#performance)
- [Testing](#testing)
- [How it works](#how-it-works)
- [License](#license)

## What it looks like

A query against a business system returns real data:

```
LIFNR      | NAME1              | EMAIL                  | CPF            | BELNR
0010000006 | Comercio Atlantico | joao.silva@cliente.pt  | 529.982.247-25 | 5105600787
0010000006 | Comercio Atlantico | joao.silva@cliente.pt  | 52998224725    | 5105600788
0010000012 | Norte Distribuicao | ana.costa@cliente.pt   | 111.444.777-35 | 5105600790
```

The model receives this instead:

```
LIFNR      | NAME1              | EMAIL      | CPF     | BELNR
0010000006 | Comercio Atlantico | EMAIL_001  | CPF_001 | 5105600787
0010000006 | Comercio Atlantico | EMAIL_001  | CPF_001 | 5105600788
0010000012 | Norte Distribuicao | EMAIL_002  | CPF_002 | 5105600790
```

Three things are happening.

**System identifiers survive.** Supplier numbers, document numbers, column names.
Redacting those would make the result useless to work with, so every numeric
detector validates a check digit before it fires.

**Pseudonyms are stable.** The same email is `EMAIL_001` on both rows, so the
model can still tell those two documents belong to one person and reason about
duplicates. `529.982.247-25` and `52998224725` share a label too — formatting is
normalised before comparison.

**You can go back.**

```console
$ guard-rail map EMAIL_001
joao.silva@cliente.pt

$ guard-rail map -t "the record for EMAIL_001 is duplicated"
the record for joao.silva@cliente.pt is duplicated
```

## The audit log

Every intervention is recorded in `~/.cache/guard-rail/violations.jsonl` — one
JSON object per line, appendable, greppable, ready for a SIEM.

```console
$ guard-rail log

🔴 2026-09-07 08:12:15  redigido           mcp__abap-adt__runQuery
     • Email: 2×  EMAIL_001, EMAIL_002
     • CPF: 2×  CPF_001, CPF_002
🔴 2026-09-07 08:12:15  BLOQUEADO          UserPromptSubmit
     • CPF: 1×  —
🔴 2026-09-07 08:12:15  PASSOU EM CLARO    mcp__abap-adt__tableContents
     ↳ resultado com 965000 chars excede max_output_chars=400000
```

| Action | Meaning |
|---|---|
| `redacted` | Value replaced by a pseudonym. Work continued. |
| `blocked` | Prompt stopped. Nothing left the machine. |
| `not_redacted` | **Data passed in the clear.** The event worth investigating. |
| `degraded` | Local model unavailable; only the regex layer was active. |
| `armed` | A session started with hooks running. |

The log stores pseudonyms, never real values. A log holding the data would be a
worse repository than the original: it grows without bound and nobody remembers
it exists. Cross-reference with `guard-rail map` when you need the value.

```bash
guard-rail log --today
guard-rail log --leaks       # only what passed in the clear
guard-rail log --summary     # aggregated by violation point
guard-rail log --json
```

## Status

| | State |
|---|---|
| Detection, redaction, pseudonyms, audit log | **85 automated tests**, green |
| Python 3.9 compatibility | Verified in CI on 3.9–3.13, Linux and macOS |
| Hooks firing in Claude Code CLI | **Unverified** — run `guard-rail doctor` |
| Hooks firing in Cowork | **Unverified** |
| Local Ollama layer | **Never exercised** — no Ollama in the test environment |

The rows marked unverified are not modesty. They are the difference between code
that is correct and protection that is running, and only your machine can settle
it. `doctor` is built to answer exactly that question.

## Install

Requires Python 3.9+ (macOS ships one). Ollama is optional.

```bash
git clone https://github.com/williansaez/guard-rail.git ~/claude-plugins/guard-rail
chmod +x ~/claude-plugins/guard-rail/bin/guard-rail
ln -s ~/claude-plugins/guard-rail/bin/guard-rail /usr/local/bin/guard-rail
```

**Claude Code CLI**

```
/plugin marketplace add williansaez/guard-rail
/plugin install guard-rail@guard-rail
```

Or from the clone, which tracks your local edits:

```bash
claude plugin marketplace add ~/claude-plugins/guard-rail
claude plugin install guard-rail@guard-rail
```

**Restart the session.** Hooks load at startup; without a restart the plugin
appears installed and does nothing.

**Optional, for the local-model layer**

```bash
ollama pull qwen3.5:9b
ollama run qwen3.5:9b ""   # keeps it warm
```

## Prove it works

```bash
guard-rail doctor
```

Then the two-minute test that matters, because installation is not protection:

1. `echo "contact: test@example.pt" > /tmp/t.txt`
2. Ask the model to read that file.
3. `guard-rail doctor` again.

If it reports **"PostToolUse disparou e redigiu"**, redaction is live. If it
reports that nothing was ever redacted, the hook is not running on this surface
and the redaction layer is decorative — find out now rather than during real work.

## Commands

Inside a session:

| Command | Purpose |
|---|---|
| `/guard-rail:doctor` | Diagnose environment, Ollama, and whether hooks fire |
| `/guard-rail:log` | Recorded violations; takes `--today`, `--leaks`, `--summary` |
| `/guard-rail:map EMAIL_001` | Resolve one pseudonym |

In a terminal: `guard-rail doctor | log | map | local | purge`.

`guard-rail local <file>` runs a blocked prompt against your local model, so a
question you could not ask the provider still gets answered.

Note that in Cowork the assistant's shell is an isolated Linux VM, not your Mac.
The commands detect this and say so rather than reporting a false negative about
your Ollama. For a full diagnosis there, use a terminal.

## Configuration

`config.json` in the plugin directory, overridden by `~/.config/guard-rail.json`.

| Key | Default | Notes |
|---|---|---|
| `block_at` | `MEDIO` | Severity that blocks a prompt. `ALTO` interrupts less. |
| `client_terms` | `[]` | Names identifying your clients. **Put these in the override file** — this one is versioned. |
| `redact_matchers` | `mcp__*__*`, `Read`, `Grep`, `Bash` | Tools whose results are inspected. |
| `max_output_chars` | `400000` | Above this, results pass uninspected and log a `not_redacted` event. |
| `llm_on_tool_output` | `false` | Local model on tool results. Catches names; costs latency on every call. Measure before enabling. |
| `fail_closed` | `false` | When Ollama is down: `true` blocks defensively, `false` trusts the regex alone. |

Disable entirely with `GUARD_RAIL_OFF=1`.

## Performance

Redaction of a synthetic result dense with personal data, regex layer only:

| Size | Time |
|---|---|
| 1 KB | 18 ms |
| 10 KB | 20 ms |
| 50 KB | 28 ms |
| 100 KB | 40 ms |
| 200 KB | 62 ms |
| 500 KB | 19 ms *(above the limit — not inspected)* |

About 18 ms of that is Python start-up. Redaction itself is linear in input size;
the regex layer alone measures 0.02 ms. The `PostToolUse` hook runs on every tool
call, so this budget is the constraint the design answers to.

## Testing

```bash
python3 tests/test_detectors.py   # 21 — detection and false positives
python3 tests/test_redact.py      # 28 — redaction, stability, latency
python3 tests/test_auditlog.py    # 36 — audit log, filters, PII absence
```

No dependencies. The hook tests run the hooks as subprocesses under a temporary
`HOME`, so they never touch a real map or log. CI runs everything on Python
3.9–3.13 across Linux and macOS, validates the manifests, and fails the build if a
real client name or a populated `client_terms` reaches the repository.

## How it works

```
guard-rail/
├── .claude-plugin/         hooks declared inline in plugin.json
├── hooks/
│   ├── heartbeat.py        SessionStart — proves hooks fire at all
│   ├── guard.py            UserPromptSubmit — blocks
│   ├── redact.py           PostToolUse — redacts via updatedToolOutput
│   ├── detectors.py        regex, check digits, positional spans
│   ├── pseudonyms.py       stable reversible map
│   ├── auditlog.py         JSONL violation log
│   └── classifier.py       Ollama
├── skills/guard-rail/      teaches the model to read redacted output
├── commands/               /guard-rail:doctor, :log, :map
└── bin/guard-rail          console
```

Two design decisions carry most of the weight.

**Check digits, not just patterns.** A bare nine-digit regex would fire on every
counter and internal ID in a query result. Validating the check digit is what
lets the tool run against business data without corrupting it — a false positive
here replaces a document number with a pseudonym and silently poisons the model's
reasoning.

**Redaction over blocking, wherever the API allows it.** `PostToolUse` can
rewrite a result, so it does, and you keep working. `UserPromptSubmit` cannot —
there is no `updatedPrompt` field — so it blocks and hands you an offline path
instead. The asymmetry is imposed by the hook API, not chosen.

## License

MIT. See [LICENSE](LICENSE).

If guard-rail saves you time, you can [buy me a coffee](https://www.buymeacoffee.com/williansaez).

Security policy and threat model: [SECURITY.md](SECURITY.md).
Contributing, including the rule about validators: [CONTRIBUTING.md](CONTRIBUTING.md).
