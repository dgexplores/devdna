# DevDNA

Evidence-based developer intelligence for developers and hiring teams.

DevDNA analyzes meaningful GitHub project evidence—such as tests, CI, documentation, APIs, databases, and deployment configuration—to produce explainable role-alignment reports, improvement roadmaps, and README drafts. It does not treat commit counts, contribution streaks, stars, or followers as skill scores.

## First release

`GitHub username + target role → explainable developer report`

The report must identify every strength, gap, and recommendation with the repository evidence that supports it.

## Repository layout

```text
apps/api/       FastAPI service and HTTP endpoints
apps/worker/    background GitHub-analysis jobs
docs/           product, architecture, security, and delivery decisions
infra/          deployment and local-service configuration
tests/          cross-service tests
```

Read [the product specification](docs/PRODUCT_SPEC.md), [architecture](docs/ARCHITECTURE.md), and [delivery plan](docs/DELIVERY_PLAN.md) before implementation.
