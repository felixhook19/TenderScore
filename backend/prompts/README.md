# Prompt registry artefacts

Prompts are versioned, hashed YAML artefacts — never inline strings
(CLAUDE.md rule 2). Each file declares `id`, `version`, `purpose`,
`output_schema` and `instruction_template` per `docs/architecture.md`
Part E.

On application start, files in this directory are hashed and reconciled
against the `prompt_registry` table; a changed file without a version bump
fails startup. Prompt changes go through PR review plus the red-team and
regression suites — **prompts are code**.

Empty at M0; the registry loader and first artefacts land in M4.
