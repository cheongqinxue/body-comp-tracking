"""Streamlit-compatible asyncio runtime helpers."""

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

import streamlit as st

from debug_trace import trace

T = TypeVar("T")

SESSION_EVENT_LOOP_KEY = "asyncio_event_loop"


def _create_event_loop() -> asyncio.AbstractEventLoop:
    """Create and register a new asyncio event loop.

    Returns:
        New event loop for the current Streamlit session.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def get_event_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent asyncio event loop for the Streamlit session.

    Streamlit reruns scripts in a worker thread without a default event loop.
    Keeping one loop per browser session allows async clients and future
    concurrent tasks to reuse the same runtime safely.

    Returns:
        Active asyncio event loop for the current session.
    """
    loop = st.session_state.get(SESSION_EVENT_LOOP_KEY)
    if loop is None or loop.is_closed():
        loop = _create_event_loop()
        st.session_state[SESSION_EVENT_LOOP_KEY] = loop
    return loop


def run_async(coro: Coroutine[object, object, T]) -> T:
    """Run an async operation inside Streamlit without using ``asyncio.run()``.

    Args:
        coro: Coroutine to execute on the session event loop.

    Returns:
        Result returned by the coroutine.

    Raises:
        Exception: Re-raises exceptions raised by the coroutine.
    """
    loop = get_event_loop()
    trace("run_async_started", coroutine=repr(coro))
    try:
        return loop.run_until_complete(coro)
    except RuntimeError as error:
        if "Event loop is closed" not in str(error):
            raise

        loop = _create_event_loop()
        st.session_state[SESSION_EVENT_LOOP_KEY] = loop
        return loop.run_until_complete(coro)
    finally:
        trace("run_async_finished", coroutine=repr(coro))
