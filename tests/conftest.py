"""
Pytest fixtures for iMessage extractor tests.

Creates a mock chat.db SQLite database that mimics the macOS iMessage schema.
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime

# Apple epoch starts at 2001-01-01
APPLE_EPOCH = datetime(2001, 1, 1)
NANOSECONDS_PER_SECOND = 1_000_000_000


def datetime_to_apple_time(dt: datetime) -> int:
    """Convert Python datetime to Apple's nanosecond timestamp format."""
    seconds_since_apple_epoch = dt.timestamp() - APPLE_EPOCH.timestamp()
    return int(seconds_since_apple_epoch * NANOSECONDS_PER_SECOND)


@pytest.fixture
def mock_chat_db(tmp_path):
    """
    Create a mock iMessage database with test data.

    Returns the path to the temporary database file.
    """
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the iMessage schema (simplified but matching real structure)
    cursor.executescript("""
        -- Handles table (contacts)
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT UNIQUE,
            service TEXT
        );

        -- Chat table (conversations)
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT,
            display_name TEXT,
            group_id TEXT
        );

        -- Message table
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            text TEXT,
            date INTEGER,
            is_from_me INTEGER,
            handle_id INTEGER,
            cache_has_attachments INTEGER DEFAULT 0,
            FOREIGN KEY (handle_id) REFERENCES handle(ROWID)
        );

        -- Attachment table
        CREATE TABLE attachment (
            ROWID INTEGER PRIMARY KEY,
            mime_type TEXT,
            filename TEXT
        );

        -- Join tables
        CREATE TABLE chat_handle_join (
            chat_id INTEGER,
            handle_id INTEGER,
            FOREIGN KEY (chat_id) REFERENCES chat(ROWID),
            FOREIGN KEY (handle_id) REFERENCES handle(ROWID)
        );

        CREATE TABLE chat_message_join (
            chat_id INTEGER,
            message_id INTEGER,
            FOREIGN KEY (chat_id) REFERENCES chat(ROWID),
            FOREIGN KEY (message_id) REFERENCES message(ROWID)
        );

        CREATE TABLE message_attachment_join (
            message_id INTEGER,
            attachment_id INTEGER,
            FOREIGN KEY (message_id) REFERENCES message(ROWID),
            FOREIGN KEY (attachment_id) REFERENCES attachment(ROWID)
        );
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def populated_chat_db(mock_chat_db):
    """
    Populate the mock database with realistic test data.

    Creates:
    - 3 contacts (handles)
    - 2 individual chats + 1 group chat
    - Multiple messages in each chat
    - Some attachments
    """
    conn = sqlite3.connect(mock_chat_db)
    cursor = conn.cursor()

    # Insert handles (contacts)
    handles = [
        (1, "+15551234567", "iMessage"),
        (2, "friend@email.com", "iMessage"),
        (3, "+15559876543", "iMessage"),
    ]
    cursor.executemany("INSERT INTO handle VALUES (?, ?, ?)", handles)

    # Insert chats
    chats = [
        (1, "+15551234567", "Alice", None),  # Individual chat
        (2, "friend@email.com", "Bob", None),  # Individual chat
        (3, "chat123456", "Work Group", "group_abc"),  # Group chat
    ]
    cursor.executemany("INSERT INTO chat VALUES (?, ?, ?, ?)", chats)

    # Link handles to chats
    chat_handles = [
        (1, 1),  # Alice in chat 1
        (2, 2),  # Bob in chat 2
        (3, 1),  # Alice in group
        (3, 2),  # Bob in group
        (3, 3),  # Third person in group
    ]
    cursor.executemany("INSERT INTO chat_handle_join VALUES (?, ?)", chat_handles)

    # Insert messages with realistic timestamps
    base_time = datetime(2024, 1, 15, 10, 0, 0)

    messages = [
        # Chat with Alice (chat_id=1)
        (1, "Hey, how are you?", datetime_to_apple_time(datetime(2024, 1, 15, 10, 0, 0)), 0, 1, 0),
        (2, "I'm good! Just working on some code", datetime_to_apple_time(datetime(2024, 1, 15, 10, 1, 0)), 1, 1, 0),
        (3, "Nice! What are you building?", datetime_to_apple_time(datetime(2024, 1, 15, 10, 2, 0)), 0, 1, 0),
        (4, "An iMessage bot that responds like me", datetime_to_apple_time(datetime(2024, 1, 15, 10, 3, 0)), 1, 1, 0),
        (5, "That sounds cool!", datetime_to_apple_time(datetime(2024, 1, 15, 10, 4, 0)), 0, 1, 0),
        (6, "Yeah it's going to be awesome", datetime_to_apple_time(datetime(2024, 1, 15, 10, 5, 0)), 1, 1, 0),

        # Chat with Bob (chat_id=2)
        (7, "Did you see the game last night?", datetime_to_apple_time(datetime(2024, 1, 15, 20, 0, 0)), 0, 2, 0),
        (8, "No I missed it, was it good?", datetime_to_apple_time(datetime(2024, 1, 15, 20, 1, 0)), 1, 2, 0),
        (9, "Amazing! You should watch the highlights", datetime_to_apple_time(datetime(2024, 1, 15, 20, 2, 0)), 0, 2, 0),
        (10, "Will do, thanks!", datetime_to_apple_time(datetime(2024, 1, 15, 20, 3, 0)), 1, 2, 0),

        # Group chat (chat_id=3)
        (11, "Team meeting at 3pm", datetime_to_apple_time(datetime(2024, 1, 16, 9, 0, 0)), 0, 3, 0),
        (12, "Sounds good", datetime_to_apple_time(datetime(2024, 1, 16, 9, 1, 0)), 1, 3, 0),
        (13, "I'll be there", datetime_to_apple_time(datetime(2024, 1, 16, 9, 2, 0)), 0, 1, 0),

        # Message with attachment (in chat 1)
        (14, "Check out this photo", datetime_to_apple_time(datetime(2024, 1, 15, 11, 0, 0)), 0, 1, 1),
        (15, "Wow that looks great!", datetime_to_apple_time(datetime(2024, 1, 15, 11, 1, 0)), 1, 1, 0),
    ]
    cursor.executemany(
        "INSERT INTO message (ROWID, text, date, is_from_me, handle_id, cache_has_attachments) VALUES (?, ?, ?, ?, ?, ?)",
        messages
    )

    # Link messages to chats
    chat_messages = [
        (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6),  # Alice chat
        (2, 7), (2, 8), (2, 9), (2, 10),  # Bob chat
        (3, 11), (3, 12), (3, 13),  # Group chat
        (1, 14), (1, 15),  # More Alice messages
    ]
    cursor.executemany("INSERT INTO chat_message_join VALUES (?, ?)", chat_messages)

    # Insert attachment
    cursor.execute("INSERT INTO attachment VALUES (1, 'image/jpeg', 'photo.jpg')")
    cursor.execute("INSERT INTO message_attachment_join VALUES (14, 1)")

    conn.commit()
    conn.close()

    return mock_chat_db


@pytest.fixture
def empty_chat_db(mock_chat_db):
    """Return the empty mock database (schema only, no data)."""
    return mock_chat_db


@pytest.fixture
def extractor(populated_chat_db):
    """Create a MessageExtractor instance with the populated test database."""
    from src.extractor.chat_db import MessageExtractor

    extractor = MessageExtractor(populated_chat_db)
    extractor.connect()
    yield extractor
    extractor.close()


@pytest.fixture
def export_dir(tmp_path):
    """Create a temporary directory for export tests."""
    export_path = tmp_path / "exports"
    export_path.mkdir()
    return export_path
