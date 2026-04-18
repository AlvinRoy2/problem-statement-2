"""
core/events.py — SSE Broadcast Hub

Maintains a registry of per-client asyncio Queues.
Any backend code can call `broadcast(payload)` to push a state snapshot
to every connected frontend immediately.
"""
import asyncio
import logging
from typing import Set

logger = logging.getLogger(__name__)

# Global set of active client queues — one per open SSE connection
_subscribers: Set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    """Register a new SSE client and return its dedicated queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.add(q)
    logger.debug(f"[SSE] Client subscribed. Total: {len(_subscribers)}")
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Deregister a client queue when the connection closes."""
    _subscribers.discard(q)
    logger.debug(f"[SSE] Client unsubscribed. Total: {len(_subscribers)}")


async def broadcast(payload: dict) -> None:
    """
    Push a state payload to all connected SSE clients.
    Drops the message for a specific client if its queue is full
    (prevents slow clients from blocking the entire system).
    """
    dead: Set[asyncio.Queue] = set()
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("[SSE] Client queue full — dropping event for slow client.")
        except Exception as e:
            logger.error(f"[SSE] Unexpected queue error: {e}")
            dead.add(q)
    for q in dead:
        _subscribers.discard(q)
