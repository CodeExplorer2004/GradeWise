import json
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()


class ConversationMemory:
    def __init__(self) -> None:
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    @staticmethod
    def _key(user_id: int, conversation_id: str) -> str:
        return f"gradewise:chat:{user_id}:{conversation_id}"

    async def get(self, user_id: int, conversation_id: str) -> list[dict[str, Any]]:
        raw = await self.redis.get(self._key(user_id, conversation_id))
        return json.loads(raw) if raw else []

    async def append(
        self,
        user_id: int,
        conversation_id: str,
        role: str,
        content: str,
        **metadata: Any,
    ) -> None:
        key = self._key(user_id, conversation_id)
        history = await self.get(user_id, conversation_id)
        history.append({"role": role, "content": content, **metadata})
        history = history[-12:]
        await self.redis.set(
            key,
            json.dumps(history, ensure_ascii=False, default=str),
            ex=settings.conversation_ttl_seconds,
        )

    async def delete(self, user_id: int, conversation_id: str) -> None:
        await self.redis.delete(self._key(user_id, conversation_id))


conversation_memory = ConversationMemory()
