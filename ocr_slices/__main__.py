"""Command-line entry point for local saved-prediction comparisons."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .core import evaluate, load_json
from .report import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare saved OCR predictions using native deterministic checks.")
    parser.add_argument("--dataset", type=Path, default=Path("examples/dataset.json"))
    parser.add_argument("--predictions", type=Path, default=Path("examples/predictions.json"))
    parser.add_argument("--tag", action="append", default=[], help="Require this tag; repeated tags use AND")
    parser.add_argument("--json", type=Path, help="Write full machine-readable results")
    parser.add_argument("--html", type=Path, help="Write an escaped standalone HTML report")
    args = parser.parse_args(argv)
    try:
        inputs = {args.dataset.resolve(), args.predictions.resolve()}
        outputs = [p.resolve() for p in (args.json, args.html) if p]
        if len(outputs) != len(set(outputs)) or inputs.intersection(outputs):
            raise ValueError("output paths must differ from each other and from input files")
        result = evaluate(load_json(args.dataset), load_json(args.predictions), args.tag)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.html:
            args.html.parent.mkdir(parents=True, exist_ok=True)
            args.html.write_text(render(result), encoding="utf-8")
        print(json.dumps({"tags_all": result["tags_all"], "parsers": [
            {k: row[k] for k in ("parser", "headline", "coverage", "passed", "tests", "failed")}
            for row in result["parsers"]]}, indent=2))
    except (OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
