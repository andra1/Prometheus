"""
iMessage database extractor for macOS.

Reads the chat.db SQLite database and extracts message history
for training the personalized response model.
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
import json


# iMessage stores dates as nanoseconds since 2001-01-01
APPLE_EPOCH = datetime(2001, 1, 1)
NANOSECONDS_PER_SECOND = 1_000_000_000


@dataclass
class Message:
    """Represents a single iMessage."""
    id: int
    text: Optional[str]
    date: datetime
    is_from_me: bool
    handle: Optional[str]  # Phone number or email of other party
    chat_id: int
    is_group_chat: bool
    has_attachment: bool
    attachment_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        d = asdict(self)
        d['date'] = self.date.isoformat()
        return d


@dataclass
class Conversation:
    """Represents a conversation thread."""
    chat_id: int
    display_name: Optional[str]
    participants: list[str]
    is_group_chat: bool
    messages: list[Message] = field(default_factory=list)

    @property
    def my_messages(self) -> list[Message]:
        """Get only messages sent by the user."""
        return [m for m in self.messages if m.is_from_me]

    @property
    def their_messages(self) -> list[Message]:
        """Get only messages received from others."""
        return [m for m in self.messages if not m.is_from_me]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            'chat_id': self.chat_id,
            'display_name': self.display_name,
            'participants': self.participants,
            'is_group_chat': self.is_group_chat,
            'message_count': len(self.messages),
            'my_message_count': len(self.my_messages),
            'messages': [m.to_dict() for m in self.messages]
        }


class MessageExtractor:
    """Extracts message history from the macOS iMessage database."""

    DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the extractor.

        Args:
            db_path: Path to chat.db. Defaults to ~/Library/Messages/chat.db
        """
        self.db_path = db_path or self.DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Connect to the iMessage database."""
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"iMessage database not found at {self.db_path}. "
                "Make sure you're running on macOS with iMessage configured."
            )

        # Connect in read-only mode to avoid any modifications
        uri = f"file:{self.db_path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _apple_time_to_datetime(self, apple_time: int) -> datetime:
        """Convert Apple's timestamp format to Python datetime."""
        if apple_time is None:
            return datetime.min

        # Handle both old (seconds) and new (nanoseconds) formats
        if apple_time > 1_000_000_000_000:
            seconds = apple_time / NANOSECONDS_PER_SECOND
        else:
            seconds = apple_time

        return datetime.fromtimestamp(APPLE_EPOCH.timestamp() + seconds)

    def get_all_handles(self) -> dict[int, str]:
        """Get mapping of handle IDs to contact identifiers."""
        cursor = self._conn.execute("""
            SELECT ROWID, id
            FROM handle
        """)
        return {row['ROWID']: row['id'] for row in cursor.fetchall()}

    def get_chat_participants(self, chat_id: int) -> list[str]:
        """Get list of participant handles for a chat."""
        cursor = self._conn.execute("""
            SELECT h.id
            FROM handle h
            JOIN chat_handle_join chj ON h.ROWID = chj.handle_id
            WHERE chj.chat_id = ?
        """, (chat_id,))
        return [row['id'] for row in cursor.fetchall()]

    def get_conversations(self) -> list[Conversation]:
        """Get all conversations with metadata."""
        cursor = self._conn.execute("""
            SELECT
                ROWID as chat_id,
                display_name,
                chat_identifier,
                group_id
            FROM chat
        """)

        conversations = []
        for row in cursor.fetchall():
            chat_id = row['chat_id']
            participants = self.get_chat_participants(chat_id)
            is_group = row['group_id'] is not None or len(participants) > 1

            conv = Conversation(
                chat_id=chat_id,
                display_name=row['display_name'] or row['chat_identifier'],
                participants=participants,
                is_group_chat=is_group
            )
            conversations.append(conv)

        return conversations

    def get_messages(
        self,
        chat_id: Optional[int] = None,
        limit: Optional[int] = None,
        since: Optional[datetime] = None
    ) -> list[Message]:
        """
        Extract messages from the database.

        Args:
            chat_id: Filter to specific conversation. None for all.
            limit: Maximum number of messages to return.
            since: Only get messages after this date.

        Returns:
            List of Message objects sorted by date.
        """
        handles = self.get_all_handles()

        query = """
            SELECT
                m.ROWID as id,
                m.text,
                m.date,
                m.is_from_me,
                m.handle_id,
                m.cache_has_attachments,
                cmj.chat_id,
                c.group_id
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat c ON cmj.chat_id = c.ROWID
            WHERE 1=1
        """
        params = []

        if chat_id is not None:
            query += " AND cmj.chat_id = ?"
            params.append(chat_id)

        if since is not None:
            # Convert datetime to Apple timestamp
            apple_time = int((since.timestamp() - APPLE_EPOCH.timestamp()) * NANOSECONDS_PER_SECOND)
            query += " AND m.date > ?"
            params.append(apple_time)

        query += " ORDER BY m.date ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self._conn.execute(query, params)

        messages = []
        for row in cursor.fetchall():
            handle_id = row['handle_id']
            handle = handles.get(handle_id) if handle_id else None

            # Get attachment types if present
            attachment_types = []
            if row['cache_has_attachments']:
                attachment_types = self._get_attachment_types(row['id'])

            msg = Message(
                id=row['id'],
                text=row['text'],
                date=self._apple_time_to_datetime(row['date']),
                is_from_me=bool(row['is_from_me']),
                handle=handle,
                chat_id=row['chat_id'],
                is_group_chat=row['group_id'] is not None,
                has_attachment=bool(row['cache_has_attachments']),
                attachment_types=attachment_types
            )
            messages.append(msg)

        return messages

    def _get_attachment_types(self, message_id: int) -> list[str]:
        """Get MIME types of attachments for a message."""
        cursor = self._conn.execute("""
            SELECT a.mime_type
            FROM attachment a
            JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
            WHERE maj.message_id = ?
        """, (message_id,))
        return [row['mime_type'] for row in cursor.fetchall() if row['mime_type']]

    def get_conversations_with_messages(
        self,
        limit_per_conversation: Optional[int] = None,
        since: Optional[datetime] = None,
        exclude_group_chats: bool = False
    ) -> list[Conversation]:
        """
        Get all conversations with their messages populated.

        Args:
            limit_per_conversation: Max messages per conversation.
            since: Only get messages after this date.
            exclude_group_chats: Skip group conversations.

        Returns:
            List of Conversation objects with messages.
        """
        conversations = self.get_conversations()

        for conv in conversations:
            if exclude_group_chats and conv.is_group_chat:
                continue

            conv.messages = self.get_messages(
                chat_id=conv.chat_id,
                limit=limit_per_conversation,
                since=since
            )

        # Filter out empty conversations and optionally group chats
        conversations = [
            c for c in conversations
            if c.messages and (not exclude_group_chats or not c.is_group_chat)
        ]

        return conversations

    def export_for_training(
        self,
        output_path: Path,
        exclude_group_chats: bool = True,
        min_my_messages: int = 5
    ) -> dict:
        """
        Export messages in a format suitable for training.

        Creates a JSON file with conversation pairs showing:
        - What message was received
        - How you responded

        Args:
            output_path: Where to save the JSON file.
            exclude_group_chats: Skip group chats (recommended for cleaner training data).
            min_my_messages: Only include conversations where you've sent at least this many messages.

        Returns:
            Summary statistics of the export.
        """
        conversations = self.get_conversations_with_messages(
            exclude_group_chats=exclude_group_chats
        )

        # Filter conversations with enough of your messages
        conversations = [
            c for c in conversations
            if len(c.my_messages) >= min_my_messages
        ]

        # Build training pairs: (received_message, your_response)
        training_pairs = []

        for conv in conversations:
            messages = sorted(conv.messages, key=lambda m: m.date)

            for i, msg in enumerate(messages):
                if msg.is_from_me and msg.text:
                    # Find the message(s) I was responding to
                    context = []
                    for j in range(max(0, i - 5), i):
                        prev_msg = messages[j]
                        if prev_msg.text:
                            context.append({
                                'text': prev_msg.text,
                                'is_from_me': prev_msg.is_from_me,
                                'timestamp': prev_msg.date.isoformat()
                            })

                    if context:  # Only include if there's context to respond to
                        training_pairs.append({
                            'conversation_id': conv.chat_id,
                            'participant': conv.display_name,
                            'context': context,
                            'my_response': msg.text,
                            'timestamp': msg.date.isoformat()
                        })

        # Export to JSON
        output_data = {
            'exported_at': datetime.now().isoformat(),
            'total_conversations': len(conversations),
            'total_training_pairs': len(training_pairs),
            'training_pairs': training_pairs
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)

        return {
            'conversations': len(conversations),
            'training_pairs': len(training_pairs),
            'output_file': str(output_path)
        }

    def get_statistics(self) -> dict:
        """Get statistics about the message database."""
        total_messages = self._conn.execute(
            "SELECT COUNT(*) FROM message"
        ).fetchone()[0]

        my_messages = self._conn.execute(
            "SELECT COUNT(*) FROM message WHERE is_from_me = 1"
        ).fetchone()[0]

        total_chats = self._conn.execute(
            "SELECT COUNT(*) FROM chat"
        ).fetchone()[0]

        date_range = self._conn.execute("""
            SELECT MIN(date), MAX(date) FROM message WHERE date > 0
        """).fetchone()

        return {
            'total_messages': total_messages,
            'my_messages': my_messages,
            'received_messages': total_messages - my_messages,
            'total_conversations': total_chats,
            'date_range': {
                'earliest': self._apple_time_to_datetime(date_range[0]).isoformat() if date_range[0] else None,
                'latest': self._apple_time_to_datetime(date_range[1]).isoformat() if date_range[1] else None
            }
        }


def main():
    """CLI entry point for testing the extractor."""
    import argparse

    parser = argparse.ArgumentParser(description='Extract iMessage history')
    parser.add_argument('--db', type=Path, help='Path to chat.db')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--export', type=Path, help='Export training data to JSON file')
    parser.add_argument('--list-conversations', action='store_true', help='List all conversations')

    args = parser.parse_args()

    try:
        with MessageExtractor(args.db) as extractor:
            if args.stats:
                stats = extractor.get_statistics()
                print(json.dumps(stats, indent=2))

            elif args.list_conversations:
                convs = extractor.get_conversations_with_messages()
                for conv in sorted(convs, key=lambda c: len(c.messages), reverse=True)[:20]:
                    print(f"{conv.display_name}: {len(conv.messages)} messages ({len(conv.my_messages)} from me)")

            elif args.export:
                result = extractor.export_for_training(args.export)
                print(f"Exported {result['training_pairs']} training pairs to {result['output_file']}")

            else:
                # Default: show stats
                stats = extractor.get_statistics()
                print("iMessage Database Statistics:")
                print(f"  Total messages: {stats['total_messages']:,}")
                print(f"  Your messages: {stats['my_messages']:,}")
                print(f"  Received: {stats['received_messages']:,}")
                print(f"  Conversations: {stats['total_conversations']}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except sqlite3.OperationalError as e:
        print(f"Database error: {e}")
        print("You may need to grant Full Disk Access to your terminal app in System Preferences.")
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
