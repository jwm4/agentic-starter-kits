"""EvalHub framework adapter for agentic evaluations."""


def __getattr__(name: str):
    if name == "AgenticEvalAdapter":
        from .adapter import AgenticEvalAdapter

        return AgenticEvalAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AgenticEvalAdapter"]
