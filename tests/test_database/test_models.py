import pytest
from sqlalchemy import select

from ua.database.models import Fact, Message, Session, User


@pytest.mark.asyncio
async def test_user_creation(db_session):
    """Test creating a User row."""
    user = User(platform="discord", platform_user_id="12345")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.id is not None
    assert user.platform == "discord"
    assert user.platform_user_id == "12345"
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_user_query(db_session):
    """Test querying a User row."""
    user = User(platform="discord", platform_user_id="12345")
    db_session.add(user)
    await db_session.commit()

    result = await db_session.execute(select(User).where(User.platform == "discord"))
    fetched = result.scalar_one()

    assert fetched.id == user.id
    assert fetched.platform == "discord"


@pytest.mark.asyncio
async def test_foreign_key_relationships(db_session):
    """Test Message -> Session -> User and Fact -> User relationships."""
    # Create a user
    user = User(platform="discord", platform_user_id="12345")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Create a session for the user
    session = Session(user_id=user.id, platform="discord")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    # Create a message in the session
    message = Message(session_id=session.id, role="user", content="Hello!")
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    assert message.session_id == session.id
    assert message.role == "user"
    assert message.content == "Hello!"

    # Create a fact for the user
    fact = Fact(user_id=user.id, key="name", value="Alice")
    db_session.add(fact)
    await db_session.commit()
    await db_session.refresh(fact)

    assert fact.user_id == user.id
    assert fact.key == "name"
    assert fact.value == "Alice"


@pytest.mark.asyncio
async def test_cascade_delete_user_removes_sessions(db_session):
    """Test that deleting a user cascades to sessions."""
    user = User(platform="discord", platform_user_id="12345")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    session = Session(user_id=user.id, platform="discord")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    session_id = session.id

    # Delete the user
    await db_session.delete(user)
    await db_session.commit()

    # Verify session is gone
    result = await db_session.execute(select(Session).where(Session.id == session_id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_cascade_delete_session_removes_messages(db_session):
    """Test that deleting a session cascades to messages."""
    user = User(platform="discord", platform_user_id="12345")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    session = Session(user_id=user.id, platform="discord")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    message = Message(session_id=session.id, role="user", content="Hello!")
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    message_id = message.id

    # Delete the session
    await db_session.delete(session)
    await db_session.commit()

    # Verify message is gone
    result = await db_session.execute(select(Message).where(Message.id == message_id))
    assert result.scalar_one_or_none() is None
