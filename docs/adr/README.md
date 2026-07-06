# Architecture Decision Records

ADRs capture *why* a load-bearing decision was made, so future sessions don't re-litigate or
contradict them. Add one for any non-obvious, hard-to-reverse choice using
`templates/adr-template.md`. Never drift from an accepted ADR — supersede it.

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](0001-python-uv-monorepo.md) | Python 3.12 + uv, single src package | Accepted |
| [0002](0002-scrapy-plus-playwright.md) | Scrapy backbone + Playwright for JS | Accepted |
| [0003](0003-source-extractor-plugin.md) | Pluggable `SourceExtractor` (html/rest/graphql) | Accepted |
| [0004](0004-rest-and-graphql-extractors.md) | First-class REST + GraphQL extractors | Accepted |
| [0005](0005-antibot-resilience-strategy.md) | Anti-bot resilience as Scrapy middlewares | Accepted |
| [0006](0006-postgres-timeseries.md) | PostgreSQL + SQLAlchemy; append-only observations | Accepted |
| [0007](0007-flask-api-scheduler.md) | Flask API + Jinja/Chart.js + APScheduler | Accepted |
| [0008](0008-pydantic-validation-boundaries.md) | pydantic validation at every boundary | Accepted |
| [0009](0009-adversarial-test-harness.md) | Local adversarial mock server for anti-bot tests | Accepted |
| [0010](0010-normalization-and-dedup-policy.md) | Normalization (currency fallback, Decimal price) + in-run dedup | Accepted |

## Next likely ADRs (write when decided)
- Concrete v1 sources per technique (+ ToS review).
- Proxy provider abstraction / pool strategy.
- Timescale/partitioning if `price_observations` volume grows.
- Distributed/queue-backed crawling if single-node concurrency is outgrown.
