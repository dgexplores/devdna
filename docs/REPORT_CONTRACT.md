# Report contract

## Versions

- Schema: `1`
- Generator: `python-backend-report-v1`
- Evidence analyzer: `python-backend-evidence-v1`
- Rubric: `python_backend_developer:v1`

The report generator is deterministic. The same evidence snapshot and collection status produce the same report.

## Meaning

`requirements_met` is a transparent count of rubric requirements that have one or more matching evidence items. It is not a universal developer score and does not use repository popularity or activity.

The alignment label is derived only from requirement coverage:

- every requirement: `Well-evidenced role alignment`;
- at least half: `Developing role alignment`;
- fewer than half: `Foundational role alignment`.

## Strengths

A strength exists only when a rubric requirement matches persisted evidence. It includes:

- the rubric requirement and human-readable title;
- the repositories where the evidence was found;
- every supporting GitHub source link.

## Gaps and actions

A completed analysis describes an unmatched requirement as having no matching repository evidence. A partial analysis says the requirement was not verified in the available inspection data; it does not claim the developer lacks the skill.

Each gap receives one action in rubric order. The action explains what to build and the repository files DevDNA needs before it can verify that requirement.

## Surfaces

- `GET /v1/analyses/{analysis_id}/report` returns the typed JSON report.
- `GET /reports/{analysis_id}` renders the accessible web report.
- A queued or running JSON report returns `409`.
- A queued or running web report returns `202` and refreshes until the report is ready.
