# Contributing

## Running the tests

No dependencies, no build step. Python 3.9 or newer:

```bash
python3 tests/test_detectors.py   # detection and false positives
python3 tests/test_redact.py      # redaction, pseudonym stability, latency
python3 tests/test_auditlog.py    # audit log, filters, and PII absence
```

The hook tests spawn the hooks as subprocesses with a temporary `HOME`, so they
never touch a real pseudonym map or audit log.

CI runs all three on Python 3.9 through 3.13. The 3.9 job is not there for
completeness: it is what verifies that the plugin still loads on the interpreter
macOS ships, where a `list[str] | None` annotation is a syntax error.

## Adding a detector

Detectors live in `hooks/detectors.py`, in the `DETECTORS` list:

```python
("NIF/NIPC (PT)", "NIF", re.compile(r"\b\d{9}\b"), valid_nif, "ALTO"),
#  human label     prefix  pattern                  validator  severity
```

The validator is the part that matters. A nine-digit regex on its own would fire
on every counter, quantity and internal ID in a query result. `valid_nif` rejects
everything whose check digit does not hold, which is what makes the detector safe
to run against SAP data.

**A new numeric detector without a validator will be rejected.** Precision is not
a nicety here: a false positive replaces a document number with a pseudonym and
silently corrupts the result the model reasons about. Add cases to
`tests/test_detectors.py` on both sides — values that must be caught, and
near-misses with bad check digits that must not be.

Use a fictional client name in tests (`Northwind`), never a real one.

## Severity

- `ALTO` — identifies a natural person: name, national ID, contact details,
  address, health or financial data.
- `MEDIO` — identifies a company or commercial relationship, but not a person.
- `NENHUM` — technical identifiers, document numbers, code, table names.

When unsure between `ALTO` and `MEDIO`, consider what the label does. `ALTO`
blocks a prompt outright; `MEDIO` can be waived with `!ok`. Over-classifying
trains the user to reach for the override, which is worse than classifying
honestly.

## Performance

`PostToolUse` runs on every tool call, including every `Read` and every shell
command. The regex path costs about 0.02 ms and must stay that way. Before
changing `find_pii` or `redact_text`, run the latency table in
`tests/test_redact.py` and compare — it is there because two separate quadratic
bugs shipped and only that table caught them.

The local-model layer is off by default for the same reason. It is not free, and
a privacy tool people disable because it is slow protects nothing.

## Reporting problems

Bugs and feature requests: GitHub issues.

Security problems, including any case where personal data reached the model
unredacted: see [SECURITY.md](SECURITY.md). Do not put real personal data in an
issue — placeholders and pseudonyms are enough to reproduce anything.
