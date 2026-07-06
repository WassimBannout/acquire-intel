"""Three-kinds parity — the M2 gate (T2.3, docs/02 §5, plan/milestones.md M2).

Proves the headline M2 claim: **REST, HTML, and GraphQL extractors all feed the identical
pipeline + storage**, producing canonical products with no source-specific logic leaking into
the shared layers.

Two complementary proofs:

1. ``test_fixture_set_produces_canonical_products`` — parameterized over all three kinds: each
   source's checked-in fixture is parsed by its own extractor → ``RawProduct``s, then driven
   through the **one** shared path (``normalize`` → ``ProductRepository.upsert`` /
   ``PriceObservationRepository.append``) into Postgres, and asserted to yield canonical
   ``{source}:{external_id}`` products + immutable observations with ``Decimal`` money. The
   ingest code is a single function parameterized only by per-source config — the same code
   normalizes and stores all three kinds.
2. ``test_shared_layers_are_source_agnostic`` — a fast structural guard (no DB): the shared
   pipeline/storage modules import nothing from ``acquisition.sources`` and name no concrete
   source, so no per-kind branch can hide there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from scrapy.http import HtmlResponse, Request, TextResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.acquisition.sources.demo_graphql import DemoGraphqlExtractor
from acquire_intel.acquisition.sources.demo_html import DemoHtmlExtractor
from acquire_intel.acquisition.sources.demo_rest import DemoRestExtractor
from acquire_intel.config import ConfigError
from acquire_intel.pipeline.normalize import normalize
from acquire_intel.storage import (
    CrawlRunRepository,
    PriceObservationRepository,
    ProductRepository,
    Source,
    SourceRepository,
    get_engine,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy import Engine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


# --- per-kind fixture → RawProduct builders ----------------------------------
#
# Each builder parses a source's checked-in fixture with its *own* extractor, exactly as the
# Scrapy engine would deliver the response. Everything downstream is shared.


def _rest_raw_products() -> list[RawProduct]:
    extractor = DemoRestExtractor(base_url="https://shop.example.com")
    payload = json.loads((_FIXTURES / "demo_rest" / "valid_payload.json").read_text())
    url = extractor._page_url(1)
    response = TextResponse(
        url=url,
        body=json.dumps(payload).encode(),
        encoding="utf-8",
        request=Request(url, meta={"page": 1}),
    )
    return [r for r in extractor.parse(response) if isinstance(r, RawProduct)]


def _html_raw_products() -> list[RawProduct]:
    extractor = DemoHtmlExtractor(base_url="https://demo-html.example.com")
    html = (_FIXTURES / "demo_html" / "rendered.html").read_text()
    response = HtmlResponse(url=extractor._listing_url(), body=html.encode(), encoding="utf-8")
    return [r for r in extractor.parse(response) if isinstance(r, RawProduct)]


def _graphql_raw_products() -> list[RawProduct]:
    extractor = DemoGraphqlExtractor(base_url="https://graphql.example.com")
    payload = json.loads((_FIXTURES / "demo_graphql" / "response_page1.json").read_text())
    request = extractor._graphql_request(after=None)
    response = TextResponse(
        url=extractor._endpoint,
        body=json.dumps(payload).encode(),
        encoding="utf-8",
        request=request,
    )
    return [r for r in extractor.parse(response) if isinstance(r, RawProduct)]


@dataclass(frozen=True)
class ParityCase:
    source_id: str
    kind: str
    base_url: str
    default_currency: str
    build: Callable[[], list[RawProduct]]


_CASES = [
    ParityCase("demo_rest", "rest", "https://shop.example.com", "USD", _rest_raw_products),
    ParityCase("demo_html", "html", "https://demo-html.example.com", "EUR", _html_raw_products),
    ParityCase(
        "demo_graphql", "graphql", "https://graphql.example.com", "USD", _graphql_raw_products
    ),
]


# --- DB fixtures (skip cleanly without Postgres) ------------------------------


@pytest.fixture(scope="module")
def engine() -> Engine:
    try:
        eng = get_engine()
        with eng.connect():
            pass
    except (ConfigError, OperationalError) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"Postgres not available: {exc}")
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session on an outer transaction rolled back after the test (no residue)."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        transaction.rollback()
        connection.close()


def _seed_source(session: Session, case: ParityCase) -> None:
    SourceRepository(session).add(
        Source(
            id=case.source_id,
            kind=case.kind,
            base_url=case.base_url,
            stale_after_seconds=21600,
            crawl_policy={"default_currency": case.default_currency},
        )
    )


def _ingest(session: Session, case: ParityCase, raws: list[RawProduct], run_id: str) -> None:
    """The one shared ingest path — identical for every kind, config the only variable."""
    captured_at = datetime.now(UTC)
    for raw in raws:
        item = normalize(
            raw,
            source_id=case.source_id,
            run_id=run_id,
            captured_at=captured_at,
            default_currency=case.default_currency,
        )
        ProductRepository(session).upsert(item.product)
        PriceObservationRepository(session).append(item.observation)


# --- the parity proof ---------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("case", _CASES, ids=[c.kind for c in _CASES])
def test_fixture_set_produces_canonical_products(session: Session, case: ParityCase) -> None:
    raws = case.build()
    assert raws, f"{case.kind} fixture yielded no RawProducts"

    _seed_source(session, case)
    run_id = f"parity-{case.kind}"
    CrawlRunRepository(session).open(
        run_id=run_id, source_id=case.source_id, started_at=datetime.now(UTC)
    )

    _ingest(session, case, raws, run_id)
    session.expire_all()  # read committed DB state, not the identity map

    products = ProductRepository(session)
    observations = PriceObservationRepository(session)

    # Every RawProduct became one canonical product + one immutable observation, and the
    # canonical shape is identical across kinds (id scheme, Decimal money, ISO currency).
    for raw in raws:
        canonical_id = f"{case.source_id}:{raw.external_id}"
        product = products.get(canonical_id)
        assert product is not None, f"{canonical_id} not persisted"
        assert product.source_id == case.source_id
        assert product.external_id == raw.external_id
        assert product.title  # non-empty after normalization

        history = observations.list_for(canonical_id)
        assert len(history) == 1
        (obs,) = history
        assert isinstance(obs.amount, Decimal)
        assert obs.amount >= 0
        assert len(obs.currency) == 3 and obs.currency.isalpha()
        assert obs.run_id == run_id

    assert products.count() == len(raws)


def test_shared_layers_are_source_agnostic() -> None:
    """No concrete source name or ``acquisition.sources`` import in the shared pipeline/storage."""
    root = Path(__file__).resolve().parent.parent / "src" / "acquire_intel"
    shared = [
        root / "pipeline" / "normalize.py",
        root / "pipeline" / "item_pipeline.py",
        root / "pipeline" / "persistence.py",
        root / "storage" / "repositories.py",
    ]
    concrete_sources = ("demo_rest", "demo_html", "demo_graphql", "acquisition.sources")
    for module in shared:
        text = module.read_text()
        for needle in concrete_sources:
            assert needle not in text, f"{module.name} leaks source-specific reference: {needle!r}"
