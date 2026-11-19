"""Accuracy benchmark for the extraction pipeline (live OpenAI calls).

Layout:
    backend/eval/cases/<case-name>/
        input.<pdf|xlsx|xls|docx|png|...>   the supplier contract
        expected.json                        HUMAN-VERIFIED ContractExtraction

Usage (from backend/, with backend/.env holding OPENAI_API_KEY):

    # 1. Draft an expected result for a new case, then check and correct
    #    it by hand against the contract and save it as expected.json:
    python -m eval.run_eval --draft my-case

    # 2. Score every case with the new reader and the old raw-file path:
    python -m eval.run_eval --modes parsed raw

A report is written to backend/eval/reports/<timestamp>.json. Never
copy draft.json to expected.json without checking it: the benchmark is
only as good as the answers it is checked against.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.config import get_settings  # noqa: E402
from app.extraction.canonical import ContractExtraction  # noqa: E402
from app.extraction.orchestrator import orchestrate_extraction  # noqa: E402
from eval.scoring import score  # noqa: E402

CASES = HERE / "cases"
REPORTS = HERE / "reports"


def _input_of(case: Path) -> Path:
    files = [p for p in case.iterdir() if p.stem == "input"]
    if not files:
        raise SystemExit(f"{case.name}: no input.* file")
    return files[0]


def _run(case: Path, mode: str) -> tuple[ContractExtraction, float]:
    os.environ["READER_MODE"] = mode
    get_settings.cache_clear()
    t = time.time()
    result = orchestrate_extraction(_input_of(case), options={})
    return result, time.time() - t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", metavar="CASE", help="write cases/CASE/draft.json")
    ap.add_argument("--modes", nargs="+", default=["parsed"], choices=["parsed", "raw"])
    ap.add_argument("--cases", nargs="*", help="limit to these case names")
    args = ap.parse_args()

    if args.draft:
        case = CASES / args.draft
        result, secs = _run(case, "parsed")
        (case / "draft.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"wrote {case / 'draft.json'} in {secs:.0f}s - verify it, then save as expected.json")
        return

    cases = sorted(
        c for c in CASES.iterdir()
        if c.is_dir() and (c / "expected.json").exists()
        and (not args.cases or c.name in args.cases)
    ) if CASES.exists() else []
    if not cases:
        raise SystemExit("no cases with expected.json under eval/cases/")

    report = {"modes": args.modes, "cases": {}}
    for case in cases:
        expected = ContractExtraction.model_validate_json(
            (case / "expected.json").read_text(encoding="utf-8")
        )
        report["cases"][case.name] = {}
        for mode in args.modes:
            try:
                got, secs = _run(case, mode)
                s = score(got, expected)
                s["seconds"] = round(secs, 1)
            except Exception as e:  # noqa: BLE001
                s = {"error": f"{type(e).__name__}: {e}"}
            report["cases"][case.name][mode] = s
            print(
                f"{case.name:30} {mode:6} "
                + (
                    s.get("error")
                    or "rates {rate_cells:.0%}  rooms {rooms:.0%}  seasons {seasons:.0%}  "
                       "supps {supplements:.0%}  child {child_bands:.0%}  extra {extra_cells}  "
                       "{seconds}s".format(**s)
                )
            )

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
