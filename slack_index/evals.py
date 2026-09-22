"""Score the index against a hand-labelled question set.

    python -m slack_index.evals
    python -m slack_index.evals --questions evals/questions.yaml --top-k 10

Every retrieval change — a different embedding model, grouping, a reranker — is
judged by re-running this against the same questions.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
from collections import defaultdict
from dataclasses import dataclass, field

import yaml

from slack_index.search import Searcher

DEFAULT_QUESTIONS = pathlib.Path("evals/questions.yaml")
DEFAULT_KS = (1, 3, 10)


@dataclass(frozen=True, slots=True)
class Question:
    question: str
    expected: frozenset[str]
    tags: tuple[str, ...]


@dataclass
class Report:
    total: int = 0
    hits: dict[int, int] = field(default_factory=dict)
    reciprocal_rank_sum: float = 0.0
    misses: list[str] = field(default_factory=list)

    def recall(self, k: int) -> float:
        return self.hits.get(k, 0) / self.total if self.total else 0.0

    @property
    def mrr(self) -> float:
        return self.reciprocal_rank_sum / self.total if self.total else 0.0


def load_questions(path: pathlib.Path) -> list[Question]:
    raw = yaml.safe_load(path.read_text()) or []
    return [
        Question(
            question=item["question"],
            expected=frozenset(item["expected"]),
            tags=tuple(item.get("tags", ())),
        )
        for item in raw
    ]


def _record(
    report: Report, ks: tuple[int, ...], rank: int | None, question: str
) -> None:
    report.total += 1
    if rank is None:
        report.misses.append(question)
        return
    report.reciprocal_rank_sum += 1.0 / rank
    for k in ks:
        if rank <= k:
            report.hits[k] = report.hits.get(k, 0) + 1


async def evaluate(
    searcher: Searcher,
    questions: list[Question],
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
    top_k: int | None = None,
) -> tuple[Report, dict[str, Report]]:
    limit = top_k or max(ks)
    overall = Report()
    per_tag: dict[str, Report] = defaultdict(Report)

    for question in questions:
        hits = await searcher.search(question.question, limit)
        rank = next(
            (
                i
                for i, hit in enumerate(hits, start=1)
                if hit.source_id in question.expected
            ),
            None,
        )
        _record(overall, ks, rank, question.question)
        for tag in question.tags:
            _record(per_tag[tag], ks, rank, question.question)
    return overall, dict(per_tag)


def _format(name: str, report: Report, ks: tuple[int, ...]) -> str:
    cells = " ".join(
        f"recall@{k}: {report.recall(k):.2f} ({report.hits.get(k, 0)}/{report.total})"
        for k in ks
    )
    return f"{name:<10} {cells}  MRR: {report.mrr:.2f}"


async def run(questions_path: pathlib.Path, top_k: int) -> None:
    questions = load_questions(questions_path)
    searcher = await Searcher.open()
    overall, per_tag = await evaluate(searcher, questions, top_k=top_k)

    print(_format("overall", overall, DEFAULT_KS))
    for tag in sorted(per_tag):
        print(_format(tag, per_tag[tag], DEFAULT_KS))
    if overall.misses:
        print(f"\nmissed ({len(overall.misses)}):")
        for question in overall.misses:
            print(f"  {question}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=pathlib.Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--top-k", type=int, default=max(DEFAULT_KS))
    args = parser.parse_args()
    asyncio.run(run(args.questions, args.top_k))


if __name__ == "__main__":
    main()
