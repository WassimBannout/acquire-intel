# ADR-0002: Scrapy as the crawl backbone; Playwright for JS rendering

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Architect, Acquisition Engineer
- **Related:** docs/02 §6, docs/04, ADR-0005, PRD FR-1/FR-3

## Context
We need concurrent, polite crawling with a natural place to insert a resilience layer, plus
the ability to render JS-heavy pages. The target role names Scrapy, Playwright, Selenium,
and Puppeteer.

## Decision
We will use **Scrapy** as the crawl engine (scheduler, concurrency, **downloader
middlewares**, item pipelines) and **Playwright** (via `scrapy-playwright`) for JS-rendered
pages. We standardize on Playwright over Selenium/Puppeteer for the browser tier.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Scrapy + Playwright (chosen) | Middleware seam for anti-bot; concurrency/politeness built-in; modern browser automation; matches role | Two moving parts to learn |
| requests + BeautifulSoup | Simple | No scheduler/concurrency/middleware seam; reinvents Scrapy; weaker role fit |
| Selenium/Puppeteer alone | Browser control | No crawl framework; heavier; Playwright is the modern choice |

## Consequences
- Positive: the resilience layer lives as Scrapy middlewares benefiting all requests;
  Playwright covers JS pages; directly evidences the role's toolchain.
- Negative: Playwright needs browser binaries (handled in Docker/CI).
- Follow-up: `scrapy-playwright` config; per-source choice of plain vs. Playwright request.

## Notes
Selenium/Puppeteer parity can be mentioned in the README for completeness, but we implement
one browser tier (Playwright) to keep scope tight.
