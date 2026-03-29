"""Backward-compatible re-export from typesense_indexer."""

from modules.search.typesense_indexer import (  # noqa: F401
    MeiliIndexer,
    TypesenseIndexer,
    build_person_doc,
    meili_indexer,
    typesense_indexer,
)
