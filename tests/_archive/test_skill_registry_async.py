import asyncio
from shopee_agent.skills.registry import Skill, invoke


def test_async_skill_invocation():
    class AsyncSkill(Skill):
        async def run(self, x):
            await asyncio.sleep(0)
            return x + 1

    inst = AsyncSkill()
    result = asyncio.run(invoke(inst, 4))
    assert result == 5


def test_mixed_sync_and_async():
    class SyncSkill(Skill):
        def run(self, x):
            return x * 3

    class AsyncSkill(Skill):
        async def run(self, x):
            await asyncio.sleep(0)
            return x + 2

    sync = SyncSkill()
    asyncs = AsyncSkill()

    assert asyncio.run(invoke(sync, 2)) == 6
    assert asyncio.run(invoke(asyncs, 3)) == 5
