#!/usr/bin/env python
"""Evaluate the merchant categorizer against hand-labeled descriptions.

Each description goes through the real pipeline order (normalize, then rules, then
the provider chosen by LLM_PROVIDER) with no cache and no database, so this runs
without Postgres. Provider calls use the pipeline's own batching, and Gemini's
timeout and retry.

    python eval/run_eval.py            # table in the terminal + eval/results/<provider>-<date>.md
    python eval/run_eval.py --json     # the same results as JSON on stdout

The labeled file is only ever read, never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
REPO_DIR = EVAL_DIR.parent
sys.path.insert(0, str(REPO_DIR / "backend"))

from app.categorization.categories import CATEGORIES, OTHER, REVIEW_THRESHOLD  # noqa: E402
from app.categorization.normalize import normalize_merchant  # noqa: E402
from app.categorization.pipeline import BATCH_SIZE, decide_categories  # noqa: E402
from app.categorization.providers import LLMProvider, Result, get_provider  # noqa: E402

LABELED_FILE = EVAL_DIR / "labeled_merchants.csv"
SHOULD_FLAG_FILE = EVAL_DIR / "should_flag.csv"
RESULTS_DIR = EVAL_DIR / "results"
TOP_CONFUSIONS = 10


# --- loading and validation -----------------------------------------------------


class EvalDataError(ValueError):
    """The labeled data is invalid. The message lists every problem found."""


@dataclass(frozen=True)
class LabeledRow:
    line: int
    description: str
    category: str


def load_labeled(path: Path) -> list[LabeledRow]:
    """Read description,category rows, rejecting unknown categories, blank and
    duplicate descriptions. Reports every problem at once, with line numbers."""
    rows, problems = [], []
    first_seen: dict[str, int] = {}
    for line, record in _read_csv(path, ["description", "category"]):
        description = (record.get("description") or "").strip()
        category = (record.get("category") or "").strip()
        if not description:
            problems.append(f"line {line}: blank description")
            continue
        if description in first_seen:
            problems.append(
                f"line {line}: duplicate description {description!r} "
                f"(first on line {first_seen[description]})"
            )
            continue
        first_seen[description] = line
        if category not in CATEGORIES:
            problems.append(
                f"line {line}: category {category!r} for {description!r} is not one of: "
                + ", ".join(CATEGORIES)
            )
            continue
        rows.append(LabeledRow(line, description, category))
    _raise_if(problems, path)
    if not rows:
        raise EvalDataError(f"{path}: no labeled rows")
    return rows


def load_should_flag(path: Path) -> list[str]:
    """Read the one-column list of descriptions that ought to be flagged for review."""
    descriptions, problems = [], []
    first_seen: dict[str, int] = {}
    for line, record in _read_csv(path, ["description"]):
        description = (record.get("description") or "").strip()
        if not description:
            problems.append(f"line {line}: blank description")
        elif description in first_seen:
            problems.append(
                f"line {line}: duplicate description {description!r} "
                f"(first on line {first_seen[description]})"
            )
        else:
            first_seen[description] = line
            descriptions.append(description)
    _raise_if(problems, path)
    return descriptions


def _read_csv(path: Path, columns: list[str]):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [name.strip() for name in reader.fieldnames or []]
        if header != columns:
            raise EvalDataError(f"{path}: expected columns {columns}, found {header}")
        reader.fieldnames = header
        for line, record in enumerate(reader, start=2):
            if None in record:  # more fields than columns, e.g. an unquoted comma
                raise EvalDataError(f"{path}: line {line} has too many fields")
            yield line, record


def _raise_if(problems: list[str], path: Path) -> None:
    if problems:
        raise EvalDataError(f"{path}: {len(problems)} problem(s)\n  " + "\n  ".join(problems))


# --- running ----------------------------------------------------------------------


@dataclass(frozen=True)
class Prediction:
    description: str
    merchant: str
    category: str
    source: str  # "rule" or "llm"
    confidence: float
    needs_review: bool
    failed: bool  # the provider batch got no usable answer


def predict(descriptions: list[str], provider: LLMProvider) -> dict[str, Prediction]:
    """Categorize descriptions exactly as the upload pipeline would, minus the cache."""
    merchants = {d: normalize_merchant(d) for d in descriptions}
    decided = decide_categories({m for m in merchants.values() if m}, provider)
    predictions = {}
    for description, merchant in merchants.items():
        # Same as the pipeline: a description that normalizes to nothing is Other.
        source, result = decided.get(merchant, ("rule", Result(OTHER, 0.0)))
        predictions[description] = Prediction(
            description=description,
            merchant=merchant,
            category=result.category,
            source=source,
            confidence=result.confidence,
            needs_review=result.confidence < REVIEW_THRESHOLD,
            failed=result.failed,
        )
    return predictions


def evaluate(
    labeled: list[LabeledRow],
    should_flag: list[str],
    provider: LLMProvider,
    sources: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Run every row and compute the report as plain JSON-ready data. `sources` names
    the input files, whose hashes go into the metadata."""
    predictions = predict([r.description for r in labeled] + should_flag, provider)

    rows = []
    for row in labeled:
        p = predictions[row.description]
        rows.append({**asdict(p), "expected": row.category,
                     "correct": None if p.failed else p.category == row.category})

    scored = [r for r in rows if not r["failed"]]
    wrong = [r for r in scored if not r["correct"]]
    flag_rows = [asdict(predictions[d]) for d in should_flag]

    return {
        "metadata": _metadata(provider, len(labeled), len(should_flag), sources or {}),
        # "rows" is always the scored rows, the denominator of "accuracy"; failed rows
        # are counted separately and never scored.
        "overall": _accuracy(scored) | {"total_rows": len(rows), "failed": len(rows) - len(scored)},
        "by_source": {
            "rule": _accuracy([r for r in scored if r["source"] == "rule"]),
            "provider": _accuracy([r for r in scored if r["source"] == "llm"])
            | {"failed": sum(r["failed"] for r in rows)},
        },
        "by_confidence": {
            "confident": _accuracy([r for r in scored if not r["needs_review"]]),
            "needs_review": _accuracy([r for r in scored if r["needs_review"]]),
        },
        "review_flag": {
            "wrong": len(wrong),
            "wrong_flagged": sum(r["needs_review"] for r in wrong),
            "recall": _ratio(sum(r["needs_review"] for r in wrong), len(wrong)),
        },
        "wrong_answers": [
            {key: r[key] for key in
             ("description", "merchant", "expected", "category", "source", "confidence")}
            for r in sorted(wrong, key=lambda r: (r["expected"], r["description"]))
        ],
        "confusions": [
            {"expected": expected, "got": got, "count": count}
            for (expected, got), count in sorted(
                Counter((r["expected"], r["category"]) for r in wrong).items(),
                key=lambda item: (-item[1], item[0]),
            )[:TOP_CONFUSIONS]
        ],
        "failed_rows": [r["description"] for r in rows if r["failed"]],
        "should_flag": {
            "total": len(flag_rows),
            "flagged": sum(r["needs_review"] for r in flag_rows),
            "failed": sum(r["failed"] for r in flag_rows),
            "not_flagged": [
                {key: r[key] for key in
                 ("description", "merchant", "category", "source", "confidence")}
                for r in flag_rows if not r["needs_review"]
            ],
        },
    }


def _accuracy(rows: list[dict]) -> dict[str, Any]:
    correct = sum(bool(r["correct"]) for r in rows)
    return {"rows": len(rows), "correct": correct, "accuracy": _ratio(correct, len(rows))}


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metadata(
    provider: LLMProvider, rows: int, should_flag_rows: int, sources: dict[str, Path]
) -> dict[str, Any]:
    return {
        "provider": provider.name,
        "model": getattr(provider, "model", None),
        "temperature": 0 if provider.name == "gemini" else None,
        "date": date.today().isoformat(),
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": rows,
        "should_flag_rows": should_flag_rows,
        "review_threshold": REVIEW_THRESHOLD,
        "batch_size": BATCH_SIZE,
        "files": {
            name: {"path": _display(path), "sha256": _sha256(path)}
            for name, path in sources.items()
        },
        "git_commit": _git_commit(),
    }


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_DIR))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else None


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_DIR,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_DIR,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return f"{out}{' (uncommitted changes)' if dirty else ''}"
    except (OSError, subprocess.SubprocessError):
        return None


# --- output -----------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _line(label: str, stats: dict, failed: int | None = None) -> tuple[str, str, str, str]:
    # Correct is out of the scored rows, the same denominator as Accuracy.
    return (label, f"{stats['correct']}/{stats['rows']}",
            "-" if failed is None else str(failed), _pct(stats["accuracy"]))


def _summary_lines(report: dict) -> list[tuple[str, str, str, str]]:
    by_source, by_conf, flag = report["by_source"], report["by_confidence"], report["review_flag"]
    return [
        _line("Overall", report["overall"], report["overall"]["failed"]),
        _line("Rules", by_source["rule"], 0),
        _line("Provider", by_source["provider"], by_source["provider"]["failed"]),
        _line(f"Confident (>= {report['metadata']['review_threshold']})", by_conf["confident"]),
        _line("Flagged needs_review", by_conf["needs_review"]),
        ("Wrong answers flagged (recall)", f"{flag['wrong_flagged']}/{flag['wrong']}", "-",
         _pct(flag["recall"])),
    ]


def _metadata_lines(report: dict) -> list[tuple[str, str]]:
    meta = report["metadata"]
    lines = [
        ("Provider", meta["provider"]),
        ("Model", meta["model"] or "n/a (offline fake)"),
        ("Temperature", "n/a" if meta["temperature"] is None else str(meta["temperature"])),
        ("Date", f"{meta['date']} (run at {meta['run_at']})"),
        ("Rows", f"{meta['rows']} labeled, {meta['should_flag_rows']} should-flag"),
        ("Review threshold", f"confidence < {meta['review_threshold']}"),
        ("Batch size", str(meta["batch_size"])),
        ("Git commit", meta["git_commit"] or "unknown"),
    ]
    for name, info in meta["files"].items():
        lines.append((f"{name} file", f"{info['path']} (sha256 {info['sha256']})"))
    return lines


def _table(headers: list[str], rows: list[list[Any]], markdown: bool) -> list[str]:
    cells = [[str(c) for c in row] for row in rows]
    if markdown:
        escape = lambda c: c.replace("|", "\\|")  # noqa: E731
        out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
        return out + ["| " + " | ".join(escape(c) for c in row) + " |" for row in cells]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h)
              for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return [fmt.format(*headers), fmt.format(*("-" * w for w in widths))] + [
        fmt.format(*row) for row in cells
    ]


def render(report: dict, markdown: bool = False) -> str:
    """The report as a terminal table, or as Markdown with the same content."""
    h = (lambda text: f"\n## {text}\n") if markdown else (lambda text: f"\n{text}\n{'=' * len(text)}")
    out = ["# Categorizer evaluation" if markdown else "Categorizer evaluation"]

    out += [h("Run"), *_table(["Setting", "Value"], _metadata_lines(report), markdown)]

    out += [h("Accuracy"), *_table(["Slice", "Correct", "Failed", "Accuracy"],
                                     _summary_lines(report), markdown)]
    failed = report["overall"]["failed"]
    if failed:
        out += ["", f"{failed} of {report['overall']['total_rows']} row(s) got no answer "
                    "because a provider batch failed. They are left out of every Correct and "
                    "Accuracy figure above and listed under Failed rows."]

    out += [h("Most common mistakes")]
    out += _table(["Expected", "Got", "Count"],
                  [[c["expected"], c["got"], c["count"]] for c in report["confusions"]],
                  markdown) if report["confusions"] else ["None."]

    wrong = report["wrong_answers"]
    out += [h(f"Wrong answers ({len(wrong)})")]
    out += _table(
        ["Description", "Merchant", "Expected", "Got", "Source", "Confidence"],
        [[w["description"], w["merchant"], w["expected"], w["category"], w["source"],
          f"{w['confidence']:.2f}"] for w in wrong],
        markdown,
    ) if wrong else ["None."]

    if report["failed_rows"]:
        out += [h(f"Failed rows ({len(report['failed_rows'])})")]
        out += [f"- {d}" for d in report["failed_rows"]]

    flag = report["should_flag"]
    out += [h("Should-flag check"), f"flagged {flag['flagged']} of {flag['total']}"]
    if flag["failed"]:
        out += [f"({flag['failed']} of those flagged only because their provider batch failed)"]
    if flag["not_flagged"]:
        out += ["", "Not flagged:"]
        out += _table(
            ["Description", "Merchant", "Got", "Source", "Confidence"],
            [[r["description"], r["merchant"], r["category"], r["source"],
              f"{r['confidence']:.2f}"] for r in flag["not_flagged"]],
            markdown,
        )
    return "\n".join(out).strip() + "\n"


def results_path(report: dict, results_dir: Path) -> Path:
    meta = report["metadata"]
    return results_dir / f"{meta['provider']}-{meta['date']}.md"


# --- command line -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the merchant categorizer.")
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    parser.add_argument("--labeled", type=Path, default=LABELED_FILE)
    parser.add_argument("--should-flag", type=Path, default=SHOULD_FLAG_FILE)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        labeled = load_labeled(args.labeled)
        should_flag = load_should_flag(args.should_flag) if args.should_flag.exists() else []
        provider = get_provider()
    except (EvalDataError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sources = {"labeled": args.labeled}
    if args.should_flag.exists():
        sources["should_flag"] = args.should_flag
    report = evaluate(labeled, should_flag, provider, sources)

    path = results_path(report, args.results_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(report, markdown=True), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))
        print(f"Wrote {_display(path)}")
    if report["overall"]["failed"]:
        print(f"warning: {report['overall']['failed']} row(s) failed; see the report",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
