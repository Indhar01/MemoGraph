"""
Claude (Anthropic) conversation importer.

Supports importing Claude conversation exports (JSON format).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .chat_models import Conversation, Message, MessageRole, ImportStats


class ClaudeImporter:
    """
    Importer for Claude conversation exports.
    
    Claude exports conversations as JSON files with a simpler structure than ChatGPT.
    """
    
    def __init__(self):
        self.platform = "claude"
    
    def import_file(self, file_path: str | Path) -> list[Conversation]:
        """
        Import conversations from a Claude export file.
        
        Args:
            file_path: Path to the JSON export file
            
        Returns:
            List of Conversation objects
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Export file not found: {file_path}")
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        conversations = []
        
        # Claude exports can be a single conversation or array
        if isinstance(data, list):
            for conv_data in data:
                conv = self._parse_conversation(conv_data)
                if conv:
                    conversations.append(conv)
        else:
            conv = self._parse_conversation(data)
            if conv:
                conversations.append(conv)
        
        return conversations
    
    def _parse_conversation(self, data: dict[str, Any]) -> Conversation | None:
        """Parse a single conversation from Claude export data."""
        try:
            # Extract basic info
            conv_id = data.get("uuid", data.get("id", "unknown"))
            name = data.get("name", "Untitled Conversation")
            
            # Parse timestamps
            created_at_str = data.get("created_at", data.get("createdAt"))
            updated_at_str = data.get("updated_at", data.get("updatedAt"))
            
            created_at = self._parse_timestamp(created_at_str) if created_at_str else datetime.now()
            updated_at = self._parse_timestamp(updated_at_str) if updated_at_str else None
            
            # Parse messages
            chat_messages = data.get("chat_messages", [])
            messages = self._parse_messages(chat_messages)
            
            if not messages:
                return None
            
            # Create conversation
            conversation = Conversation(
                id=conv_id,
                title=name,
                messages=messages,
                created_at=created_at,
                updated_at=updated_at,
                platform=self.platform,
                metadata={
                    "model": data.get("model", "unknown"),
                    "raw_data": data,
                }
            )
            
            return conversation
            
        except Exception as e:
            print(f"Error parsing Claude conversation: {e}")
            return None
    
    def _parse_messages(self, messages_: list[dict]) -> list[Message]:
        """Parse messages from Claude's message list."""
        messages = []
        
        for msg_data in messages_:
            msg = self._parse_message(msg_data)
            if msg:
                messages.append(msg)
        
        return messages
    
    def _parse_message(self, message_data: dict[str, Any]) -> Message | None:
        """Parse a single message."""
        try:
            # Get role
            sender = message_data.get("sender", "user")
            
            # Map Claude roles to our MessageRole enum
            role_mapping = {
                "human": MessageRole.USER,
                "user": MessageRole.USER,
                "assistant": MessageRole.ASSISTANT,
                "system": MessageRole.SYSTEM,
            }
            role = role_mapping.get(sender.lower(), MessageRole.USER)
            
            # Get content
            content = message_data.get("text", "")
            if not content or content.strip() == "":
                return None
            
            # Get timestamp
            created_at_str = message_data.get("created_at", message_data.get("createdAt"))
            timestamp = self._parse_timestamp(created_at_str) if created_at_str else None
            
            # Get metadata
            metadata = {
                "message_id": message_data.get("uuid", message_data.get("id")),
                "sender": sender,
            }
            
            # Get model if available
            model = message_data.get("model")
            
            message = Message(
                role=role,
                content=content,
                timestamp=timestamp,
                metadata=metadata,
                model=model,
            )
            
            return message
            
        except Exception as e:
            print(f"Error parsing Claude message: {e}")
            return None
    
    def _parse_timestamp(self, timestamp_str: str) -> datetime | None:
        """Parse various timestamp formats."""
        if not timestamp_str:
            return None
        
        try:
            # Try ISO format
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            try:
                # Try Unix timestamp
                return datetime.fromtimestamp(float(timestamp_str))
            except (ValueError, TypeError):
                return None
    
    def get_import_stats(self, conversations: list[Conversation]) -> ImportStats:
        """Generate statistics for imported conversations."""
        stats = ImportStats(platform=self.platform)
        
        stats.total_conversations = len(conversations)
        stats.total_messages = sum(conv.message_count() for conv in conversations)
        
        # Get date range
        if conversations:
            dates = [conv.created_at for conv in conversations if conv.created_at]
            if dates:
                stats.date_range = (min(dates), max(dates))
        
        return stats