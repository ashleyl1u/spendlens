"""Tests for the categorizer evaluation harness (eval/run_eval.py). No network, no key."""

import csv
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.categorization.normalize import normalize_merchant
from app.categorization.providers import FakeProvider, GeminiProvider
from app.categorization.rules import match_rule

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_eval", REPO / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
sys.modules["run_eval"] = run_eval  # dataclasses look their module up here
_spec.loader.exec_module(run_eval)

# A tiny built-in sample, with what the rules and FakeProvider do to each row.
SAMPLE = [
    ("TIM HORTONS #4521 TORONTO ON", "Dining"),         # rule, right
    ("UBER *TRIP HELP.UBER.COM", "Transport"),          # rule, right
    ("METRO #142 MISSISSAUGA ON", "Shopping"),          # rule says Groceries: wrong, confident
    ("MAPLE STREET BOOKS CO., VANCOUVER", "Shopping"),  # fake: Shopping 0.8, right
    ("SQ *GARDEN DUMPLING HOUSE", "Dining"),            # fake: Dining 0.85, right
    ("*RFBT-TORONTO YONGE ST TORONTO", "Dining"),       # fake: Dining 0.6, right but flagged
    ("ZZZ UNKNOWN PLACE", "Entertainment"),             # fake: Other 0.4, wrong and flagged
]
SHOULD_FLAG = [
    "QQQ MYSTERY SHOP",  # fake: Shopping 0.75, so NOT flagged
    "XYZ NOWHERE",       # fake: Other 0.4, flagged
]


def write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path


@pytest.fixture()
def sample_files(tmp_path):
    labeled = write_csv(tmp_path / "labeled.csv", ["description", "category"], SAMPLE)
    flag = write_csv(tmp_path / "flag.csv", ["description"], [[d] for d in SHOULD_FLAG])
    return labeled, flag


def run(capsys, monkeypatch, labeled, flag, results_dir, *extra):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    code = run_eval.main(["--labeled", str(labeled), "--should-flag", str(flag),
                          "--results-dir", str(results_dir), *extra])
    return code, capsys.readouterr()


# --- the harness on the fake provider ---------------------------------------------


def test_report_on_the_built_in_sample(capsys, monkeypatch, tmp_path, sample_files):
    code, out = run(capsys, monkeypatch, *sample_files, tmp_path / "results", "--json")
    assert code == 0
    report = json.loads(out.out)

    assert report["overall"] == {
        "rows": 7, "correct": 5, "accuracy": 5 / 7, "total_rows": 7, "failed": 0
    }
    assert report["by_source"]["rule"] == {"rows": 3, "correct": 2, "accuracy": 2 / 3}
    assert report["by_source"]["provider"] == {
        "rows": 4, "correct": 3, "accuracy": 3 / 4, "failed": 0
    }
    # Confident: Tim Hortons, Uber, Metro, Maple, Garden. Flagged: RFBT, ZZZ.
    assert report["by_confidence"]["confident"] == {"rows": 5, "correct": 4, "accuracy": 4 / 5}
    assert report["by_confidence"]["needs_review"] == {"rows": 2, "correct": 1, "accuracy": 1 / 2}
    # Two wrong answers (Metro, ZZZ); only ZZZ was flagged.
    assert report["review_flag"] == {"wrong": 2, "wrong_flagged": 1, "recall": 0.5}

    assert report["wrong_answers"] == [
        {"description": "ZZZ UNKNOWN PLACE", "merchant": "ZZZ UNKNOWN PLACE",
         "expected": "Entertainment", "category": "Other", "source": "llm", "confidence": 0.4},
        {"description": "METRO #142 MISSISSAUGA ON", "merchant": "METRO",
         "expected": "Shopping", "category": "Groceries", "source": "rule", "confidence": 0.95},
    ]
    assert report["confusions"] == [
        {"expected": "Entertainment", "got": "Other", "count": 1},
        {"expected": "Shopping", "got": "Groceries", "count": 1},
    ]

    assert report["should_flag"]["total"] == 2
    assert report["should_flag"]["flagged"] == 1
    assert [r["description"] for r in report["should_flag"]["not_flagged"]] == ["QQQ MYSTERY SHOP"]

    meta = report["metadata"]
    assert (meta["provider"], meta["model"], meta["rows"], meta["should_flag_rows"]) == (
        "fake", None, 7, 2
    )
    assert meta["date"] == date.today().isoformat()
    assert set(meta["files"]) == {"labeled", "should_flag"}
    assert all(len(info["sha256"]) == 12 for info in meta["files"].values())


def test_terminal_and_markdown_reports(capsys, monkeypatch, tmp_path, sample_files):
    results = tmp_path / "results"
    code, out = run(capsys, monkeypatch, *sample_files, results)
    assert code == 0

    for text in (out.out, (results / f"fake-{date.today().isoformat()}.md").read_text()):
        assert "flagged 1 of 2" in text
        assert "QQQ MYSTERY SHOP" in text  # listed as not flagged
        assert "ZZZ UNKNOWN PLACE" in text  # listed as a wrong answer
        assert "71.4%" in text  # overall 5/7
        assert "n/a (offline fake)" in text
    assert "| Overall | 5/7 | 0 | 71.4% |" in (results / f"fake-{date.today().isoformat()}.md").read_text()


def test_labels_are_never_modified(capsys, monkeypatch, tmp_path, sample_files):
    labeled, _ = sample_files
    before = labeled.read_bytes()
    run(capsys, monkeypatch, *sample_files, tmp_path / "results")
    assert labeled.read_bytes() == before


def test_provider_calls_use_the_pipeline_batching(monkeypatch, tmp_path, sample_files):
    monkeypatch.setattr("app.categorization.pipeline.BATCH_SIZE", 2)
    provider = FakeProvider()
    labeled, flag = sample_files
    run_eval.evaluate(run_eval.load_labeled(labeled), run_eval.load_should_flag(flag), provider)

    # 4 provider merchants from the sample + 2 should-flag rows, each sent once.
    assert [len(call) for call in provider.calls] == [2, 2, 2]
    sent = [m for call in provider.calls for m in call]
    assert len(sent) == len(set(sent)) == 6


# --- gemini: failed batches and reproducibility -------------------------------------


def gemini_with(handler):
    return GeminiProvider(api_key="test-key", model="test-model",
                          transport=httpx.MockTransport(handler), sleep=lambda _: None)


def test_failed_batch_is_reported_as_failed_not_wrong(tmp_path, sample_files):
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    labeled, flag = sample_files
    report = run_eval.evaluate(
        run_eval.load_labeled(labeled), run_eval.load_should_flag(flag), gemini_with(timeout)
    )

    # The 3 rule rows are still scored; the 4 provider rows are failed, not wrong.
    assert report["overall"] == {
        "rows": 3, "correct": 2, "accuracy": 2 / 3, "total_rows": 7, "failed": 4
    }
    assert report["by_source"]["provider"] == {
        "rows": 0, "correct": 0, "accuracy": None, "failed": 4
    }
    assert [w["description"] for w in report["wrong_answers"]] == ["METRO #142 MISSISSAUGA ON"]
    assert sorted(report["failed_rows"]) == sorted(d for d, _ in SAMPLE[3:])
    assert report["should_flag"]["failed"] == 2

    text = run_eval.render(report, markdown=True)
    assert "Failed rows (4)" in text
    assert "4 of 7 row(s) got no answer" in text
    # Correct uses the scored denominator, with the failed count beside it, so the
    # fraction and the percentage always agree.
    assert "| Overall | 2/3 | 4 | 66.7% |" in text
    assert "| Rules | 2/3 | 0 | 66.7% |" in text
    assert "| Provider | 0/0 | 4 | n/a |" in text


def test_gemini_run_records_model_and_temperature(tmp_path, sample_files):
    def answer(request):
        merchants = json.loads(json.loads(request.content)["contents"][0]["parts"][0]["text"])[
            "merchants"
        ]
        results = [{"category": "Dining", "confidence": 0.9} for _ in merchants]
        return httpx.Response(200, json={"candidates": [{
            "content": {"parts": [{"text": json.dumps({"results": results})}]},
            "finishReason": "STOP",
        }]})

    labeled, flag = sample_files
    report = run_eval.evaluate(
        run_eval.load_labeled(labeled), run_eval.load_should_flag(flag), gemini_with(answer),
        sources={"labeled": labeled},
    )
    meta = report["metadata"]
    assert (meta["provider"], meta["model"], meta["temperature"]) == ("gemini", "test-model", 0)
    assert report["overall"]["failed"] == 0
    assert report["by_source"]["provider"]["rows"] == 4


# --- validation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows, message",
    [
        ([["LOBLAWS", "Groceries"], ["NETFLIX", "Streaming"]], "line 3: category 'Streaming'"),
        ([["LOBLAWS", "Groceries"], ["", "Dining"]], "line 3: blank description"),
        ([["LOBLAWS", "Groceries"], ["  ", "Dining"]], "line 3: blank description"),
        ([["LOBLAWS", "Groceries"], ["LOBLAWS", "Dining"]], "line 3: duplicate description"),
        ([["LOBLAWS", "groceries"]], "category 'groceries'"),
        ([["LOBLAWS", ""]], "category ''"),
    ],
)
def test_invalid_labels_are_rejected(tmp_path, rows, message):
    path = write_csv(tmp_path / "labeled.csv", ["description", "category"], rows)
    with pytest.raises(run_eval.EvalDataError, match=message):
        run_eval.load_labeled(path)


def test_every_problem_is_reported_at_once(tmp_path):
    path = write_csv(tmp_path / "labeled.csv", ["description", "category"],
                     [["A", "Nope"], ["", "Dining"], ["B", "Dining"], ["B", "Dining"]])
    with pytest.raises(run_eval.EvalDataError) as error:
        run_eval.load_labeled(path)
    assert "3 problem(s)" in str(error.value)
    for line in ("line 2", "line 3", "line 5"):
        assert line in str(error.value)


def test_wrong_header_and_extra_fields_are_rejected(tmp_path):
    bad_header = write_csv(tmp_path / "a.csv", ["merchant", "label"], [["X", "Dining"]])
    with pytest.raises(run_eval.EvalDataError, match="expected columns"):
        run_eval.load_labeled(bad_header)

    extra = tmp_path / "b.csv"
    extra.write_text("description,category\nFOO, INC,Dining\n")
    with pytest.raises(run_eval.EvalDataError, match="too many fields"):
        run_eval.load_labeled(extra)


def test_should_flag_file_is_validated(tmp_path):
    path = write_csv(tmp_path / "flag.csv", ["description"], [["A"], ["A"]])
    with pytest.raises(run_eval.EvalDataError, match="duplicate"):
        run_eval.load_should_flag(path)


def test_invalid_file_exits_with_an_error(capsys, monkeypatch, tmp_path):
    labeled = write_csv(tmp_path / "labeled.csv", ["description", "category"], [["A", "Nope"]])
    code, out = run(capsys, monkeypatch, labeled, tmp_path / "missing.csv", tmp_path / "results")
    assert code == 2
    assert "category 'Nope'" in out.err
    assert not (tmp_path / "results").exists()


def test_missing_gemini_key_exits_with_an_error(capsys, monkeypatch, tmp_path, sample_files):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    labeled, flag = sample_files
    code = run_eval.main(["--labeled", str(labeled), "--should-flag", str(flag),
                          "--results-dir", str(tmp_path)])
    assert code == 2
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().err


# --- regression guard on the real labeled file ---------------------------------------

# Measured on 2026-11-08 with the 166-row file, after fixing the Uber Eats, DoorDash,
# gas bar, Amazon Prime and YouTube cases: rules matched 86 rows and got all 86 right.
# The guard allows a little slack, so adding hard rows does not fail it, but a
# normalization or rule change that breaks several merchants will.
MIN_RULE_ACCURACY = 0.95
MIN_RULE_CORRECT = 82


@pytest.mark.skipif(
    not run_eval.LABELED_FILE.exists(),
    reason="eval/labeled_merchants.csv is not in this checkout (it is git-ignored)",
)
def test_rules_accuracy_on_the_labeled_file():
    rows = run_eval.load_labeled(run_eval.LABELED_FILE)
    covered = [(row, match_rule(normalize_merchant(row.description))) for row in rows]
    covered = [(row, got) for row, got in covered if got is not None]
    correct = sum(got == row.category for row, got in covered)

    wrong = [f"{row.description} -> {got} (expected {row.category})"
             for row, got in covered if got != row.category]
    assert correct >= MIN_RULE_CORRECT, wrong
    assert correct / len(covered) >= MIN_RULE_ACCURACY, wrong
