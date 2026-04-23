"""Benchmark registry and golden query loader for EvalHub."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


# Resolve fixtures relative to the behavioral tests root (one level up from this package)
_BEHAVIORAL_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES_DIR = _BEHAVIORAL_ROOT / "fixtures" / "benchmarks"


@dataclass
class QuerySpec:
    """A single golden query with expected outcomes."""

    query: str
    expected_tools: list[str] = field(default_factory=list)
    expected_elements: list[str] = field(default_factory=list)


@dataclass
class BenchmarkDef:
    """Definition of a benchmark: which queries to run and which scorers to apply."""

    queries_file: str
    scorers: list[str]


# Registry of available benchmarks. Currently ships agentic-tool-use only;
# additional benchmarks (coherence, safety, latency) will be added as query
# files are populated.
BENCHMARKS: dict[str, BenchmarkDef] = {
    "agentic-tool-use": BenchmarkDef(
        queries_file="tool_use.yaml",
        scorers=[
            "tool_selection",
            "tool_sequence",
            "hallucinated_tools",
            "tool_call_validity",
        ],
    ),
}

# Which scorers to run when "all" is specified
ALL_SCORERS = [
    "tool_selection",
    "tool_sequence",
    "hallucinated_tools",
    "tool_call_validity",
    "plan_coherence",
    "completeness",
    "latency",
    "pii_leakage",
    "policy_adherence",
    "injection_resistance",
]


def get_benchmark(benchmark_id: str) -> BenchmarkDef:
    """Look up a benchmark by ID. Raises ValueError if unknown."""
    if benchmark_id not in BENCHMARKS:
        available = ", ".join(sorted(BENCHMARKS.keys()))
        raise ValueError(
            f"Unknown benchmark '{benchmark_id}'. Available: {available}"
        )
    return BENCHMARKS[benchmark_id]


def resolve_scorers(benchmark: BenchmarkDef) -> list[str]:
    """Expand 'all' to the full scorer list."""
    if "all" in benchmark.scorers:
        return list(ALL_SCORERS)
    return list(benchmark.scorers)


def load_queries(benchmark: BenchmarkDef) -> list[QuerySpec]:
    """Load golden queries from the benchmark's YAML file."""
    path = _FIXTURES_DIR / benchmark.queries_file
    if not path.exists():
        raise FileNotFoundError(f"Benchmark queries file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return []

    queries: list[QuerySpec] = []
    for i, entry in enumerate(data.get("queries") or []):
        if "query" not in entry:
            raise ValueError(
                f"Query entry {i} missing required 'query' field in {path}"
            )
        queries.append(
            QuerySpec(
                query=entry["query"],
                expected_tools=entry.get("expected_tools", []),
                expected_elements=entry.get("expected_elements", []),
            )
        )
    return queries
