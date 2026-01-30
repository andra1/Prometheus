"""
Comprehensive tests for the iMessage extractor module.
"""

import pytest
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.extractor.chat_db import (
    Message,
    Conversation,
    MessageExtractor,
    APPLE_EPOCH,
    NANOSECONDS_PER_SECOND,
    main,
)


def datetime_to_apple_time(dt: datetime) -> int:
    """Convert Python datetime to Apple's nanosecond timestamp format."""
    seconds_since_apple_epoch = dt.timestamp() - APPLE_EPOCH.timestamp()
    return int(seconds_since_apple_epoch * NANOSECONDS_PER_SECOND)


class TestMessageDataclass:
    """Tests for the Message dataclass."""

    def test_message_creation(self):
        """Test creating a Message with all fields."""
        msg = Message(
            id=1,
            text="Hello world",
            date=datetime(2024, 1, 15, 10, 0, 0),
            is_from_me=True,
            handle="+15551234567",
            chat_id=1,
            is_group_chat=False,
            has_attachment=False,
            attachment_types=[]
        )

        assert msg.id == 1
        assert msg.text == "Hello world"
        assert msg.is_from_me is True
        assert msg.handle == "+15551234567"
        assert msg.chat_id == 1
        assert msg.is_group_chat is False
        assert msg.has_attachment is False
        assert msg.attachment_types == []

    def test_message_with_none_text(self):
        """Test Message can have None text (e.g., attachment-only messages)."""
        msg = Message(
            id=1,
            text=None,
            date=datetime(2024, 1, 15, 10, 0, 0),
            is_from_me=False,
            handle="+15551234567",
            chat_id=1,
            is_group_chat=False,
            has_attachment=True,
            attachment_types=["image/jpeg"]
        )

        assert msg.text is None
        assert msg.has_attachment is True
        assert msg.attachment_types == ["image/jpeg"]

    def test_message_to_dict(self):
        """Test Message serialization to dictionary."""
        dt = datetime(2024, 1, 15, 10, 0, 0)
        msg = Message(
            id=1,
            text="Test",
            date=dt,
            is_from_me=True,
            handle="+15551234567",
            chat_id=1,
            is_group_chat=False,
            has_attachment=False,
            attachment_types=[]
        )

        d = msg.to_dict()

        assert d['id'] == 1
        assert d['text'] == "Test"
        assert d['date'] == dt.isoformat()
        assert d['is_from_me'] is True
        assert d['handle'] == "+15551234567"

    def test_message_to_dict_preserves_all_fields(self):
        """Test that to_dict includes all Message fields."""
        msg = Message(
            id=42,
            text="Full message",
            date=datetime(2024, 6, 20, 15, 30, 45),
            is_from_me=False,
            handle="test@email.com",
            chat_id=5,
            is_group_chat=True,
            has_attachment=True,
            attachment_types=["image/png", "video/mp4"]
        )

        d = msg.to_dict()

        assert set(d.keys()) == {
            'id', 'text', 'date', 'is_from_me', 'handle',
            'chat_id', 'is_group_chat', 'has_attachment', 'attachment_types'
        }


class TestConversationDataclass:
    """Tests for the Conversation dataclass."""

    def test_conversation_creation(self):
        """Test creating a Conversation."""
        conv = Conversation(
            chat_id=1,
            display_name="Alice",
            participants=["+15551234567"],
            is_group_chat=False,
            messages=[]
        )

        assert conv.chat_id == 1
        assert conv.display_name == "Alice"
        assert conv.participants == ["+15551234567"]
        assert conv.is_group_chat is False
        assert conv.messages == []

    def test_conversation_my_messages(self):
        """Test filtering messages sent by the user."""
        messages = [
            Message(1, "Hi", datetime.now(), False, "+1", 1, False, False),
            Message(2, "Hello", datetime.now(), True, "+1", 1, False, False),
            Message(3, "How are you?", datetime.now(), False, "+1", 1, False, False),
            Message(4, "Good!", datetime.now(), True, "+1", 1, False, False),
        ]

        conv = Conversation(
            chat_id=1,
            display_name="Test",
            participants=["+1"],
            is_group_chat=False,
            messages=messages
        )

        my_msgs = conv.my_messages
        assert len(my_msgs) == 2
        assert all(m.is_from_me for m in my_msgs)
        assert my_msgs[0].text == "Hello"
        assert my_msgs[1].text == "Good!"

    def test_conversation_their_messages(self):
        """Test filtering messages received from others."""
        messages = [
            Message(1, "Hi", datetime.now(), False, "+1", 1, False, False),
            Message(2, "Hello", datetime.now(), True, "+1", 1, False, False),
            Message(3, "How are you?", datetime.now(), False, "+1", 1, False, False),
        ]

        conv = Conversation(
            chat_id=1,
            display_name="Test",
            participants=["+1"],
            is_group_chat=False,
            messages=messages
        )

        their_msgs = conv.their_messages
        assert len(their_msgs) == 2
        assert all(not m.is_from_me for m in their_msgs)

    def test_conversation_to_dict(self):
        """Test Conversation serialization."""
        messages = [
            Message(1, "Hi", datetime(2024, 1, 1), False, "+1", 1, False, False),
            Message(2, "Hello", datetime(2024, 1, 1), True, "+1", 1, False, False),
        ]

        conv = Conversation(
            chat_id=1,
            display_name="Alice",
            participants=["+15551234567"],
            is_group_chat=False,
            messages=messages
        )

        d = conv.to_dict()

        assert d['chat_id'] == 1
        assert d['display_name'] == "Alice"
        assert d['participants'] == ["+15551234567"]
        assert d['is_group_chat'] is False
        assert d['message_count'] == 2
        assert d['my_message_count'] == 1
        assert len(d['messages']) == 2

    def test_empty_conversation_properties(self):
        """Test properties on empty conversation."""
        conv = Conversation(
            chat_id=1,
            display_name="Empty",
            participants=[],
            is_group_chat=False,
            messages=[]
        )

        assert conv.my_messages == []
        assert conv.their_messages == []
        assert conv.to_dict()['message_count'] == 0


class TestMessageExtractorConnection:
    """Tests for MessageExtractor connection handling."""

    def test_connect_to_valid_database(self, populated_chat_db):
        """Test connecting to a valid database."""
        extractor = MessageExtractor(populated_chat_db)
        extractor.connect()

        assert extractor._conn is not None
        extractor.close()

    def test_connect_to_nonexistent_database(self, tmp_path):
        """Test error when database doesn't exist."""
        fake_path = tmp_path / "nonexistent.db"
        extractor = MessageExtractor(fake_path)

        with pytest.raises(FileNotFoundError) as exc_info:
            extractor.connect()

        assert "iMessage database not found" in str(exc_info.value)

    def test_close_connection(self, populated_chat_db):
        """Test closing the database connection."""
        extractor = MessageExtractor(populated_chat_db)
        extractor.connect()
        extractor.close()

        assert extractor._conn is None

    def test_close_without_connect(self, populated_chat_db):
        """Test closing without connecting doesn't raise."""
        extractor = MessageExtractor(populated_chat_db)
        extractor.close()  # Should not raise

    def test_context_manager(self, populated_chat_db):
        """Test using extractor as context manager."""
        with MessageExtractor(populated_chat_db) as extractor:
            assert extractor._conn is not None

        # Connection should be closed after exiting context
        assert extractor._conn is None

    def test_context_manager_with_exception(self, populated_chat_db):
        """Test context manager closes connection on exception."""
        extractor = MessageExtractor(populated_chat_db)

        with pytest.raises(ValueError):
            with extractor:
                assert extractor._conn is not None
                raise ValueError("Test error")

        assert extractor._conn is None

    def test_default_db_path(self):
        """Test default database path is set correctly."""
        extractor = MessageExtractor()
        expected = Path.home() / "Library" / "Messages" / "chat.db"
        assert extractor.db_path == expected


class TestAppleTimeConversion:
    """Tests for Apple timestamp conversion."""

    def test_convert_nanosecond_timestamp(self, extractor):
        """Test converting modern nanosecond timestamps."""
        # January 15, 2024 10:00:00 as Apple nanoseconds
        dt = datetime(2024, 1, 15, 10, 0, 0)
        apple_time = int((dt.timestamp() - APPLE_EPOCH.timestamp()) * NANOSECONDS_PER_SECOND)

        result = extractor._apple_time_to_datetime(apple_time)

        # Allow 1 second tolerance for floating point
        assert abs((result - dt).total_seconds()) < 1

    def test_convert_legacy_second_timestamp(self, extractor):
        """Test converting older second-based timestamps."""
        # Some older messages use seconds instead of nanoseconds
        dt = datetime(2020, 6, 15, 12, 0, 0)
        apple_time = int(dt.timestamp() - APPLE_EPOCH.timestamp())

        result = extractor._apple_time_to_datetime(apple_time)

        assert abs((result - dt).total_seconds()) < 1

    def test_convert_none_timestamp(self, extractor):
        """Test handling None timestamp."""
        result = extractor._apple_time_to_datetime(None)
        assert result == datetime.min


class TestGetAllHandles:
    """Tests for retrieving handles (contacts)."""

    def test_get_all_handles(self, extractor):
        """Test retrieving all handles from database."""
        handles = extractor.get_all_handles()

        assert len(handles) == 3
        assert handles[1] == "+15551234567"
        assert handles[2] == "friend@email.com"
        assert handles[3] == "+15559876543"

    def test_get_handles_empty_db(self, empty_chat_db):
        """Test getting handles from empty database."""
        with MessageExtractor(empty_chat_db) as extractor:
            handles = extractor.get_all_handles()
            assert handles == {}


class TestGetChatParticipants:
    """Tests for retrieving chat participants."""

    def test_get_individual_chat_participants(self, extractor):
        """Test getting participants for individual chat."""
        participants = extractor.get_chat_participants(1)

        assert len(participants) == 1
        assert "+15551234567" in participants

    def test_get_group_chat_participants(self, extractor):
        """Test getting participants for group chat."""
        participants = extractor.get_chat_participants(3)

        assert len(participants) == 3
        assert "+15551234567" in participants
        assert "friend@email.com" in participants
        assert "+15559876543" in participants

    def test_get_nonexistent_chat_participants(self, extractor):
        """Test getting participants for non-existent chat."""
        participants = extractor.get_chat_participants(999)
        assert participants == []


class TestGetConversations:
    """Tests for retrieving conversations."""

    def test_get_all_conversations(self, extractor):
        """Test retrieving all conversations."""
        conversations = extractor.get_conversations()

        assert len(conversations) == 3

    def test_conversation_metadata(self, extractor):
        """Test conversation metadata is correct."""
        conversations = extractor.get_conversations()

        # Find Alice's chat
        alice_chat = next(c for c in conversations if c.display_name == "Alice")
        assert alice_chat.chat_id == 1
        assert alice_chat.is_group_chat is False
        assert "+15551234567" in alice_chat.participants

    def test_group_chat_identification(self, extractor):
        """Test group chats are correctly identified."""
        conversations = extractor.get_conversations()

        group_chat = next(c for c in conversations if c.display_name == "Work Group")
        assert group_chat.is_group_chat is True
        assert len(group_chat.participants) == 3


class TestGetMessages:
    """Tests for retrieving messages."""

    def test_get_all_messages(self, extractor):
        """Test retrieving all messages."""
        messages = extractor.get_messages()

        assert len(messages) == 15  # Total messages in test data

    def test_get_messages_by_chat_id(self, extractor):
        """Test filtering messages by chat ID."""
        messages = extractor.get_messages(chat_id=1)

        assert len(messages) == 8  # Messages in Alice's chat
        assert all(m.chat_id == 1 for m in messages)

    def test_get_messages_with_limit(self, extractor):
        """Test limiting number of messages."""
        messages = extractor.get_messages(limit=5)

        assert len(messages) == 5

    def test_get_messages_since_date(self, extractor):
        """Test filtering messages by date."""
        since = datetime(2024, 1, 15, 20, 0, 0)
        messages = extractor.get_messages(since=since)

        # Should get Bob's messages and group chat messages
        assert all(m.date >= since for m in messages)

    def test_messages_sorted_by_date(self, extractor):
        """Test messages are returned in chronological order."""
        messages = extractor.get_messages()

        for i in range(1, len(messages)):
            assert messages[i].date >= messages[i-1].date

    def test_message_is_from_me_flag(self, extractor):
        """Test is_from_me flag is correctly set."""
        messages = extractor.get_messages(chat_id=1)

        # Based on our test data
        from_me = [m for m in messages if m.is_from_me]
        from_them = [m for m in messages if not m.is_from_me]

        assert len(from_me) > 0
        assert len(from_them) > 0

    def test_message_handle_populated(self, extractor):
        """Test message handles are populated."""
        messages = extractor.get_messages(chat_id=1)

        # Messages from others should have handles
        from_them = [m for m in messages if not m.is_from_me]
        assert all(m.handle is not None for m in from_them)

    def test_message_with_attachment(self, extractor):
        """Test messages with attachments are flagged."""
        messages = extractor.get_messages(chat_id=1)

        attachment_msgs = [m for m in messages if m.has_attachment]
        assert len(attachment_msgs) == 1
        assert attachment_msgs[0].attachment_types == ["image/jpeg"]


class TestGetConversationsWithMessages:
    """Tests for retrieving full conversations with messages."""

    def test_get_conversations_with_messages(self, extractor):
        """Test getting conversations with their messages."""
        conversations = extractor.get_conversations_with_messages()

        assert all(len(c.messages) > 0 for c in conversations)

    def test_exclude_group_chats(self, extractor):
        """Test excluding group chats."""
        conversations = extractor.get_conversations_with_messages(
            exclude_group_chats=True
        )

        assert all(not c.is_group_chat for c in conversations)
        assert len(conversations) == 2  # Only individual chats

    def test_limit_per_conversation(self, extractor):
        """Test limiting messages per conversation."""
        conversations = extractor.get_conversations_with_messages(
            limit_per_conversation=3
        )

        assert all(len(c.messages) <= 3 for c in conversations)

    def test_filter_by_date(self, extractor):
        """Test filtering by date across conversations."""
        since = datetime(2024, 1, 16, 0, 0, 0)
        conversations = extractor.get_conversations_with_messages(since=since)

        for conv in conversations:
            assert all(m.date >= since for m in conv.messages)


class TestExportForTraining:
    """Tests for training data export."""

    def test_export_creates_file(self, extractor, export_dir):
        """Test export creates JSON file."""
        output_path = export_dir / "training.json"

        extractor.export_for_training(output_path)

        assert output_path.exists()

    def test_export_json_structure(self, extractor, export_dir):
        """Test exported JSON has correct structure."""
        output_path = export_dir / "training.json"

        extractor.export_for_training(output_path, min_my_messages=1)

        with open(output_path) as f:
            data = json.load(f)

        assert 'exported_at' in data
        assert 'total_conversations' in data
        assert 'total_training_pairs' in data
        assert 'training_pairs' in data

    def test_export_training_pair_structure(self, extractor, export_dir):
        """Test each training pair has correct structure."""
        output_path = export_dir / "training.json"

        extractor.export_for_training(output_path, min_my_messages=1)

        with open(output_path) as f:
            data = json.load(f)

        if data['training_pairs']:
            pair = data['training_pairs'][0]
            assert 'conversation_id' in pair
            assert 'participant' in pair
            assert 'context' in pair
            assert 'my_response' in pair
            assert 'timestamp' in pair

    def test_export_context_structure(self, extractor, export_dir):
        """Test context in training pairs has correct structure."""
        output_path = export_dir / "training.json"

        extractor.export_for_training(output_path, min_my_messages=1)

        with open(output_path) as f:
            data = json.load(f)

        for pair in data['training_pairs']:
            for ctx in pair['context']:
                assert 'text' in ctx
                assert 'is_from_me' in ctx
                assert 'timestamp' in ctx

    def test_export_excludes_group_chats(self, extractor, export_dir):
        """Test group chats are excluded by default."""
        output_path = export_dir / "training.json"

        result = extractor.export_for_training(output_path, min_my_messages=1)

        with open(output_path) as f:
            data = json.load(f)

        # Our test data has group chat with chat_id=3
        conversation_ids = {p['conversation_id'] for p in data['training_pairs']}
        assert 3 not in conversation_ids

    def test_export_min_messages_filter(self, extractor, export_dir):
        """Test minimum messages filter."""
        output_path = export_dir / "training.json"

        # Set high threshold that excludes some conversations
        result = extractor.export_for_training(output_path, min_my_messages=10)

        with open(output_path) as f:
            data = json.load(f)

        # With high threshold, fewer conversations should be included
        assert data['total_conversations'] < 3

    def test_export_returns_statistics(self, extractor, export_dir):
        """Test export returns summary statistics."""
        output_path = export_dir / "training.json"

        result = extractor.export_for_training(output_path, min_my_messages=1)

        assert 'conversations' in result
        assert 'training_pairs' in result
        assert 'output_file' in result

    def test_export_creates_parent_directories(self, extractor, tmp_path):
        """Test export creates parent directories if needed."""
        output_path = tmp_path / "nested" / "dirs" / "training.json"

        extractor.export_for_training(output_path, min_my_messages=1)

        assert output_path.exists()


class TestGetStatistics:
    """Tests for database statistics."""

    def test_get_statistics(self, extractor):
        """Test getting database statistics."""
        stats = extractor.get_statistics()

        assert 'total_messages' in stats
        assert 'my_messages' in stats
        assert 'received_messages' in stats
        assert 'total_conversations' in stats
        assert 'date_range' in stats

    def test_statistics_counts(self, extractor):
        """Test statistics counts are accurate."""
        stats = extractor.get_statistics()

        assert stats['total_messages'] == 15
        assert stats['total_conversations'] == 3
        assert stats['my_messages'] + stats['received_messages'] == stats['total_messages']

    def test_statistics_date_range(self, extractor):
        """Test date range is included."""
        stats = extractor.get_statistics()

        assert stats['date_range']['earliest'] is not None
        assert stats['date_range']['latest'] is not None

    def test_statistics_empty_db(self, empty_chat_db):
        """Test statistics on empty database."""
        with MessageExtractor(empty_chat_db) as extractor:
            stats = extractor.get_statistics()

            assert stats['total_messages'] == 0
            assert stats['my_messages'] == 0


class TestGetAttachmentTypes:
    """Tests for attachment type extraction."""

    def test_get_attachment_types(self, extractor):
        """Test getting attachment types for a message."""
        # Message 14 has an attachment in our test data
        types = extractor._get_attachment_types(14)

        assert types == ["image/jpeg"]

    def test_get_attachment_types_no_attachments(self, extractor):
        """Test getting attachment types for message without attachments."""
        types = extractor._get_attachment_types(1)

        assert types == []

    def test_get_attachment_types_nonexistent_message(self, extractor):
        """Test getting attachment types for non-existent message."""
        types = extractor._get_attachment_types(999)

        assert types == []


class TestCLI:
    """Tests for CLI entry point."""

    def test_cli_stats(self, populated_chat_db, capsys):
        """Test CLI with --stats flag."""
        with patch('sys.argv', ['chat_db.py', '--db', str(populated_chat_db), '--stats']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert 'total_messages' in captured.out

    def test_cli_list_conversations(self, populated_chat_db, capsys):
        """Test CLI with --list-conversations flag."""
        with patch('sys.argv', ['chat_db.py', '--db', str(populated_chat_db), '--list-conversations']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert 'messages' in captured.out

    def test_cli_export(self, populated_chat_db, tmp_path, capsys):
        """Test CLI with --export flag."""
        export_path = tmp_path / "export.json"

        with patch('sys.argv', ['chat_db.py', '--db', str(populated_chat_db), '--export', str(export_path)]):
            result = main()

        assert result == 0
        assert export_path.exists()
        captured = capsys.readouterr()
        assert 'Exported' in captured.out

    def test_cli_default_shows_stats(self, populated_chat_db, capsys):
        """Test CLI with no flags shows stats."""
        with patch('sys.argv', ['chat_db.py', '--db', str(populated_chat_db)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert 'Total messages' in captured.out

    def test_cli_missing_database(self, tmp_path, capsys):
        """Test CLI with missing database."""
        fake_path = tmp_path / "nonexistent.db"

        with patch('sys.argv', ['chat_db.py', '--db', str(fake_path)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert 'Error' in captured.out

    def test_cli_database_error(self, tmp_path, capsys):
        """Test CLI handles database errors."""
        # Create an invalid database file
        bad_db = tmp_path / "bad.db"
        bad_db.write_text("not a database")

        with patch('sys.argv', ['chat_db.py', '--db', str(bad_db)]):
            result = main()

        assert result == 1


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_message_with_empty_text(self, mock_chat_db):
        """Test handling messages with empty text."""
        conn = sqlite3.connect(mock_chat_db)
        cursor = conn.cursor()

        # Add minimal data
        cursor.execute("INSERT INTO handle VALUES (1, '+1', 'iMessage')")
        cursor.execute("INSERT INTO chat VALUES (1, '+1', 'Test', NULL)")
        cursor.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        cursor.execute(
            "INSERT INTO message VALUES (1, '', 0, 0, 1, 0)"
        )
        cursor.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        conn.commit()
        conn.close()

        with MessageExtractor(mock_chat_db) as extractor:
            messages = extractor.get_messages()
            assert len(messages) == 1
            assert messages[0].text == ''

    def test_message_without_handle(self, mock_chat_db):
        """Test handling messages without handle_id."""
        conn = sqlite3.connect(mock_chat_db)
        cursor = conn.cursor()

        cursor.execute("INSERT INTO chat VALUES (1, 'test', 'Test', NULL)")
        cursor.execute(
            "INSERT INTO message VALUES (1, 'test', 0, 1, NULL, 0)"
        )
        cursor.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        conn.commit()
        conn.close()

        with MessageExtractor(mock_chat_db) as extractor:
            messages = extractor.get_messages()
            assert len(messages) == 1
            assert messages[0].handle is None

    def test_conversation_with_no_display_name(self, mock_chat_db):
        """Test handling conversation without display name."""
        conn = sqlite3.connect(mock_chat_db)
        cursor = conn.cursor()

        cursor.execute("INSERT INTO chat VALUES (1, 'chat_id_123', NULL, NULL)")
        conn.commit()
        conn.close()

        with MessageExtractor(mock_chat_db) as extractor:
            conversations = extractor.get_conversations()
            assert len(conversations) == 1
            # Should fall back to chat_identifier
            assert conversations[0].display_name == 'chat_id_123'

    def test_multiple_attachments(self, mock_chat_db):
        """Test message with multiple attachments."""
        conn = sqlite3.connect(mock_chat_db)
        cursor = conn.cursor()

        cursor.execute("INSERT INTO handle VALUES (1, '+1', 'iMessage')")
        cursor.execute("INSERT INTO chat VALUES (1, '+1', 'Test', NULL)")
        cursor.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        cursor.execute("INSERT INTO message VALUES (1, 'Check these', 0, 0, 1, 1)")
        cursor.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        cursor.execute("INSERT INTO attachment VALUES (1, 'image/jpeg', 'a.jpg')")
        cursor.execute("INSERT INTO attachment VALUES (2, 'image/png', 'b.png')")
        cursor.execute("INSERT INTO message_attachment_join VALUES (1, 1)")
        cursor.execute("INSERT INTO message_attachment_join VALUES (1, 2)")
        conn.commit()
        conn.close()

        with MessageExtractor(mock_chat_db) as extractor:
            messages = extractor.get_messages()
            assert len(messages[0].attachment_types) == 2
            assert 'image/jpeg' in messages[0].attachment_types
            assert 'image/png' in messages[0].attachment_types

    def test_sms_messages_processed(self, mock_chat_db):
        """Test that SMS messages (not iMessage) are processed correctly."""
        conn = sqlite3.connect(mock_chat_db)
        cursor = conn.cursor()

        # Create handles with different services - SMS vs iMessage
        cursor.execute("INSERT INTO handle VALUES (1, '+15551234567', 'SMS')")
        cursor.execute("INSERT INTO handle VALUES (2, '+15559876543', 'iMessage')")

        # Create chats for both
        cursor.execute("INSERT INTO chat VALUES (1, '+15551234567', 'SMS Contact', NULL)")
        cursor.execute("INSERT INTO chat VALUES (2, '+15559876543', 'iMessage Contact', NULL)")

        cursor.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        cursor.execute("INSERT INTO chat_handle_join VALUES (2, 2)")

        # Insert SMS message with proper Apple timestamp
        sms_time = datetime_to_apple_time(datetime(2024, 1, 15, 10, 0, 0))
        cursor.execute(
            "INSERT INTO message VALUES (1, 'This is an SMS', ?, 0, 1, 0)",
            (sms_time,)
        )
        cursor.execute("INSERT INTO chat_message_join VALUES (1, 1)")

        # Insert iMessage with proper Apple timestamp
        imsg_time = datetime_to_apple_time(datetime(2024, 1, 15, 11, 0, 0))
        cursor.execute(
            "INSERT INTO message VALUES (2, 'This is an iMessage', ?, 0, 2, 0)",
            (imsg_time,)
        )
        cursor.execute("INSERT INTO chat_message_join VALUES (2, 2)")

        conn.commit()
        conn.close()

        with MessageExtractor(mock_chat_db) as extractor:
            # Both SMS and iMessage should be extracted
            messages = extractor.get_messages()
            assert len(messages) == 2

            # Verify both message types are present
            texts = [m.text for m in messages]
            assert 'This is an SMS' in texts
            assert 'This is an iMessage' in texts

            # Verify handles are correctly associated
            sms_msg = next(m for m in messages if m.text == 'This is an SMS')
            imsg_msg = next(m for m in messages if m.text == 'This is an iMessage')

            assert sms_msg.handle == '+15551234567'
            assert imsg_msg.handle == '+15559876543'

    def test_mixed_sms_imessage_same_contact(self, mock_chat_db):
        """Test conversation with same contact via both SMS and iMessage.

        In real chat.db, the same phone number with different services gets
        different handle identifiers (e.g., '+1555...' for SMS, 'p:+1555...' for iMessage).
        """
        conn = sqlite3.connect(mock_chat_db)
        cursor = conn.cursor()

        # Same phone but different service identifiers (realistic format)
        cursor.execute("INSERT INTO handle VALUES (1, '+15551234567', 'SMS')")
        cursor.execute("INSERT INTO handle VALUES (2, 'p:+15551234567', 'iMessage')")

        # Single chat can have messages from both services
        cursor.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Mixed Contact', NULL)")
        cursor.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        cursor.execute("INSERT INTO chat_handle_join VALUES (1, 2)")

        # Messages alternating between SMS and iMessage (common when service switches)
        times = [
            datetime_to_apple_time(datetime(2024, 1, 15, 10, 0, 0)),
            datetime_to_apple_time(datetime(2024, 1, 15, 10, 1, 0)),
            datetime_to_apple_time(datetime(2024, 1, 15, 10, 2, 0)),
            datetime_to_apple_time(datetime(2024, 1, 15, 10, 3, 0)),
        ]

        cursor.execute(
            "INSERT INTO message VALUES (1, 'SMS when no data', ?, 0, 1, 0)", (times[0],)
        )
        cursor.execute(
            "INSERT INTO message VALUES (2, 'Reply via SMS', ?, 1, 1, 0)", (times[1],)
        )
        cursor.execute(
            "INSERT INTO message VALUES (3, 'Now on iMessage', ?, 0, 2, 0)", (times[2],)
        )
        cursor.execute(
            "INSERT INTO message VALUES (4, 'iMessage reply', ?, 1, 2, 0)", (times[3],)
        )

        cursor.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        cursor.execute("INSERT INTO chat_message_join VALUES (1, 2)")
        cursor.execute("INSERT INTO chat_message_join VALUES (1, 3)")
        cursor.execute("INSERT INTO chat_message_join VALUES (1, 4)")

        conn.commit()
        conn.close()

        with MessageExtractor(mock_chat_db) as extractor:
            # All messages should be in the same conversation
            conversations = extractor.get_conversations_with_messages()
            assert len(conversations) == 1

            conv = conversations[0]
            assert len(conv.messages) == 4
            assert conv.display_name == 'Mixed Contact'

            # Verify message order is preserved (chronological)
            assert conv.messages[0].text == 'SMS when no data'
            assert conv.messages[3].text == 'iMessage reply'

            # Verify is_from_me is correct
            assert conv.messages[0].is_from_me is False
            assert conv.messages[1].is_from_me is True
            assert conv.messages[2].is_from_me is False
            assert conv.messages[3].is_from_me is True

            # Verify handles show the service transition
            assert conv.messages[0].handle == '+15551234567'  # SMS
            assert conv.messages[2].handle == 'p:+15551234567'  # iMessage
