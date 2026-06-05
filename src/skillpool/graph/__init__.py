"""Graph module — Skill graph algorithms."""
from __future__ import annotations

__all__ = ["personalized_pagerank", "reverse_ppr"]


def __getattr__(name: str):
    """Lazy import — numpy/scipy are optional dependencies."""
    if name in ("personalized_pagerank", "reverse_ppr"):
        from skillpool.graph.ppr import personalized_pagerank, reverse_ppr  # noqa: F401
        return locals().get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
