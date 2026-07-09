"""Manual test script for LongTermMemory."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ua.database.models import Base, User
from ua.memory.long_term import LongTermMemory


async def main():
    # Create in-memory database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    memory = LongTermMemory(session_factory)

    # Create a user
    async with session_factory() as session:
        user = User(platform="test", platform_user_id="test_user")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    print(f"Created user: {user_id}")

    # Test 1: put then get
    print("\n--- Test 1: put then get ---")
    await memory.put(user_id, "favorite_color", "blue")
    value = await memory.get(user_id, "favorite_color")
    print(f"After first put: {value}")
    assert value == "blue", f"Expected 'blue', got {value}"

    # Test 2: upsert (put same key with different value)
    print("\n--- Test 2: upsert ---")
    await memory.put(user_id, "favorite_color", "green")
    value = await memory.get(user_id, "favorite_color")
    print(f"After second put (upsert): {value}")
    assert value == "green", f"Expected 'green', got {value}"

    # Verify only 1 row exists
    async with session_factory() as session:
        from sqlalchemy import func, select
        result = await session.execute(
            select(func.count()).select_from(Base.metadata.tables["facts"]).where(
                Base.metadata.tables["facts"].c.user_id == user_id,
                Base.metadata.tables["facts"].c.key == "favorite_color"
            )
        )
        count = result.scalar_one()
        print(f"Row count for favorite_color: {count}")
        assert count == 1, f"Expected 1 row, got {count}"

    # Test 3: search
    print("\n--- Test 3: search ---")
    await memory.put(user_id, "hobby", "chess")
    results = await memory.search(user_id, "ch")
    print(f"Search for 'ch': {[(r.key, r.value) for r in results]}")
    assert len(results) == 1
    assert results[0].key == "hobby"
    assert results[0].value == "chess"

    print("\n✅ All manual tests passed!")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
