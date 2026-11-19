"""Pytest configuration and corpus test filtering."""

import os
import pytest


def pytest_addoption(parser):
    """Add custom CLI options to pytest."""
    parser.addoption(
        "--corpus",
        action="store_true",
        default=False,
        help="Run local corpus acceptance tests requiring private/raw/",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "corpus: mark test as requiring local private/raw/ corpus files",
    )


def pytest_collection_modifyitems(config, items):
    """Skip corpus tests unless explicitly requested via --corpus or RUN_CORPUS_TESTS=1."""
    run_corpus = config.getoption("--corpus") or bool(os.environ.get("RUN_CORPUS_TESTS"))
    if run_corpus:
        return

    skip_corpus = pytest.mark.skip(
        reason="Local corpus test skipped (enable with --corpus or RUN_CORPUS_TESTS=1)"
    )
    for item in items:
        if "corpus" in item.keywords:
            item.add_marker(skip_corpus)
