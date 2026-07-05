"""Scaffolding: verifica che tutti i package top-level del repo siano
importabili (pythonpath src/ configurato correttamente in pyproject.toml)."""

from __future__ import annotations


def test_all_top_level_packages_import():
    import components  # noqa: F401
    import forecasts  # noqa: F401
    import regime  # noqa: F401
    import report  # noqa: F401
    import risk  # noqa: F401
