"""Validate local inputs, run native unit tests, and aggregate selected slices."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from omni_parse_bench import data, errors
from omni_parse_bench.scorers import unit_tests

SOURCE_REVISION = "c4e40e352cfb84ec896a01c2788b3a650dd847a3"


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"nonfinite JSON number: {value}")
    return number


def load_json(path: Path | str) -> Any:
    """Read bounded UTF-8 JSON; duplicate keys and nonfinite numbers are invalid."""
    path = Path(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError(f"{path.name}: JSON exceeds the 10 MiB limit")
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_object, parse_float=_finite_float,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"invalid number: {x}")))


def _name(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a nonempty string")
    return value


def _dataset(raw: Any) -> list[tuple[data.Page, tuple]]:
    if not isinstance(raw, dict) or set(raw) != {"description", "pages"}:
        raise ValueError("dataset must contain exactly description and pages")
    _name(raw["description"], "description")
    if not isinstance(raw["pages"], list) or not raw["pages"]:
        raise ValueError("dataset pages must be a nonempty list")
    pages, page_ids, test_ids = [], set(), set()
    for entry in raw["pages"]:
        if not isinstance(entry, dict) or set(entry) != {"page_id", "document", "gold"}:
            raise ValueError("each page must contain exactly page_id, document, gold")
        page_id = _name(entry["page_id"], "page_id")
        document = _name(entry["document"], "document")
        if page_id in page_ids:
            raise ValueError(f"duplicate page_id: {page_id}")
        page_ids.add(page_id)
        tests = unit_tests.tests.parse(page_id, entry["gold"])
        if not tests:
            raise ValueError(f"{page_id}: gold must contain tests")
        for test in tests:
            if test.id in test_ids:
                raise ValueError(f"duplicate test id: {test.id}")
            test_ids.add(test.id)
        page = data.Page(page_id, document, "local", Path("unused.pdf"), Path("unused.json"),
                         tuple(sorted(unit_tests.tests.wants(tests))))
        pages.append((page, tests))
    return pages


def evaluate(dataset: Any, predictions: Any, tags: list[str] | None = None) -> dict[str, Any]:
    """Score each parser. Repeated tags mean AND; filters never change a verdict.

    The headline is the native mean of represented family scores on answered pages,
    multiplied by selected-page coverage. Failed pages remain in the denominator.
    No tests in a slice is represented by null scores, never a perfect zero-page run.
    """
    pages = _dataset(dataset)
    if not isinstance(predictions, dict) or set(predictions) != {"parsers"}:
        raise ValueError("predictions must contain exactly parsers")
    parsers = predictions["parsers"]
    if not isinstance(parsers, dict) or not parsers:
        raise ValueError("parsers must be a nonempty object")
    if tags is not None and (not isinstance(tags, list) or
                             any(not isinstance(tag, str) or not tag.strip() for tag in tags)):
        raise ValueError("tags must be a list of nonempty strings")
    wanted = set(tags or [])
    known_tags = {tag for _, tests in pages for test in tests for tag in test.tags}
    if wanted - known_tags:
        raise ValueError(f"tags absent from dataset: {sorted(wanted - known_tags)}")
    selected = [(page, tuple(t for t in tests if wanted <= set(t.tags))) for page, tests in pages]
    selected = [(page, tests) for page, tests in selected if tests]
    all_page_ids = {page.page_id for page, _ in pages}
    summaries = []
    scorer = unit_tests.UnitTests()
    for name, saved in parsers.items():
        _name(name, "parser name")
        if not isinstance(saved, dict):
            raise ValueError(f"{name}: saved pages must be an object")
        if unknown := set(saved) - all_page_ids:
            raise ValueError(f"{name}: unknown pages: {sorted(unknown)}")
        details, scored_lines, failures = [], [], []
        for page, tests in selected:
            prediction = saved.get(page.page_id)
            reason = None
            if prediction is None:
                reason = "missing prediction"
            elif isinstance(prediction, dict) and set(prediction) == {"error"}:
                reason = _name(prediction["error"], f"{name}/{page.page_id} error")
            if reason is None:
                try:
                    output = scorer.prediction(prediction)
                except errors.SystemFailed as exc:
                    reason = str(exc)
            if reason is not None:
                failures.append({"page_id": page.page_id, "document": page.document, "why": reason})
                vs = [unit_tests.Verdict(t.id, "fail", f"page failed: {reason}") for t in tests]
                details.extend(unit_tests.lines(vs, tests, page))
                continue
            lines = unit_tests.lines(unit_tests.score(output, tests), tests, page)
            scored_lines.extend(lines)
            details.extend(lines)
        native = unit_tests.summarize(scored_lines)
        population = unit_tests.summarize(details)
        rows = len(selected)
        answered = rows - len(failures)
        coverage = answered / rows if rows else None
        headline = ((native["headline"] or 0.0) * coverage) if rows else None
        summaries.append({"parser": name, "headline": headline,
                          "headline_is": "native scored family mean multiplied by page coverage",
                          "pages": rows, "answered": answered, "failed": len(failures),
                          "coverage": coverage, "documents": len({p.document for p, _ in selected}),
                          "tests": len(details), "passed": sum(d["result"] == "pass" for d in details),
                          "scored": native, "all_pages": population,
                          "failures": failures, "details": details})
    return {"description": dataset["description"], "source_revision": SOURCE_REVISION,
            "tags_all": sorted(wanted), "available_tags": sorted(known_tags),
            "note": "Saved predictions only; scores describe these inputs, not model performance.",
            "parsers": summaries}
