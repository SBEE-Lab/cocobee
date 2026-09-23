"""Score the index against a hand-labelled question set.

    python -m cocobee.evals
    python -m cocobee.evals --questions evals/questions.yaml --top-k 10

Every retrieval change — a different embedding model, grouping, a reranker — is
judged by re-running this against the same questions.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

import yaml

from cocobee.search import Searcher

DEFAULT_QUESTIONS = pathlib.Path("evals/questions.yaml")
# The labels quote channel content, so the repo carries only this encrypted copy;
# `sops -d` writes the plaintext the scorer reads.
ENCRYPTED_QUESTIONS = pathlib.Path("evals/questions.enc.yaml")
DEFAULT_KS = (1, 3, 10)


@dataclass(frozen=True, slots=True)
class Question:
    question: str
    expected: frozenset[str]
    tags: tuple[str, ...]

    @property
    def answerable(self) -> bool:
        """An empty `expected` means the channel has no answer: the question is
        there to show what the index does when nothing is relevant."""
        return bool(self.expected)


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
    """Read the plaintext question set, or decrypt the committed one when a fresh
    checkout has no plaintext yet."""
    if not path.exists() and path == DEFAULT_QUESTIONS:
        raise FileNotFoundError(
            f"{path} is not there; decrypt the committed copy first:\n"
            f"  sops -d {ENCRYPTED_QUESTIONS} > {path}"
        )
    raw = yaml.safe_load(path.read_text()) or []
    return [
        Question(
            question=item["question"],
            expected=frozenset(item.get("expected") or ()),
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


@dataclass
class Scores:
    """Top-1 similarity, split by whether an answer exists at all. If the two
    overlap, no score cutoff can stop the index from answering confidently about
    something the channel never discussed."""

    answerable: list[float] = field(default_factory=list)
    unanswerable: list[float] = field(default_factory=list)


async def evaluate(
    searcher: Searcher,
    questions: list[Question],
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
    top_k: int | None = None,
    candidates: int | None = None,
) -> tuple[Report, dict[str, Report], Scores]:
    limit = top_k or max(ks)
    overall = Report()
    per_tag: dict[str, Report] = defaultdict(Report)
    scores = Scores()

    for question in questions:
        hits = await searcher.search(question.question, limit, candidates=candidates)
        top_score = hits[0].score if hits else 0.0
        if not question.answerable:
            scores.unanswerable.append(top_score)
            continue
        scores.answerable.append(top_score)
        rank = next(
            (
                i
                for i, hit in enumerate(hits, start=1)
                if question.expected & ({hit.source_id} | hit.covered)
            ),
            None,
        )
        _record(overall, ks, rank, question.question)
        for tag in question.tags:
            _record(per_tag[tag], ks, rank, question.question)
    return overall, dict(per_tag), scores


def _format(name: str, report: Report, ks: tuple[int, ...]) -> str:
    cells = " ".join(
        f"recall@{k}: {report.recall(k):.2f} ({report.hits.get(k, 0)}/{report.total})"
        for k in ks
    )
    return f"{name:<10} {cells}  MRR: {report.mrr:.2f}"


async def run(
    questions_path: pathlib.Path,
    top_k: int,
    *,
    rerank: bool,
    candidates: int | None = None,
) -> None:
    questions = load_questions(questions_path)
    searcher = await Searcher.open(rerank=rerank)
    overall, per_tag, scores = await evaluate(
        searcher, questions, top_k=top_k, candidates=candidates
    )

    print(f"rerank: {'on' if rerank else 'off'}")
    print(_format("overall", overall, DEFAULT_KS))
    for tag in sorted(per_tag):
        print(_format(tag, per_tag[tag], DEFAULT_KS))

    if scores.unanswerable:
        answerable = sorted(scores.answerable)
        p25 = answerable[len(answerable) // 4]
        print(
            f"\ntop-1 score  answerable: min {min(answerable):.3f},"
            f" p25 {p25:.3f}, median {statistics.median(answerable):.3f}"
            f"  |  unanswerable ({len(scores.unanswerable)}):"
            f" median {statistics.median(scores.unanswerable):.3f},"
            f" max {max(scores.unanswerable):.3f}"
        )
    if overall.misses:
        print(f"\nmissed ({len(overall.misses)}):")
        for question in overall.misses:
            print(f"  {question}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=pathlib.Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--top-k", type=int, default=max(DEFAULT_KS))
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="score the retriever alone, to measure what reranking adds",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=None,
        help="how many sources the reranker sees (default: config.RERANK_CANDIDATES)",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            args.questions,
            args.top_k,
            rerank=not args.no_rerank,
            candidates=args.candidates,
        )
    )


if __name__ == "__main__":
    main()
