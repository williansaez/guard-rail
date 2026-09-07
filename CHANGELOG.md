# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
