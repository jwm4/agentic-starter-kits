"""Unit tests for evalhub_adapter config and benchmarks modules.

Covers AgenticEvalParams.from_dict(), job_spec_to_task_config(),
get_benchmark(), resolve_scorers(), and load_queries().
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from evalhub_adapter.benchmarks import (
    ALL_SCORERS,
    BENCHMARKS,
    BenchmarkDef,
    QuerySpec,
    get_benchmark,
    load_queries,
    resolve_scorers,
)
from evalhub_adapter.config import AgenticEvalParams, job_spec_to_task_config
from harness.runner import TaskConfig

pytestmark = pytest.mark.unit


class TestAgenticEvalParamsFromDict:
    """Tests for constructing AgenticEvalParams from a raw dict."""

    def test_from_dict_with_known_keys(self):
        """Known keys are set on the resulting dataclass."""
        raw = {
            "known_tools": ["search", "calculator"],
            "forbidden_actions": ["shell execution"],
            "max_latency_seconds": 5.0,
            "timeout_seconds": 60.0,
            "verify_ssl": True,
            "mlflow_tracking_uri": "http://mlflow:5000",
            "mlflow_experiment_name": "my-exp",
        }
        params = AgenticEvalParams.from_dict(raw)

        assert params.known_tools == ["search", "calculator"]
        assert params.forbidden_actions == ["shell execution"]
        assert params.max_latency_seconds == 5.0
        assert params.timeout_seconds == 60.0
        assert params.verify_ssl is True
        assert params.mlflow_tracking_uri == "http://mlflow:5000"
        assert params.mlflow_experiment_name == "my-exp"

    def test_from_dict_ignores_unknown_keys(self):
        """Unknown keys in the dict are silently dropped."""
        raw = {
            "known_tools": ["web_search"],
            "totally_made_up": True,
            "another_unknown": 42,
        }
        params = AgenticEvalParams.from_dict(raw)

        assert params.known_tools == ["web_search"]
        assert not hasattr(params, "totally_made_up")
        assert not hasattr(params, "another_unknown")

    def test_from_dict_defaults(self):
        """An empty dict produces an instance with all default values."""
        params = AgenticEvalParams.from_dict({})

        assert params.known_tools == []
        assert params.forbidden_actions == []
        assert params.max_latency_seconds == 10.0
        assert params.timeout_seconds == 30.0
        assert params.verify_ssl is True
        assert params.mlflow_tracking_uri is None
        assert params.mlflow_experiment_name is None

    def test_from_dict_partial(self):
        """Supplying only some keys sets those; the rest stay at defaults."""
        raw = {
            "timeout_seconds": 120.0,
        }
        params = AgenticEvalParams.from_dict(raw)

        assert params.timeout_seconds == 120.0
        assert params.known_tools == []  # other defaults unchanged


class TestJobSpecToTaskConfig:
    """Tests for translating EvalHub job parameters into TaskConfig."""

    def test_job_spec_to_task_config(self):
        """All fields are mapped correctly into a TaskConfig."""
        params = AgenticEvalParams(timeout_seconds=45.0)
        cfg = job_spec_to_task_config(
            agent_url="http://agent:8000",
            query="What is the weather?",
            expected_tools=["get_weather"],
            params=params,
            model_name="gpt-4o",
        )

        assert isinstance(cfg, TaskConfig)
        assert cfg.agent_url == "http://agent:8000"
        assert cfg.query == "What is the weather?"
        assert cfg.expected_tools == ["get_weather"]
        assert cfg.timeout_seconds == 45.0
        assert cfg.model == "gpt-4o"

    def test_job_spec_to_task_config_no_model(self):
        """model defaults to None when not provided."""
        params = AgenticEvalParams()
        cfg = job_spec_to_task_config(
            agent_url="http://agent:8000",
            query="Hello",
            expected_tools=None,
            params=params,
        )

        assert cfg.model is None
        assert cfg.expected_tools is None
        assert cfg.timeout_seconds == 30.0


EXPECTED_BENCHMARK_IDS = [
    "agentic-tool-use",
]


class TestGetBenchmark:
    """Tests for the BENCHMARKS registry and get_benchmark()."""

    @pytest.mark.parametrize("benchmark_id", EXPECTED_BENCHMARK_IDS)
    def test_get_benchmark_valid(self, benchmark_id: str):
        """Each registered benchmark ID returns a BenchmarkDef."""
        bm = get_benchmark(benchmark_id)
        assert isinstance(bm, BenchmarkDef)
        assert bm.queries_file, "queries_file must be a non-empty string"
        assert isinstance(bm.scorers, list)

    def test_get_benchmark_unknown_raises(self):
        """An unknown benchmark ID raises ValueError listing available IDs."""
        with pytest.raises(ValueError, match="no-such-benchmark") as exc_info:
            get_benchmark("no-such-benchmark")

        error_msg = str(exc_info.value)
        for bid in BENCHMARKS:
            assert bid in error_msg, (
                f"Error message should list available benchmark '{bid}'"
            )

    def test_expected_ids_match_registry(self):
        """EXPECTED_BENCHMARK_IDS stays in sync with BENCHMARKS registry."""
        assert set(EXPECTED_BENCHMARK_IDS) == set(BENCHMARKS.keys())


class TestResolveScorers:
    """Tests for resolve_scorers()."""

    def test_resolve_scorers_specific(self):
        """A benchmark with explicit scorers returns that exact list."""
        bm = get_benchmark("agentic-tool-use")
        scorers = resolve_scorers(bm)

        assert scorers == [
            "tool_selection",
            "tool_sequence",
            "hallucinated_tools",
            "tool_call_validity",
        ]

    def test_resolve_scorers_all(self):
        """The 'all' sentinel expands to ALL_SCORERS."""
        bm = BenchmarkDef(queries_file="unused.yaml", scorers=["all"])
        scorers = resolve_scorers(bm)
        assert scorers == list(ALL_SCORERS)

    def test_resolve_scorers_empty(self):
        """A benchmark with no scorers returns an empty list."""
        bm = BenchmarkDef(queries_file="unused.yaml", scorers=[])
        assert resolve_scorers(bm) == []

    def test_all_scorers_contains_expected(self):
        """ALL_SCORERS has exactly the 10 known scorer names."""
        expected = {
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
        }
        assert set(ALL_SCORERS) == expected
        assert len(ALL_SCORERS) == len(set(ALL_SCORERS))


class TestLoadQueries:
    """Tests for loading query files into QuerySpec lists."""

    def test_load_queries_valid_file(self, fixtures_dir: Path):
        """A well-formed YAML produces a list of QuerySpec objects."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "What is 2+2?"
                expected_tools: ["calculator"]
                expected_elements: ["4"]
              - query: "Search for cats"
                expected_tools: ["web_search"]
        """)
        (fixtures_dir / "test_queries.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="test_queries.yaml", scorers=["tool_selection"])

        queries = load_queries(bm)

        assert len(queries) == 2
        assert isinstance(queries[0], QuerySpec)
        assert queries[0].query == "What is 2+2?"
        assert queries[0].expected_tools == ["calculator"]
        assert queries[0].expected_elements == ["4"]
        assert queries[1].query == "Search for cats"

    def test_load_queries_missing_file(self, fixtures_dir: Path):
        """A non-existent queries file raises FileNotFoundError."""
        bm = BenchmarkDef(queries_file="does_not_exist.yaml", scorers=[])

        with pytest.raises(FileNotFoundError, match=r"does_not_exist\.yaml"):
            load_queries(bm)

    def test_load_queries_empty(self, fixtures_dir: Path):
        """An empty queries list produces an empty result."""
        yaml_content = textwrap.dedent("""\
            queries: []
        """)
        (fixtures_dir / "empty.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="empty.yaml", scorers=[])

        queries = load_queries(bm)

        assert queries == []

    def test_load_queries_defaults(self, fixtures_dir: Path):
        """Missing optional fields default to empty lists."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "Hello world"
        """)
        (fixtures_dir / "defaults.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="defaults.yaml", scorers=[])

        queries = load_queries(bm)

        assert len(queries) == 1
        assert queries[0].query == "Hello world"
        assert queries[0].expected_tools == []
        assert queries[0].expected_elements == []

    def test_load_queries_null_value(self, fixtures_dir: Path):
        """queries: null (YAML None) returns an empty list, not TypeError."""
        (fixtures_dir / "null_queries.yaml").write_text("queries:\n")
        bm = BenchmarkDef(queries_file="null_queries.yaml", scorers=[])

        queries = load_queries(bm)
        assert queries == []

    def test_load_queries_missing_query_key(self, fixtures_dir: Path):
        """A query entry without 'query' raises KeyError."""
        yaml_content = textwrap.dedent("""\
            queries:
              - expected_tools: ["search"]
        """)
        (fixtures_dir / "bad_entry.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="bad_entry.yaml", scorers=[])

        with pytest.raises(KeyError, match="query"):
            load_queries(bm)


class TestRealFixtures:
    """Integration tests that verify real benchmark fixture files load correctly."""

    @pytest.mark.parametrize("benchmark_id", EXPECTED_BENCHMARK_IDS)
    def test_real_fixture_files_parse(self, benchmark_id: str):
        """Every registered benchmark's YAML loads without error."""
        bm = get_benchmark(benchmark_id)
        queries = load_queries(bm)
        assert isinstance(queries, list)
        for q in queries:
            assert isinstance(q, QuerySpec)
            assert isinstance(q.query, str)
            assert q.query, "Query text must be non-empty"
