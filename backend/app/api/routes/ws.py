"""Room-based WebSocket chat with observable traces and ephemeral presence."""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import settings
from app.core.graph_agent_v2 import ObservableRAGAgent
from app.core.hybrid_retrieval import HybridRetriever, RetrievedChunk
from app.core.security import RateLimitExceeded, ResilientRateLimiter
from app.core.semantic_cache import SemanticCache
from app.models.database import AsyncSessionLocal, ChatSession, User

logger = logging.getLogger(__name__)
router = APIRouter()
PUBLIC_DEMO_SESSION = "live-demo-session"
MAX_DEMO_CONNECTIONS = 50
MAX_DEMO_QUESTION_LENGTH = 500


@dataclass
class Participant:
    user_id: str
    name: str
    avatar: str | None = None

    def public(self) -> dict:
        return {"id": self.user_id, "name": self.name, "avatar": self.avatar}


class ConnectionManager:
    """Local socket fan-out with optional Redis Pub/Sub across instances."""

    def __init__(self):
        self.rooms: Dict[str, Dict[WebSocket, Optional[Participant]]] = {}
        self._local_presence: Dict[str, Dict[str, int]] = {}
        self.redis = None
        self.instance_id = uuid.uuid4().hex
        self._listener_task: asyncio.Task | None = None
        self._presence_heartbeat_task: asyncio.Task | None = None

    def configure_redis(self, redis_client) -> None:
        """Enable shared room events. A missing Redis client stays local-only."""
        self.redis = redis_client if settings.WS_REDIS_BROADCAST_ENABLED else None

    async def start(self) -> None:
        if not self.redis or self._listener_task:
            return
        self._listener_task = asyncio.create_task(self._listen(), name="ws-redis-pubsub")
        self._presence_heartbeat_task = asyncio.create_task(self._refresh_presence(), name="ws-presence-heartbeat")

    async def stop(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        if self._presence_heartbeat_task:
            self._presence_heartbeat_task.cancel()
            try:
                await self._presence_heartbeat_task
            except asyncio.CancelledError:
                pass
            self._presence_heartbeat_task = None

    async def _refresh_presence(self) -> None:
        """Remove crashed-instance presence within one minute, not forever."""
        try:
            while True:
                await asyncio.sleep(30)
                if not self.redis:
                    return
                for session_id in list(self._local_presence):
                    await self.redis.expire(self._presence_key(session_id), 60)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("WebSocket Redis presence heartbeat failed: %s", error)

    async def _listen(self) -> None:
        """Relay events published by other processes to this process's sockets."""
        pubsub = None
        try:
            pubsub = self.redis.pubsub()
            await pubsub.psubscribe("neuralrag:ws:room:*")
            async for item in pubsub.listen():
                if item.get("type") != "pmessage":
                    continue
                payload = json.loads(item["data"])
                if payload.get("origin") == self.instance_id:
                    continue
                await self._broadcast_local(payload["session_id"], payload["message"])
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Redis is an enhancement, not a reason to disconnect sockets.
            logger.warning("WebSocket Redis broadcast unavailable; using local rooms only: %s", error)
            self.redis = None
        finally:
            if pubsub:
                await pubsub.aclose()

    async def connect(self, session_id: str, websocket: WebSocket, participant: Participant | None = None) -> bool:
        # The public demo is intentionally capped. Authenticated rooms are
        # governed by infrastructure/load-balancer limits, not this demo cap.
        if session_id == PUBLIC_DEMO_SESSION and len(self.rooms.get(session_id, {})) >= settings.PUBLIC_DEMO_MAX_CONNECTIONS:
            await websocket.close(code=1013, reason="Demo is busy")
            return False
        await websocket.accept()
        self.rooms.setdefault(session_id, {})[websocket] = participant
        if participant:
            await self._add_presence(session_id, participant)
            await self.broadcast_presence(session_id)
        return True

    async def identify(self, session_id: str, websocket: WebSocket, participant: Participant) -> None:
        room = self.rooms.get(session_id)
        if room is not None and websocket in room:
            old = room[websocket]
            room[websocket] = participant
            if old:
                await self._remove_presence(session_id, old)
            await self._add_presence(session_id, participant)
            await self.broadcast_presence(session_id)

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        room = self.rooms.get(session_id)
        if not room:
            return
        participant = room.pop(websocket, None)
        if participant:
            await self._remove_presence(session_id, participant)
            await self.broadcast_presence(session_id)
        if not room:
            self.rooms.pop(session_id, None)

    def participants(self, session_id: str) -> list[dict]:
        seen: set[str] = set()
        users = []
        for participant in self.rooms.get(session_id, {}).values():
            if participant and participant.user_id not in seen:
                seen.add(participant.user_id)
                users.append(participant.public())
        return users

    def _presence_key(self, session_id: str) -> str:
        return f"neuralrag:ws:presence:{session_id}"

    async def _add_presence(self, session_id: str, participant: Participant) -> None:
        counts = self._local_presence.setdefault(session_id, {})
        counts[participant.user_id] = counts.get(participant.user_id, 0) + 1
        if self.redis:
            try:
                await self.redis.hset(
                    self._presence_key(session_id),
                    f"{self.instance_id}:{participant.user_id}",
                    json.dumps(participant.public()),
                )
                await self.redis.expire(self._presence_key(session_id), 60)
            except Exception as error:
                logger.warning("WebSocket Redis presence update failed; using local presence: %s", error)

    async def _remove_presence(self, session_id: str, participant: Participant) -> None:
        counts = self._local_presence.get(session_id, {})
        remaining = max(0, counts.get(participant.user_id, 1) - 1)
        if remaining:
            counts[participant.user_id] = remaining
            return
        counts.pop(participant.user_id, None)
        if not counts:
            self._local_presence.pop(session_id, None)
        if self.redis:
            try:
                await self.redis.hdel(self._presence_key(session_id), f"{self.instance_id}:{participant.user_id}")
            except Exception as error:
                logger.warning("WebSocket Redis presence removal failed: %s", error)

    async def _distributed_participants(self, session_id: str) -> list[dict]:
        if not self.redis:
            return self.participants(session_id)
        try:
            records = await self.redis.hgetall(self._presence_key(session_id))
            users: dict[str, dict] = {}
            for raw in records.values():
                user = json.loads(raw)
                users.setdefault(user["id"], user)
            return list(users.values())
        except Exception as error:
            logger.warning("WebSocket Redis presence read failed; using local presence: %s", error)
            return self.participants(session_id)

    async def broadcast_presence(self, session_id: str) -> None:
        users = await self._distributed_participants(session_id)
        await self.broadcast(session_id, {"type": "presence", "viewers": len(users), "users": users})

    async def broadcast(self, session_id: str, message: dict) -> None:
        await self._broadcast_local(session_id, message)
        if self.redis:
            try:
                await self.redis.publish(
                    f"neuralrag:ws:room:{session_id}",
                    json.dumps({"origin": self.instance_id, "session_id": session_id, "message": message}),
                )
            except Exception as error:
                logger.warning("WebSocket Redis publish failed; delivered locally only: %s", error)

    async def _broadcast_local(self, session_id: str, message: dict) -> None:
        room = self.rooms.get(session_id, {})
        dead = []
        for client, participant in room.items():
            if participant is None:
                continue
            try:
                await client.send_json(message)
            except Exception:
                dead.append(client)
        for client in dead:
            room.pop(client, None)


manager = ConnectionManager()
_DEMO_DOCS = [
    RetrievedChunk(id="d1", text="Invoice #4471 was issued on March 3rd for the Q1 consulting engagement, totaling $12,400.", metadata={"source": "invoices.pdf"}),
    RetrievedChunk(id="d2", text="Employees must submit expense reports within 30 days of the purchase date to be reimbursed.", metadata={"source": "hr_policy.pdf"}),
    RetrievedChunk(id="d3", text="The reimbursement policy requires all expense claims to be filed within one month of purchase.", metadata={"source": "hr_policy.pdf"}),
    RetrievedChunk(id="d4", text="Our data retention policy stores customer records for 7 years per SOC 2 compliance requirements.", metadata={"source": "security.pdf"}),
    RetrievedChunk(id="d5", text="SOC 2 compliance mandates that customer data be retained for a period of seven years.", metadata={"source": "security.pdf"}),
    RetrievedChunk(id="d6", text="The onboarding checklist includes setting up a company email, laptop provisioning, and Slack access.", metadata={"source": "onboarding.pdf"}),
]
_agent = ObservableRAGAgent(HybridRetriever(_DEMO_DOCS), SemanticCache())


def _guest() -> Participant:
    identity = uuid.uuid4().hex[:6]
    return Participant(user_id=f"guest-{identity}", name="Live explorer")


async def _participant_for_session(session_id: str, token: str | None) -> Participant | None:
    if not token:
        return None
    try:
        user_id = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]).get("sub")
    except JWTError:
        return None
    if not user_id:
        return None
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))).scalar_one_or_none()
        session = (await db.execute(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id))).scalar_one_or_none()
    if not user or not session:
        return None
    return Participant(user_id=user.id, name=user.name or user.email.split("@")[0], avatar=user.picture)


def _rate_limit_identity(participant: Participant | None, client_id: str) -> tuple[str, int]:
    if participant and not participant.user_id.startswith("guest-"):
        return f"chat:user:{participant.user_id}", settings.AUTHENTICATED_CHAT_REQUESTS_PER_MINUTE
    return f"live-demo:{client_id}", settings.PUBLIC_DEMO_REQUESTS_PER_MINUTE


@router.websocket("/ws/chat/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    origin = websocket.headers.get("origin", "").rstrip("/")
    if origin not in settings.allowed_origins:
        await websocket.close(code=1008, reason="Unauthorized origin")
        return

    is_demo = session_id == PUBLIC_DEMO_SESSION
    participant = _guest() if is_demo else None
    if not await manager.connect(session_id, websocket, participant):
        return
    client_id = websocket.headers.get("x-forwarded-for", "").split(",")[0].strip() or (websocket.client.host if websocket.client else "unknown")
    limiter: ResilientRateLimiter = websocket.app.state.rate_limiter
    try:
        # Private rooms require an explicit first-frame join so the JWT never
        # appears in a WebSocket URL or server access log.
        if not participant:
            try:
                join = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=10))
            except (TimeoutError, json.JSONDecodeError, AttributeError):
                await websocket.close(code=1008, reason="Authentication required")
                return
            if join.get("type") != "join":
                await websocket.close(code=1008, reason="Authentication required")
                return
            participant = await _participant_for_session(session_id, join.get("access_token"))
            if not participant:
                await websocket.close(code=1008, reason="Invalid session credentials")
                return
            await manager.identify(session_id, websocket, participant)

        while True:
            try:
                payload = json.loads(await websocket.receive_text())
            except (json.JSONDecodeError, AttributeError):
                await websocket.send_json({"type": "error", "message": "Invalid request"})
                continue

            event_type = payload.get("type")
            if event_type == "typing":
                # Echoing this optional client timestamp is useful for the
                # k6 room-load test and harmless to existing clients.
                await manager.broadcast(session_id, {
                    "type": "typing", "user": participant.public(),
                    "is_typing": bool(payload.get("is_typing")),
                    "client_sent_at": payload.get("client_sent_at"),
                })
                continue
            if event_type == "join":
                continue

            # Only the deliberately public demo runs agent queries over this
            # socket. Private ChatPage messages retain their existing REST API.
            if not is_demo:
                await websocket.send_json({"type": "error", "message": "Use the chat API to send a message"})
                continue
            question = str(payload.get("question", "")).strip()
            if not question or len(question) > MAX_DEMO_QUESTION_LENGTH:
                await websocket.send_json({"type": "error", "message": f"Question must be 1-{MAX_DEMO_QUESTION_LENGTH} characters"})
                continue
            try:
                key, limit = _rate_limit_identity(participant, client_id)
                await limiter.check(key, limit)
            except RateLimitExceeded as error:
                await websocket.send_json({"type": "rate_limit", "message": error.detail, "retry_after": error.headers["Retry-After"]})
                continue
            await manager.broadcast(session_id, {"type": "user_message", "question": question})

            async def trace_callback(event: dict):
                await manager.broadcast(session_id, event)

            await _agent.run_streaming(question, namespace=None, trace_cb=trace_callback, session_id=session_id)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(session_id, websocket)
