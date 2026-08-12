import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes.ws import ConnectionManager, Participant, PUBLIC_DEMO_SESSION
import app.api.routes.ws as ws_module


class FakeSocket:
    def __init__(self):
        self.events = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, event):
        self.events.append(event)

    async def close(self, **kwargs):
        return None


@pytest.mark.asyncio
async def test_presence_broadcasts_named_participants_on_join_and_leave():
    manager = ConnectionManager()
    first, second = FakeSocket(), FakeSocket()
    await manager.connect("session", first, Participant("u1", "Aarav", "https://avatar.test/a.png"))
    await manager.connect("session", second, Participant("u2", "Maya"))

    joined = second.events[-1]
    assert joined == {"type": "presence", "viewers": 2, "users": [
        {"id": "u1", "name": "Aarav", "avatar": "https://avatar.test/a.png"},
        {"id": "u2", "name": "Maya", "avatar": None},
    ]}

    await manager.disconnect("session", second)
    assert first.events[-1] == {"type": "presence", "viewers": 1, "users": [{"id": "u1", "name": "Aarav", "avatar": "https://avatar.test/a.png"}]}


@pytest.mark.asyncio
async def test_typing_event_is_ephemeral_room_broadcast():
    manager = ConnectionManager()
    first, second = FakeSocket(), FakeSocket()
    user = Participant("u1", "Aarav")
    await manager.connect("session", first, user)
    await manager.connect("session", second, Participant("u2", "Maya"))
    await manager.broadcast("session", {"type": "typing", "user": user.public(), "is_typing": True})
    assert second.events[-1] == {"type": "typing", "user": {"id": "u1", "name": "Aarav", "avatar": None}, "is_typing": True}


class FakeRedis:
    def __init__(self): self.published = []; self.hashes = {}
    async def publish(self, channel, body): self.published.append((channel, body))
    async def hset(self, key, field, value): self.hashes.setdefault(key, {})[field] = value
    async def expire(self, key, seconds): return True
    async def hdel(self, key, field): self.hashes.get(key, {}).pop(field, None)
    async def hgetall(self, key): return self.hashes.get(key, {})


@pytest.mark.asyncio
async def test_redis_room_broadcast_keeps_local_fanout_and_publishes_envelope():
    manager = ConnectionManager()
    redis = FakeRedis()
    manager.configure_redis(redis)
    socket = FakeSocket()
    await manager.connect("shared", socket, Participant("u1", "Aarav"))

    await manager.broadcast("shared", {"type": "typing", "is_typing": True})

    assert socket.events[-1] == {"type": "typing", "is_typing": True}
    channel, raw = redis.published[-1]
    payload = __import__("json").loads(raw)
    assert channel == "neuralrag:ws:room:shared"
    assert payload["session_id"] == "shared"
    assert payload["message"]["type"] == "typing"
    assert payload["origin"] == manager.instance_id


@pytest.mark.asyncio
async def test_redis_presence_combines_users_from_multiple_instances():
    redis = FakeRedis()
    first, second = ConnectionManager(), ConnectionManager()
    first.configure_redis(redis); second.configure_redis(redis)
    first_socket, second_socket = FakeSocket(), FakeSocket()
    await first.connect("shared", first_socket, Participant("u1", "Aarav"))
    await second.connect("shared", second_socket, Participant("u2", "Maya"))

    await first.broadcast_presence("shared")
    event = first_socket.events[-1]
    assert event["type"] == "presence"
    assert {user["id"] for user in event["users"]} == {"u1", "u2"}


@pytest.mark.asyncio
async def test_public_demo_cap_does_not_limit_authenticated_rooms(monkeypatch):
    monkeypatch.setattr(ws_module.settings, "PUBLIC_DEMO_MAX_CONNECTIONS", 1)
    manager = ConnectionManager()
    first, second, private = FakeSocket(), FakeSocket(), FakeSocket()
    assert await manager.connect(PUBLIC_DEMO_SESSION, first, Participant("u1", "Aarav"))
    assert not await manager.connect(PUBLIC_DEMO_SESSION, second, Participant("u2", "Maya"))
    assert await manager.connect("private-session", private, Participant("u3", "Sam"))
