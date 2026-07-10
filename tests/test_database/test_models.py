import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ua.database.models import Fact, KnowledgeDocument, Message, Session, User


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
async def test_knowledge_document_relationship(db_session):
    """Test KnowledgeDocument -> User relationship."""
    # Create a user
    user = User(platform="discord", platform_user_id="12345")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Create a knowledge document for the user
    doc = KnowledgeDocument(
        user_id=user.id,
        title="Meeting Notes",
        content="We discussed the Q3 roadmap and chess strategy.",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    assert doc.id is not None
    assert doc.user_id == user.id
    assert doc.title == "Meeting Notes"
    assert doc.content == "We discussed the Q3 roadmap and chess strategy."
    assert doc.created_at is not None

    # Verify the relationship from User back to documents
    # Need to load the relationship within the session context
    result = await db_session.execute(
        select(User).where(User.id == user.id).options(selectinload(User.documents))
    )
    fetched_user = result.scalar_one()
    assert len(fetched_user.documents) == 1
    assert fetched_user.documents[0].id == doc.id
    assert fetched_user.documents[0].title == "Meeting Notes"
