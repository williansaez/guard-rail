# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-10-01

### Added

- `guard-rail model` and `/guard-rail:model`: show the classifier in use and
  the models available, or switch. `jev` selects TypeSafe's Jev, a cloud API
  that answered a 46-case synthetic corpus at 98% accuracy and 339 ms median
  against 93% and 2.2 s for the local `qwen3.5:9b`. Any other name selects
  that Ollama model. The default is unchanged. The choice is written to
  `~/.config/guard-rail.json` and recorded in the audit log as a `toggled`
  event with the transition; every session start records the model in use.
- The TypeSafe key is a plugin option (`typesafe_api_key`, kept in the
  Keychain), with `TYPESAFE_API_KEY` as the fallback for manual installs.
- Findings from the LLM layer now say which backend produced them, `(jev)`
  or `(modelo local)`, in the block message and in the audit log.
- A Jev answer below 0.6 confidence is logged as a new `uncertain` event;
  `fail_closed` decides whether it passes or blocks at MEDIO.
- `guard-rail doctor` has a `── Modelo ──` section: which model, from where,
  whether it answers, and whether extraction on tool output is off.
- `tests/test_model.py`, and Jev coverage in `tests/test_llm_layer.py` with a
  fake Jev on localhost that also catches any stray call to Ollama.
- The Jev client refuses HTTP redirects, so neither the key nor the prompt
  text can be re-sent to a host the response names. A reply without a usable
  `nivel` is a `degraded` classification (which warns), never a silent
  NENHUM; an `uncertain` event records which level Jev leaned towards.

### Changed

- With `model: jev` the entity-extraction layer on tool output is off, because
  Jev returns typed answers and never literals. The doctor says so.
- `SECURITY.md` and the README state the privacy promise for the default and
  what changes under Jev.

## [2.2.1] - 2026-09-21

### Fixed

- The local-model layer never worked with `qwen3.5:9b`. It is a reasoning
  model: without `"think": false` Ollama returns its output in the `thinking`
  field and leaves `response` empty, so every prompt was logged as "Resposta do
  modelo nao era JSON valido" and decided by the regex alone. Both
  `classify()` and `extract_entities()` now send `"think": false`.
- The degraded-control warning was printed to stderr with exit 0, which Claude
  Code does not show to the user, so a layer that was down for every prompt
  went unnoticed. It is now a `systemMessage` on stdout, shown once per
  session and again if the failure lasts beyond 30 minutes. The audit log
  still records every degradation.

### Added

- `tests/test_llm_layer.py`, covering the request payload and the warning's
  visibility and rate limit, wired into CI.

## [2.2.0] - 2026-09-20

### Added

- An on/off switch: `guard-rail on`, `guard-rail off` and `guard-rail status`,
  plus the slash command `/guard-rail:toggle`. The state is written to
  `~/.config/guard-rail.json` rather than the plugin's `config.json`, which is
  versioned and replaced on upgrade. `GUARD_RAIL_OFF=1` still overrides both,
  for a single process.
- Turning the guard off is recorded rather than silent: a `toggled` event in the
  audit log, a line in the transcript at `SessionStart`, and a failed check in
  `guard-rail doctor`. A window with no redactions can now be told apart from a
  window with no protection.
- `tests/test_state.py`, asserting that disabled really means disabled (the
  prompt hook passes PII through, the tool hook stops rewriting), that enabling
  restores both, that the personal config file survives a toggle with its
  `client_terms` intact, and that a corrupted config leaves the guard on.

### Fixed

- The audit log suite no longer depends on Ollama being absent. It asserted a
  degraded-control event carrying an "Ollama unreachable" note, which held in CI
  and failed on any machine where Ollama was actually running — there the model
  replied with something that was not JSON, a different degradation with a
  different note. The test now forces the failure by pointing the host at a
  closed port, so it proves the same thing in both environments, and stops
  making a live model call.

## [2.1.0] - 2026-09-07

### Added

- Skill `guard-rail`, teaching the model how to read redacted output: that a
  pseudonym is a stable identifier rather than missing data, that it must not
  try to recover the underlying value, and that the absence of pseudonyms does
  not prove a result is clean.
- Slash commands `/guard-rail:doctor`, `/guard-rail:log` and `/guard-rail:map`.
- `guard-rail doctor`, which reports what is actually working rather than what
  should work: Python version, Ollama reachability, config state, a detection
  self-test, and — from the audit log — which hooks have genuinely fired.
- `SessionStart` heartbeat writing an `armed` event. It protects nothing; it
  exists so `doctor` can distinguish "no personal data was found" from "the
  redaction hook never ran on this surface".

### Fixed

- Compatibility with Python 3.9, the interpreter macOS ships. The modules used
  `list[str] | None` annotations, which are a syntax error before 3.10 — the
  plugin would have failed on every prompt. All modules now use
  `from __future__ import annotations`.
- `owner.url` and `author.url` added to the manifests, matching the reference
  plugins.

### Changed

- `llm_on_tool_output` defaults to `false`. The local-model layer had never been
  measured; enabling it by default meant paying unquantified latency on every
  MCP result.
- `client_terms` ships empty. Client names are exactly the data this tool
  protects, and a versioned config file is the wrong place for them — put them
  in `~/.config/guard-rail.json`, which overrides and never enters the repo.

## [2.0.0] - 2026-09-07

Redaction replaces blocking as the primary mechanism.

### Added

- `PostToolUse` hook redacting personal data in tool results via
  `hookSpecificOutput.updatedToolOutput`. Tool results reach the model with
  values replaced, so work continues instead of stopping.
- Session-stable reversible pseudonyms (`EMAIL_001`, `CPF_002`). The same value
  always receives the same label, so the model can still reason about which
  rows belong to the same entity. Formatting is normalised, so `529.982.247-25`
  and `52998224725` share a label.
- JSONL audit log recording every violation with an ISO 8601 timestamp,
  severity, and the exact violation point. It stores pseudonyms, never real
  values — a log holding the data would be a worse repository than the original,
  because it grows without bound and nobody remembers it exists.
- `guard-rail` console: `log`, `map`, `local`, `purge`.

### Changed

- Renamed from `lgpd-guard` to `guard-rail`.
- Detection returns positional spans rather than a verdict, which is what makes
  substitution possible.

### Fixed

- Pseudonym numbering followed substitution order (right to left), so the last
  occurrence in a text became `_001`. Labels are now assigned in reading order.
- Redaction was quadratic in input size: 200 KB took 552 ms, because overlap
  checks scanned a growing list and each substitution copied the whole string.
  An occupancy bytearray and single-pass assembly bring the same input to 62 ms.

## [1.0.0] - 2026-09-07

### Added

- `UserPromptSubmit` hook blocking prompts containing personal data. This hook
  cannot rewrite prompt text — no `updatedPrompt` field exists — so blocking is
  the only available action, with an `!ok` prefix as a deliberate override.
- Regex detection with check-digit validation for CPF, CNPJ, NIF, IBAN and
  payment cards. Validation is not decoration: without it, SAP document numbers
  would be flagged constantly and the guard would be switched off within a day.
- Allowlist protecting SAP identifiers — supplier and document numbers, purchase
  orders, transports, ABAP objects — from being treated as personal data.
- Optional classification through a local model served by Ollama.

[2.1.0]: https://github.com/williansaez/guard-rail/releases/tag/v2.1.0
[2.0.0]: https://github.com/williansaez/guard-rail/releases/tag/v2.0.0
[1.0.0]: https://github.com/williansaez/guard-rail/releases/tag/v1.0.0
