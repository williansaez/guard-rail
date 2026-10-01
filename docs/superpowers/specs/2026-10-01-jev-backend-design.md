# Jev as an opt-in classifier backend, selected with `guard-rail model`

Date: 2026-10-01
Status: approved in conversation, pending review of this document
Target version: 2.3.0

## Goal

Let the residual classification layer (the LLM that runs when the regex has
not already decided) use TypeSafe's Jev instead of a local Ollama model, and
give the user one command, `guard-rail model`, to see what is available and
pick it. The default stays Ollama with `qwen3.5:9b`, so the plugin's privacy
promise is unchanged for anyone who installs it and configures nothing.

## Why

A 46-case synthetic benchmark on 2026-10-01 (Portuguese and Brazilian prompts,
ALTO/MEDIO/NENHUM plus adversarial cases) gave:

| metric | qwen3.5:9b local | Jev |
|---|---|---|
| 3-level accuracy | 93% | 98% |
| ALTO blocked (at or above MEDIO) | 95% | 100% |
| NENHUM blocked by mistake | 10% | 5% |
| prompt injections resisted | 3/3 | 3/3 |
| transport errors | 1 (cold start over 8 s) | 0 |
| median / p90 latency | 2.2 s / 2.7 s | 339 ms / 388 ms |

Jev is a cloud API. Choosing it means the residual prompt text, after regex
masking, leaves the machine. That is why it is opt-in, why choosing it is
audited, and why the documentation must say so plainly.

## Decisions taken

- Default backend: Ollama. Jev is opt-in.
- With `model: jev`, the entity-extraction layer on tool output
  (`llm_on_tool_output`) is off, because Jev cannot return literal text and
  Ollama may not be running. `guard-rail doctor` says so.
- Jev's confidence below a threshold is handled by the existing `fail_closed`
  key, with the same meaning it already has for an unreachable Ollama.

## What Jev is, as far as this plugin cares

- `POST https://api.typesafe.ai/v1/systemone`, bearer key, JSON body
  `{"state": <text>, "model": "jev-latest", "questions": {...}}`.
- Three question types: `choice` (returns `choice` and `confidence`), `noul`
  (returns a probability in `noul`), `score`. Answers are typed. Jev never
  returns free text, so it cannot extract names.
- Stdlib `urllib` is enough. The plugin does not import anything from the
  claude-jev plugin.

## Configuration

### The `model` key

`model` remains the only key that selects the classifier. Its value is either
the literal `jev` or an Ollama model name. No separate `llm_backend` key.

Precedence, strongest first, mirroring the on/off switch in `hooks/state.py`:

1. `GUARD_RAIL_MODEL` environment variable (already read by `guard-rail local`)
2. `~/.config/guard-rail.json`, written by `guard-rail model <name>`
3. `config.json` in the plugin
4. default `qwen3.5:9b`

### New keys

- `jev_host`, default `https://api.typesafe.ai/v1/systemone`, next to
  `ollama_host`. Exists so tests can point at a fake Jev on localhost.
- `jev_model`, default `jev-latest`. The TypeSafe model id sent in the body.

### The API key

`.claude-plugin/plugin.json` declares:

```json
"userConfig": {
  "typesafe_api_key": {
    "type": "string",
    "title": "TypeSafe API key",
    "description": "Only needed when `guard-rail model jev` is selected. Without it Jev is never called and the regex layer decides alone.",
    "sensitive": true
  }
}
```

Claude Code stores a sensitive option in the Keychain and hands it to hooks as
`CLAUDE_PLUGIN_OPTION_TYPESAFE_API_KEY`. The hooks read that first and fall
back to `TYPESAFE_API_KEY` for manual installs. The key is never written to
any file by this plugin, and never logged.

## Components

### `hooks/classifier.py`

- `classify()` gains `jev_host`, `jev_model` and `api_key` parameters and
  returns a 4-tuple `(level, findings, err, meta)`. `meta` is
  `{"backend": "jev" | "ollama", "confidence": float | None}`. The existing
  callers (`guard.py`, `tests/test_llm_layer.py`, `tests/test_auditlog.py`)
  are updated to unpack four values.
- When `model == "jev"` it calls `_classify_jev()`; otherwise the existing
  Ollama path runs unchanged.
- `_classify_jev()` sends one request with five questions:
  - `nivel`: `choice` with criteria ALTO / MEDIO / NENHUM, text taken from the
    current `SYSTEM` prompt, including the instructions that the state is
    data, that `<ID>` markers are already anonymised, and that technology
    names are not people.
  - `pessoa`, `morada`, `saude`, `cliente`: `noul` questions used only to
    name the finding.
  - State is `"<texto>\n" + text + "\n</texto>"`, the same delimiters the
    Ollama prompt uses.
- Findings from Jev are category labels with the probability, for example
  `nome de pessoa (0.93)`, listing only `noul` answers at or above 0.5. No
  literals.
- `MIN_CONFIDENCE = 0.6`. If the `choice` confidence is below it, the function
  returns `err = "Jev incerto (0.30)"` with the level it would have given, so
  the caller can apply `fail_closed`. The benchmark placed every confident
  answer at 0.77 or above and every ambiguous case at 0.58 or below.
- Error strings follow the existing pattern: `Jev sem chave`,
  `Jev inacessivel (...)`, `Jev excedeu Ns`, `Jev devolveu HTTP 401`,
  `Resposta do Jev nao era JSON valido`. Any exception maps to an error
  string; nothing propagates.
- `extract_entities()` returns `[]` immediately when `model == "jev"`.

### `hooks/guard.py`

- Reads `model`, `jev_host`, `jev_model` and the key from config and
  environment and passes them to `classify()`.
- Finding labels: `(jev)` or `(modelo local)` in both the block message and
  the audit findings, replacing the current hard-coded `(modelo local)`.
- On `err` starting with `Jev incerto`:
  - `fail_closed: false` records an audit event with the new action
    `UNCERTAIN` (severity INFO, note with the confidence) and lets the regex
    decision stand.
  - `fail_closed: true` raises the level to at least MEDIO and appends the
    finding `Jev incerto (fail_closed)`. `!ok` still overrides a MEDIO block.
- Every other `err` keeps the current `DEGRADED` path, including the
  once-per-session `systemMessage` warning.

### `hooks/redact.py`

- When `model == "jev"`, the LLM extraction step is skipped even if
  `llm_on_tool_output` is true. No audit event; the doctor reports the state.

### `hooks/state.py`

- `model_status(plugin_root) -> (model, source)` with the same four sources
  as `status()`.
- `set_model(name) -> Path`: read-modify-write of `~/.config/guard-rail.json`,
  preserving every other key, `0600`, atomic replace, same as `set_enabled`.

### `hooks/auditlog.py`

- New action constant `UNCERTAIN = "uncertain"` with a label in the CLI's
  `ACTION_LABEL` (`classificação incerta`).

### `hooks/heartbeat.py`

- The `armed` note gains `model=<name>`.
- If the model is `jev` and no key is available, prints one line to the
  session context: `[guard-rail] model=jev sem chave: classificação só por
  regex. Define a chave nas opções do plugin.`

### `bin/guard-rail`

- `guard-rail model`: prints the active model, its source, and the list of
  what is available:
  - every Ollama model from `GET {ollama_host}/api/tags`, marked `local`;
    if Ollama does not answer, one line saying so;
  - `jev`, marked `cloud, texto residual sai da máquina`, plus `(sem chave)`
    when no key is found.
- `guard-rail model <name>`: writes via `state.set_model()`, records a
  `TOGGLED` audit event with note `model: <old> → <new>`, and prints the
  result. Selecting `jev` prints one sentence stating that residual prompt
  text will leave the machine. A name that Ollama does not list is written
  anyway with a warning, since the user may be pulling it.
- `guard-rail local` keeps using `GUARD_RAIL_MODEL` but falls back to the
  configured model when that is not `jev`; with `jev` it falls back to
  `qwen3.5:9b`, because `ollama run jev` makes no sense.
- `guard-rail doctor` gains a `── Modelo ──` section:
  - active model and source;
  - for an Ollama model: the existing reachability and model-present checks;
  - for `jev`: whether a key was found, then one minimal real call (state
    `ping`, a single `noul` question, 3-second timeout) reporting the HTTP
    outcome. A missing key counts as a problem; an unreachable Jev is a
    warning, like an unreachable Ollama;
  - `extração em output: desligada com jev` whenever `model == "jev"` and
    `llm_on_tool_output` is true.

### `commands/model.md`

Slash command `/guard-rail:model`, same shape as `toggle.md`:

- no argument runs `guard-rail model`;
- an argument runs `guard-rail model <arg>`;
- rule: when switching to `jev`, tell the user in one sentence that residual
  prompt text now goes to TypeSafe, and how to go back;
- rule: never switch on your own initiative.

### `config.json`

- `model` gets a comment line explaining the two kinds of value and pointing
  at `guard-rail model`.
- `jev_host` and `jev_model` added with their defaults.

## Data flow with `model: jev`

```
prompt
  → mask_allowlist()                       (unchanged)
  → find_pii()                             (unchanged; ALTO here never calls the LLM)
  → len ≥ min_chars_for_llm?
  → classify(model="jev")
       → POST jev_host {state, questions}  ← text leaves the machine here
       → choice + 4 noul
       → confidence ≥ 0.6 → level, findings, meta
       → confidence < 0.6 → err "Jev incerto", level kept in meta
  → guard.py decides: block / pass / uncertain / degraded
```

## Audit trail

The goal is to be able to say afterwards, for any time window, whether
residual prompts were classified locally or sent to TypeSafe.

- `guard-rail model <name>` → `toggled` event with the old and new value.
- Session start → `armed` note carries `model=<name>`.
- An uncertain Jev answer → `uncertain` event.
- A Jev failure → `degraded` event, as today for Ollama.
- No per-prompt event for successful Jev classifications. The two boundary
  events above delimit the window; one line per prompt would drown the log.

## Documentation changes

- `SECURITY.md`: the "nothing is sent to a third party" sentence becomes a
  statement about the default, followed by a paragraph on `model: jev`: what
  is sent (residual prompt text after regex masking), to whom, when, and that
  the choice is recorded in the audit log.
- `README.md`: the same correction to "Nothing leaves your machine"; a
  `guard-rail model` entry in the CLI table; `/guard-rail:model` in the
  commands table; `jev_host`, `jev_model` in the config table; the benchmark
  table above in a short "Choosing a model" section.
- `CHANGELOG.md`: 2.3.0 entry.
- `skills/guard-rail/SKILL.md`: mention the `(jev)` label and the
  `uncertain` log action.
- Version bump to 2.3.0 in `plugin.json` and `marketplace.json`.

## Tests

Style: plain `python3 tests/test_x.py` scripts with `check(desc, ok)`, run
by the CI matrix, no pytest.

- `tests/test_model.py` (new):
  - precedence env > user config > plugin config > default;
  - `set_model` preserves `client_terms` and `enabled`;
  - CLI `model` with no argument lists and exits 0 with Ollama unreachable;
  - CLI `model jev` writes the key and records `toggled`;
  - corrupted user config falls back to the default.
- `tests/test_llm_layer.py` (extended) with a fake Jev HTTP server on
  localhost, selected through `jev_host` in a temporary user config and a
  key in the environment:
  - the outgoing request has the bearer header, the delimited state, and the
    five expected question ids;
  - a confident ALTO answer blocks with a `(jev)` label;
  - a 0.3-confidence answer passes with an `uncertain` event when
    `fail_closed` is false, and blocks at MEDIO when it is true;
  - missing key → `degraded` event and the once-per-session warning;
  - HTTP 401 → `degraded`;
  - with `model: jev` and `llm_on_tool_output: true`, `redact.py` never
    contacts Ollama;
  - with `model: jev`, the Ollama host is never contacted by `guard.py`.

## Out of scope

- A Jev-based extraction layer. Jev cannot return literals.
- Per-prompt logging of external sends.
- Changing the default model or the regex layer.
- The two Ollama defects found by the benchmark (cold-start timeout, and
  pseudonym markers without angle brackets): tracked separately.
