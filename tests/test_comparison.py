"""Native-scoring behavior, failure accounting, validation and report safety."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ocr_slices import evaluate, load_json
from ocr_slices.__main__ import main
from ocr_slices.report import render

ROOT = Path(__file__).resolve().parents[1]


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_json(ROOT / "examples/dataset.json")
        self.predictions = load_json(ROOT / "examples/predictions.json")

    def row(self, name="simulated-complete", tags=None):
        result = evaluate(self.dataset, self.predictions, tags)
        return next(r for r in result["parsers"] if r["parser"] == name)

    def test_all_five_native_check_types_pass(self):
        row = self.row()
        self.assertEqual((row["headline"], row["passed"], row["tests"]), (1, 12, 12))
        self.assertEqual({d["test_type"] for d in row["details"]},
                         {"present", "order", "repeat", "table_cell", "layout_kind"})

    def test_family_mean_is_not_flat_test_mean(self):
        row = self.row("simulated-table-focused")
        self.assertAlmostEqual(row["headline"], (3/8 + 1 + 2/3)/3)
        self.assertNotEqual(row["headline"], row["passed"]/row["tests"])

    def test_missing_and_error_pages_lower_coverage(self):
        row = self.row("simulated-incomplete")
        self.assertAlmostEqual(row["coverage"], 1/3)
        self.assertAlmostEqual(row["headline"], 1/3)
        self.assertEqual((row["failed"], row["tests"], row["passed"]), (2, 12, 5))
        self.assertEqual(len(row["failures"]), 2)
        self.assertEqual(sum(d["result"] == "fail" for d in row["details"]), 7)

    def test_tag_slice_keeps_failed_page_in_denominator(self):
        row = self.row("simulated-incomplete", ["handwriting"])
        self.assertEqual((row["headline"], row["coverage"], row["pages"], row["tests"]), (0, 0, 1, 4))

    def test_tag_and_selects_intersection(self):
        row = self.row(tags=["handwriting", "heading"])
        self.assertEqual((row["tests"], row["documents"]), (1, 1))
        self.assertEqual(set(row["scored"]["families"]), {"layout"})

    def test_no_intersection_has_null_scores(self):
        row = self.row(tags=["table", "handwriting"])
        self.assertEqual((row["pages"], row["tests"]), (0, 0))
        self.assertIsNone(row["headline"])
        self.assertIsNone(row["coverage"])

    def test_unknown_tags_refused(self):
        with self.assertRaisesRegex(ValueError, "absent"):
            self.row(tags=["nonexistent"])

    def test_nonlist_tags_refused(self):
        with self.assertRaisesRegex(ValueError, "list"):
            self.row(tags="table")

    def test_missing_layout_fails_native_checks_but_page_answered(self):
        del self.predictions["parsers"]["simulated-complete"]["ledger-p1"]["pages"][0]["blocks"]
        row = self.row()
        self.assertEqual((row["failed"], row["coverage"], row["passed"]), (0, 1, 11))
        self.assertTrue(any("no blocks output" in d["why"] for d in row["details"]))

    def test_malformed_output_fails_only_that_output_checks(self):
        self.predictions["parsers"]["simulated-complete"]["ledger-p1"]["pages"][0]["html"] = 12
        row = self.row()
        self.assertEqual((row["failed"], row["passed"]), (0, 8))

    def test_malformed_native_page_wrapper_counts_failure(self):
        self.predictions["parsers"]["simulated-complete"]["ledger-p1"] = {"pages": [{}, {}]}
        row = self.row()
        self.assertEqual(row["failed"], 1)
        self.assertAlmostEqual(row["coverage"], 2/3)

    def test_all_failed_scores_zero(self):
        self.predictions = {"parsers": {"empty": {}}}
        row = self.row("empty")
        self.assertEqual((row["headline"], row["coverage"], row["failed"]), (0, 0, 3))
        self.assertIsNone(row["scored"]["headline"])

    def test_document_denominators_use_distinct_documents(self):
        self.dataset["pages"][1]["document"] = "ledger"
        row = self.row()
        self.assertEqual(row["documents"], 2)
        self.assertEqual(row["scored"]["families"]["text"]["documents"], 2)

    def test_duplicate_page_refused(self):
        self.dataset["pages"].append(copy.deepcopy(self.dataset["pages"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate page"):
            self.row()

    def test_duplicate_test_refused(self):
        self.dataset["pages"][1]["gold"]["tests"][0]["id"] = "ledger-cell"
        with self.assertRaisesRegex(ValueError, "duplicate test"):
            self.row()

    def test_invalid_gold_uses_native_validation(self):
        self.dataset["pages"][0]["gold"]["tests"][0]["settings"] = {"unexpected": 4}
        with self.assertRaisesRegex(ValueError, "settings"):
            self.row()

    def test_unknown_prediction_page_refused(self):
        self.predictions["parsers"]["simulated-complete"]["typo"] = {"pages": [{}]}
        with self.assertRaisesRegex(ValueError, "unknown pages"):
            self.row()

    def test_empty_gold_refused(self):
        self.dataset["pages"][0]["gold"]["tests"] = []
        with self.assertRaisesRegex(ValueError, "contain tests"):
            self.row()

    def test_json_duplicate_and_nonfinite_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for content in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":-1e999}'):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_json(path)

    def test_report_escapes_all_external_text(self):
        self.dataset["description"] = '<script>alert("x")</script>'
        self.predictions["parsers"]['<img src=x onerror=alert(1)>'] = {
            "ledger-p1": {"error": "<iframe src=https://evil.invalid>"}}
        output = render(evaluate(self.dataset, self.predictions))
        self.assertNotIn("<script>", output)
        self.assertNotIn("<img ", output)
        self.assertNotIn("<iframe ", output)
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("Content-Security-Policy", output)

    def test_no_network_during_native_scoring(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.assertEqual(self.row()["passed"], 12)

    def test_cli_writes_json_html_and_refuses_input_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            out = Path(directory)
            args = ["--dataset", str(ROOT / "examples/dataset.json"), "--predictions",
                    str(ROOT / "examples/predictions.json")]
            self.assertEqual(main(args + ["--json", str(out / "report.json"), "--html", str(out / "report.html")]), 0)
            self.assertEqual(load_json(out / "report.json")["parsers"][0]["passed"], 12)
            self.assertTrue((out / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>"))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args + ["--json", str(ROOT / "examples/dataset.json")]), 2)


if __name__ == "__main__":
    unittest.main()
