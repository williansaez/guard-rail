# Security policy

guard-rail sits between your tools and a language model, deciding which personal
data the model is allowed to see. When it works, values are replaced before they
reach the model. When it fails, they are not — and the failure is invisible.

That asymmetry is the whole security story of this project. A tool people trust
to redact, which quietly stops redacting, is more dangerous than no tool at all:
it converts caution into confidence without earning it. Everything below exists
to keep you from being in that position without knowing it.

## Supported versions

| Version | Supported |
|---|---|
| 2.1.x | Yes |
| 2.0.x and earlier | No |

Only the newest minor release receives fixes. Nothing is backported.

## Reporting a vulnerability

Report through GitHub private vulnerability reporting on this repository
(Security tab, "Report a vulnerability"). That channel is private.

There is no security email and no PGP key. If the Security tab is not offered to
you, open a public issue saying nothing more than "security, please contact me",
and wait for a private follow-up. Put no detail in that issue.

**Never include real personal data in a report.** A CPF with a valid check digit,
a real email address, a client name — none of these are needed to reproduce
anything. Use `529.982.247-25` (a well-known test value), `Northwind`, and
`joao.silva@example.pt`. A report that leaks the data this tool exists to protect
is worse than the bug it describes.

A useful report contains the plugin version, the surface (Claude Code CLI or
Cowork), the tool involved, the shape of the input, and what the model received.

## What this tool protects

- **Tool results.** `PostToolUse` inspects results from MCP servers, `Read`,
  `Grep` and shell commands, replacing detected personal data with stable
  pseudonyms before the model sees them.
- **Your own prompts.** `UserPromptSubmit` blocks a prompt containing personal
  data. It cannot rewrite it — the hook API offers no such field — so blocking
  is the only available action.

Detected values never leave the machine. The pseudonym map and the audit log are
local files with `0600` permissions. The optional classification layer runs
against a local Ollama instance; nothing is sent to a third party.

## What this tool does not protect

Read this section before relying on it.

**Names are not detected by default.** Detection is regex with check-digit
validation: CPF, CNPJ, NIF, IBAN, payment cards, email addresses, phone numbers,
postal addresses. A person's name in a free-text column has no structure to
match. It passes through untouched unless you list it in `client_terms` or enable
`llm_on_tool_output`.

The consequence is worth stating plainly: **the absence of pseudonyms in a result
does not mean the result was clean.** It means nothing matched.

**Large results pass uninspected.** Above `max_output_chars` (400,000 by default)
the hook gives up, logs a `not_redacted` event and lets the result through. A
large table export defeats the tool entirely. Check `guard-rail log --leaks`.

**Tool arguments are not filtered.** A CPF inside a `WHERE` clause sent to a
remote MCP server leaves the machine. `PreToolUse` redaction is not implemented.

**The local-model layer is probabilistic.** When enabled, it catches names the
regex cannot — sometimes. It is reinforcement, not a guarantee. The auditable
layer is the regex with check digits.

**The pseudonym map holds the real values.** That is the price of reversibility.
`~/.cache/guard-rail/map-*.json`, mode `0600`. Treat it as you would a database
export, and run `guard-rail purge` regularly.

**Silent failure is possible.** If the plugin is installed but its hooks never
fire — a surface that does not support them, a Python that cannot load the
modules — nothing warns you. This is the most serious failure mode, and the
reason `SessionStart` writes an `armed` event: `guard-rail doctor` compares
those against actual redaction events and tells you when protection is not
running. **Run it after installing, and after any upgrade.**

## Threat model

**In scope.** Accidental exposure of personal data to a model provider during
ordinary work: a query returning customer rows, a file containing contact
details, a prompt written without thinking. The user is not an adversary; they
want the protection and would rather not think about it.

**Out of scope.** A user deliberately bypassing the guard — `!ok`, disabling the
plugin, `GUARD_RAIL_OFF=1`, pasting data into a surface the hooks do not cover.
These overrides exist on purpose; the tool is a guard rail, not a cage.

Also out of scope: a compromised machine (the map and log are readable by
anything running as you), a malicious MCP server, and the model provider's own
handling of data that legitimately reached it.

**Assumed trustworthy.** The local Ollama instance, the filesystem permissions
model, and the host's hook implementation.

## Log and map hygiene

The audit log records pseudonyms, never real values — deliberately, so it cannot
become a personal-data repository itself. The map is the opposite: it exists to
hold real values, and is the sensitive file.

```bash
guard-rail purge 7     # drop maps and stashed prompts older than 7 days
```

`purge` prunes the log by date rather than deleting it; keeping the violation
history is its purpose.

## Compliance

This tool is a technical control, not compliance advice, and not a legal opinion.
It reduces the chance of personal data reaching a model provider. It does not
make any particular processing lawful under the LGPD or the GDPR, does not
constitute anonymisation in the legal sense — pseudonymised data remains personal
data under GDPR Article 4(5), because the map that reverses it exists on your
disk — and does not substitute for a data processing agreement with your model
provider. Talk to whoever owns data protection at your organisation.
