"""Compare saved document parses with the native Omni Parse Bench scorer."""

from .core import evaluate, load_json

__all__ = ["evaluate", "load_json"]
