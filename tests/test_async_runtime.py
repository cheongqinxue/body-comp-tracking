"""Tests for Streamlit asyncio runtime helpers."""

import asyncio
from unittest.mock import patch

import pytest

from async_runtime import SESSION_EVENT_LOOP_KEY, get_event_loop, run_async


class TestAsyncRuntime:
    """Tests for session-scoped asyncio helpers."""

    @pytest.fixture
    def session_state(self) -> dict[str, object]:
        """Provide a mock Streamlit session state dictionary.

        Returns:
            Empty session state mapping.
        """
        return {}

    def test_run_async_executes_coroutine(self, session_state: dict[str, object]) -> None:
        """Execute a coroutine through the session event loop.

        Args:
            session_state: Mock Streamlit session state.
        """
        async def sample_coro() -> str:
            return "done"

        with patch("async_runtime.st.session_state", session_state):
            result = run_async(sample_coro())

        assert result == "done"
        assert SESSION_EVENT_LOOP_KEY in session_state

    def test_get_event_loop_reuses_existing_loop(self, session_state: dict[str, object]) -> None:
        """Reuse the same event loop across repeated lookups.

        Args:
            session_state: Mock Streamlit session state.
        """
        with patch("async_runtime.st.session_state", session_state):
            first_loop = get_event_loop()
            second_loop = get_event_loop()

        assert first_loop is second_loop
        assert not first_loop.is_closed()

    def test_run_async_recreates_closed_loop(self, session_state: dict[str, object]) -> None:
        """Create a fresh loop when the stored loop has been closed.

        Args:
            session_state: Mock Streamlit session state.
        """
        closed_loop = asyncio.new_event_loop()
        closed_loop.close()
        session_state[SESSION_EVENT_LOOP_KEY] = closed_loop

        async def sample_coro() -> int:
            return 7

        with patch("async_runtime.st.session_state", session_state):
            result = run_async(sample_coro())

        assert result == 7
        replacement_loop = session_state[SESSION_EVENT_LOOP_KEY]
        assert isinstance(replacement_loop, asyncio.AbstractEventLoop)
        assert not replacement_loop.is_closed()
        assert replacement_loop is not closed_loop
