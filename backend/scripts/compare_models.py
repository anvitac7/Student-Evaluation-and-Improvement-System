"""
PHASE A-1 — scripts/compare_models.py

Run-once evaluation harness: Nemotron vs Qwen3.8-27B on the project's
actual task types. Not part of the running app — a CLI script an
engineer runs manually, whose OUTPUT (a decision) gets hand-copied into
config_additions.py's LLM_PRIMARY_* / LLM_FALLBACK_* values.

Usage:
    export NVIDIA_API_KEY=...
    export OPENROUTER_API_KEY=...
    python scripts/compare_models.py --eval-set scripts/eval_dataset.json

Requires: pip install openai httpx tabulate
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field

from openai import OpenAI


@dataclass
class Candidate:
    label: str
    model: str
    base_url: str
    api_key_env: str
    extra_body: dict = field(default_factory=dict)


CANDIDATES = [
    Candidate(
        label="NVIDIA Nemotron",
        model="nvidia/nemotron-4-340b-instruct",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
    ),
    Candidate(
        label="Qwen3.8-27B (OpenRouter)",
        model="qwen/qwen3-8b",  # swap to the 3.8-27B route id once confirmed live on OpenRouter
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        extra_body={"enable_thinking": True},
    ),
]

SKILL_SCHEMA_HINT = """{
  "matched_skills": ["<canonical skill name from the provided vocabulary>", ...],
  "unmapped_candidates": ["<phrase found in text that is NOT in the vocabulary>", ...]
}"""


def run_one(candidate: Candidate, system_prompt: str, user_prompt: str, json_mode: bool) -> dict:
    api_key = os.environ.get(candidate.api_key_env, "")
    client = OpenAI(base_url=candidate.base_url, api_key=api_key or "not-needed", timeout=30)

    start = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=candidate.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2 if json_mode else 0.6,
            extra_body=candidate.extra_body or None,
        )
        latency = time.monotonic() - start
        text = resp.choices[0].message.content or ""
        return {"ok": True, "latency_s": round(latency, 2), "output": text}
    except Exception as e:  # noqa: BLE001 — eval script, want to see any failure
        latency = time.monotonic() - start
        return {"ok": False, "latency_s": round(latency, 2), "error": str(e)}


def eval_skill_extraction(eval_set: dict, vocabulary: dict) -> list[dict]:
    system = (
        "You extract technical skills from resume/JD text. Only match against "
        f"this vocabulary (canonical terms + aliases): {json.dumps(vocabulary)}. "
        "Do not invent skills outside this vocabulary — if you see a real skill "
        "that genuinely isn't in the list, put it under unmapped_candidates instead."
    )
    results = []
    for item in eval_set.get("skill_extraction", []):
        row = {"input_id": item["id"], "input_text": item["text"][:80] + "...", "candidates": {}}
        for c in CANDIDATES:
            row["candidates"][c.label] = run_one(
                c, system + f"\n\nRespond ONLY with JSON: {SKILL_SCHEMA_HINT}", item["text"], json_mode=True
            )
        results.append(row)
    return results


def eval_gap_analysis(eval_set: dict) -> list[dict]:
    system = (
        "You are an academic coach. You are given a student's ALREADY-COMPUTED "
        "wrong-answer skills, mastery percentages, and retrieved reference "
        "material. Write a short, specific, encouraging explanation of why "
        "they scored what they scored and what to study next. Do NOT invent "
        "facts not present in the input — every claim must trace back to the "
        "given data or retrieved chunks."
    )
    results = []
    for item in eval_set.get("gap_analysis", []):
        row = {"input_id": item["id"], "candidates": {}}
        for c in CANDIDATES:
            row["candidates"][c.label] = run_one(c, system, json.dumps(item["facts"]), json_mode=False)
        results.append(row)
    return results


def eval_jd_explanation(eval_set: dict) -> list[dict]:
    system = (
        "You are a career coach. You are given an ALREADY-COMPUTED match-score "
        "breakdown (semantic similarity, skills overlap, experience fit), a "
        "missing-skills list, and retrieved JD/skill-taxonomy chunks. Explain "
        "in the student's terms what held the score back and give 2-3 concrete "
        "next steps, grounded only in the retrieved material."
    )
    results = []
    for item in eval_set.get("jd_explanation", []):
        row = {"input_id": item["id"], "candidates": {}}
        for c in CANDIDATES:
            row["candidates"][c.label] = run_one(c, system, json.dumps(item["facts"]), json_mode=False)
        results.append(row)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", default="scripts/eval_dataset.json")
    parser.add_argument("--vocabulary", default="scripts/vocabulary_snapshot.json")
    parser.add_argument("--out", default="scripts/comparison_log.json")
    args = parser.parse_args()

    with open(args.eval_set) as f:
        eval_set = json.load(f)
    with open(args.vocabulary) as f:
        vocabulary = json.load(f)

    log = {
        "skill_extraction": eval_skill_extraction(eval_set, vocabulary),
        "gap_analysis": eval_gap_analysis(eval_set),
        "jd_explanation": eval_jd_explanation(eval_set),
    }

    with open(args.out, "w") as f:
        json.dump(log, f, indent=2)

    print(f"Comparison log written to {args.out}")
    print("Review side-by-side, score against the checklist in the Phase A-1 doc,")
    print("then hand-set LLM_PRIMARY_* / LLM_FALLBACK_* in config_additions.py.")


if __name__ == "__main__":
    main()