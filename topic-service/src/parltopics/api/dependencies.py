"""Composition root: builds the adapters once and hands services to the routes.

This is the only module that knows which adapter implements which port.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from ..adapters.apertus import ApertusKeywordWriter, ApertusQueryTranslator
from ..adapters.bodies import load_parliaments
from ..adapters.files import FileTextExtractor
from ..adapters.jev import JevRelevanceRanker, JevSimilarityRanker, JevTopicClassifier
from ..adapters.labels import LabelledDataLabels
from ..adapters.openparldata import OpenParlDataClient
from ..adapters.taxonomies import LabelledDataTaxonomies
from ..config import Settings, get_settings
from ..services.classify import ClassificationService
from ..services.documents import DocumentResolver
from ..services.search import SearchService
from ..services.similar import SimilarCasesService

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    taxonomies: LabelledDataTaxonomies
    resolver: DocumentResolver
    parliaments: dict[str, dict]
    search: SearchService | None  # needs an Apertus key
    classification: ClassificationService | None  # needs a TypeSafe key
    similar: SimilarCasesService | None = None  # needs an Apertus key; ranking needs a TypeSafe key


@asynccontextmanager
async def build_container(settings: Settings | None = None) -> AsyncIterator[Container]:
    settings = settings or get_settings()
    async with AsyncExitStack() as stack:
        opd_http = await stack.enter_async_context(
            httpx.AsyncClient(timeout=settings.openparldata_timeout_s, headers={"User-Agent": "parltopics/0.1"})
        )
        openparldata = OpenParlDataClient(
            opd_http, base_url=settings.openparldata_base_url, site_url=settings.openparldata_site_url
        )
        taxonomies = LabelledDataTaxonomies(settings.data_dir)
        resolver = DocumentResolver(openparldata, FileTextExtractor())
        parliaments = load_parliaments(settings.bodies_file)

        jev_client = None
        if settings.typesafe_api_key:
            jev_client = await stack.enter_async_context(
                AsyncTypeSafeClient(
                    api_key=settings.typesafe_api_key.get_secret_value(),
                    model=settings.typesafe_model,
                    timeout=settings.typesafe_timeout_s,
                    retry=RetryPolicy(max_retries=4),
                )
            )

        classification = None
        ranker = None
        if jev_client is not None:
            classifier = JevTopicClassifier(
                jev_client,
                model=settings.typesafe_model,
                max_concurrency=settings.typesafe_max_concurrency,
                max_section_chars=settings.max_section_chars,
                max_state_chars=settings.max_state_chars,
            )
            classification = ClassificationService(classifier, taxonomies)
            ranker = JevRelevanceRanker(jev_client, model=settings.typesafe_model)

        search = None
        similar = None
        if settings.apertus_api_key:
            apertus_http = await stack.enter_async_context(httpx.AsyncClient(timeout=settings.apertus_timeout_s))
            translator = ApertusQueryTranslator(
                apertus_http,
                base_url=settings.apertus_base_url,
                api_key=settings.apertus_api_key.get_secret_value(),
                model=settings.apertus_model,
            )
            search = SearchService(translator, openparldata, ranker)
            writer = ApertusKeywordWriter(
                apertus_http,
                base_url=settings.apertus_base_url,
                api_key=settings.apertus_api_key.get_secret_value(),
                model=settings.apertus_model,
                parliaments=parliaments,
            )
            similarity = None
            if jev_client is not None:
                similarity = JevSimilarityRanker(
                    jev_client,
                    model=settings.typesafe_model,
                    parliaments=parliaments,
                    max_section_chars=settings.max_section_chars,
                    max_state_chars=settings.max_state_chars,
                )
            similar = SimilarCasesService(writer, openparldata, similarity, _labels(settings, taxonomies))

        yield Container(settings, taxonomies, resolver, parliaments, search, classification, similar)


def _labels(settings: Settings, taxonomies: LabelledDataTaxonomies) -> LabelledDataLabels | None:
    """Labels for similar cases. Optional: without the labelled data, cases come without labels."""
    try:
        return LabelledDataLabels(settings.data_dir, taxonomies)
    except Exception as error:  # noqa: BLE001
        log.warning("Labels for similar cases are off: %s", error)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with build_container() as container:
        app.state.container = container
        yield


def container(request: Request) -> Container:
    return request.app.state.container


def search_service(request: Request) -> SearchService:
    service = container(request).search
    if service is None:
        raise HTTPException(503, "Search needs APERTUS_API_KEY in .env")
    return service


def classification_service(request: Request) -> ClassificationService:
    service = container(request).classification
    if service is None:
        raise HTTPException(503, "Classification needs TYPESAFE_API_KEY in .env")
    return service


def similar_service(request: Request) -> SimilarCasesService:
    service = container(request).similar
    if service is None:
        raise HTTPException(503, "Similar cases need APERTUS_API_KEY in .env")
    return service


def document_resolver(request: Request) -> DocumentResolver:
    return container(request).resolver
