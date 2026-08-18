# Product specification

## Product statement

DevDNA converts public GitHub project evidence into an understandable developer profile. It helps developers improve their GitHub presence and identify role-specific portfolio gaps. A later recruiter workspace will compare candidates transparently; it must support human review, not automated hiring decisions.

## Release 1: developer analysis

**Input:** public GitHub username and a target role.

**Output:** an evidence-backed report containing:

- Relevant repositories selected for review.
- Proven technologies and engineering practices.
- Strengths and missing evidence against a role rubric.
- Practical, prioritised improvement actions.
- A source link for each claim.

Supported initial target role: `python_backend_developer`. Add roles only when their rubric and evidence rules are defined. The React frontend role `frontend_react_developer` is now supported with its own versioned rubric and evidence rules.

## Original release 1 non-goals

These constraints defined the first delivery. CV evidence alignment and recruiter batch comparison
were subsequently added as bounded, owner-scoped milestones; persistent CV storage and autonomous
hiring decisions remain out of scope.

- Private repository analysis.
- Persistent CV upload storage or treating CV statements as verified evidence.
- Automated profile README publishing to GitHub.
- Autonomous candidate acceptance, rejection, or protected-trait inference.
- A universal developer score.

## Evidence policy

DevDNA may report only facts it can source from GitHub metadata or repository files. The system may infer a skill only when a rule identifies evidence, for example:

- Python dependency file and Python source code.
- FastAPI dependency plus an API route structure.
- Tests directory plus a recognised test framework/configuration.
- GitHub Actions workflow.
- Dockerfile or Compose configuration.

An LLM may write summaries and suggestions, but it cannot add facts, skills, or projects that are absent from the evidence store.

## Quality bar

- Every report is reproducible from a saved analysis snapshot.
- Every user-facing conclusion explains its evidence.
- A failed repository fetch produces a partial report and a visible warning, never fabricated data.
- Analysis is asynchronous and idempotent.
