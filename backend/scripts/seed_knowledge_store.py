"""
Seed the RAG knowledge store from data the system already owns.

Why a seeder rather than hand-authored notes: everything ingested here is
derived from existing, factual sources in this codebase, so nothing is
invented. Sources:

  1. Skill taxonomy (app.ml.parsing.skill_normalizer) — the 65 canonical
     skills and their alias mappings. Real, authoritative, and exactly what
     the retrieval `tags` field is matched against, so these chunks double as
     documentation of the tagging vocabulary itself.

  2. The question bank (questions collection) — each question becomes a
     `question_explanation` chunk carrying its stem, the correct answer, and
     the distractor options. This is the highest-value content for gap
     analysis: when a student is weak on a skill, retrieval surfaces the
     actual questions they got wrong, so the narrative is grounded in the
     same items rather than generic advice.

Nothing here calls an LLM. Content generation would risk factual drift and
cost money per run; the seeder only embeds text that already exists.

Idempotent: re-running replaces each source's chunks rather than duplicating
them.

Usage (from backend/, backend running not required — it talks to Mongo
directly, but DOES need the embedding provider reachable):

    .venv\\Scripts\\python.exe -m scripts.seed_knowledge_store

Flags:
    --dry-run     report what would be ingested, write nothing
    --no-embed    skip embedding entirely (prints counts only)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.ml.parsing.skill_normalizer import ALIASES, CANONICAL_SKILLS  # noqa: E402
from app.ml.rag.knowledge_store import KnowledgeStore  # noqa: E402

TAXONOMY_SOURCE = "seed:skill_taxonomy"
QUESTION_SOURCE_PREFIX = "seed:question"


def build_taxonomy_chunks() -> list[dict]:
    """One chunk per canonical skill, describing what it is in this system
    and which aliases resolve to it."""
    # Group aliases by their canonical target.
    aliases_by_target: dict[str, list[str]] = {}
    for alias, target in ALIASES.items():
        aliases_by_target.setdefault(target, []).append(alias)

    chunks = []
    for skill in CANONICAL_SKILLS:
        aliases = sorted(aliases_by_target.get(skill, []), key=str.lower)
        lines = [
            f"{skill} is one of the canonical skill tags recognised by this system's "
            f"resume parser, semantic matcher, knowledge tracer and RAG knowledge store. "
            f"Student performance on {skill} is tracked per skill, so mastery of it is "
            f"estimated independently from every other tag."
        ]
        if aliases:
            lines.append(
                f"Common resume spellings that normalise to {skill}: "
                + ", ".join(aliases)
                + "."
            )
        chunks.append(
            {
                "text": " ".join(lines),
                "chunk_type": "skill_taxonomy",
                "tags": [skill],
                "source_id": f"{TAXONOMY_SOURCE}:{skill}",
                "chunk": False,  # short by construction
            }
        )

    # One consolidated alias reference, useful when retrieval is asked
    # "what does ML mean" rather than about a specific skill.
    alias_lines = "; ".join(f"{a} -> {t}" for a, t in sorted(ALIASES.items(), key=lambda kv: kv[0].lower()))
    if alias_lines:
        chunks.append(
            {
                "text": (
                    "Skill alias resolution table used when parsing resumes and job "
                    f"descriptions: {alias_lines}."
                ),
                "chunk_type": "skill_taxonomy",
                "tags": sorted(set(ALIASES.values())),
                "source_id": f"{TAXONOMY_SOURCE}:__all_aliases",
                "chunk": True,
            }
        )
    return chunks


async def load_question_chunks(db) -> list[dict]:
    """Turn every question in the bank into a retrievable explanation chunk."""
    cursor = db.questions.find({})
    chunks: list[dict] = []
    async for q in cursor:
        text = str(q.get("text", "")).strip()
        if not text:
            continue
        tags = [t for t in (q.get("skill_tags") or []) if t]
        difficulty = q.get("difficulty")
        qtype = q.get("type")
        correct = q.get("correct_answer")
        options = q.get("options") or []

        parts = [text]
        if qtype == "mcq" and options:
            opts = "; ".join(str(o) for o in options)
            parts.append(f"Options: {opts}.")
        if correct:
            parts.append(f"Correct answer: {correct}.")
        if difficulty:
            parts.append(f"Difficulty: {difficulty}.")
        parts.append(
            "A student who misses this question has a specific, identifiable gap in "
            f"{tags[0] if tags else 'this topic'} — revisit the underlying concept rather "
            "than guessing."
        )

        chunks.append(
            {
                "text": " ".join(parts),
                "chunk_type": "question_explanation",
                "tags": tags or ["Untagged"],
                "source_id": f"{QUESTION_SOURCE_PREFIX}:{q.get('_id')}",
                "chunk": False,
            }
        )
    return chunks


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the RAG knowledge store.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing.")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding entirely.")
    args = parser.parse_args()

    s = get_settings()
    print(f"MongoDB   : {s.MONGODB_URI}/{s.MONGODB_DB_NAME}")
    print(f"Embeddings: provider={s.EMBEDDING_PROVIDER} model={s.EMBEDDING_MODEL}")
    print()

    client = AsyncIOMotorClient(s.MONGODB_URI)
    db = client[s.MONGODB_DB_NAME]
    store = KnowledgeStore(db)

    taxonomy = build_taxonomy_chunks()
    questions = await load_question_chunks(db)

    print(f"skill taxonomy chunks : {len(taxonomy)}")
    print(f"question chunks       : {len(questions)}")
    print(f"total to ingest       : {len(taxonomy) + len(questions)}")

    if args.dry_run or args.no_embed:
        if args.dry_run:
            print("\n--dry-run: nothing written.")
        return 0

    # Idempotency: clear prior seeds before rewriting.
    removed_tax = await store.delete_by_source_prefix(TAXONOMY_SOURCE)
    print(f"\ncleared {removed_tax} previously-seeded chunks")

    ingested = 0
    batch_size = 25
    for start in range(0, len(taxonomy), batch_size):
        for item in taxonomy[start : start + batch_size]:
            n = await store.ingest_long(**{k: v for k, v in item.items() if k != "chunk"})
            ingested += n
        print(f"  taxonomy {min(start + batch_size, len(taxonomy))}/{len(taxonomy)}")

    print(f"taxonomy chunks written: {ingested}")

    q_ingested = 0
    for item in questions:
        ok = await store.ingest(**{k: v for k, v in item.items() if k != "chunk"})
        if ok:
            q_ingested += 1
    print(f"question chunks written: {q_ingested}")

    stats = await store.stats()
    print(f"\nstore now holds {stats['total']} chunks:")
    for chunk_type, n in sorted(stats["by_type"].items()):
        print(f"  {chunk_type:24} {n}")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))