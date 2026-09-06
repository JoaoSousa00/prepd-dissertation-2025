import os

import pytest

from src.shared.tracing import reset_tracing_state_for_tests


# Hard-disable tracing defaults for test runs, even when developer machines have
# Langfuse credentials exported in the shell.
os.environ["TRACING_ENABLED"] = "false"
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
os.environ.pop("LANGFUSE_BASE_URL", None)


@pytest.fixture(autouse=True)
def _disable_langfuse_for_tests(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRACING_ENABLED", "false")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    reset_tracing_state_for_tests()
    yield
    reset_tracing_state_for_tests()
