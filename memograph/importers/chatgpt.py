"""
ChatGPT (OpenAI) conversation importer.

Supports importing ChatGPT export files (JSON format).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .chat_models import Conversation, Message, MessageRole, ImportStats


class ChatGPTImporter:
    """
    Importer for ChatGPT conversation exports.
    
    ChatGPT exports conversations as JSON files with the following structure:
    - Each conversation has a title, create_time, update_time
    - Messages are in a mapping structure with parent/child relationships
    - Each message has content, role, author, and create_time
    """
    
    def __init__(self):
        self.platform = "chatgpt"
    
    def import_file(self, file_path: str | Path) -> list[Conversation]:
        """
        Import conversations from a ChatGPT export file.
        
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
        
        # ChatGPT exports can be a single conversation or array of conversations
        if isinstance(data, list):
            for conv_data in 
                conv = self._parse_conversation(conv_data)
                if conv:
                    conversations.append(conv)
        else:
            conv = self._parse_conversation(data)
            if conv:
                conversations.append(conv)
        
        return conversations
    
    def _parse_conversation(self, data: dict[str, Any]) -> Conversation | None:
        """Parse a single conversation from ChatGPT export data."""
        try:
            # Extract basic info
            conv_id = data.get("id", data.get("conversation_id", "unknown"))
            title = data.get("title", "Untitled Conversation")
            
            # Parse timestamps
            create_time = data.get("create_time", data.get("created_at"))
            update_time = data.get("update_time", data.get("updated_at"))
            
            created_at = datetime.fromtimestamp(create_time) if create_time else datetime.now()
            updated_at = datetime.fromtimestamp(update_time) if update_time else None
            
            # Parse messages
            messages = self._parse_messages(data.get("mapping", {}))
            
            if not messages:
                return None
            
            # Create conversation
            conversation = Conversation(
                id=conv_id,
                title=title,
                messages=messages,
                created_at=created_at,
                updated_at=updated_at,
                platform=self.platform,
                metadata={
                    "model": data.get("model", "unknown"),
                    "raw_data": data,  # Store for debugging
                }
            )
            
            return conversation
            
        except Exception as e:
            print(f"Error parsing conversation: {e}")
            return None
    
    def _parse_messages(self, mapping: dict[str, Any]) -> list[Message]:
        """
        Parse messages from ChatGPT's mapping structure.
        
        ChatGPT uses a tree structure with parent-child relationships.
        We need to traverse this tree to reconstruct the conversation.
        """
        if not mapping:
            return []
        
        # Find the root message (no parent)
        root_id = None
        for msg_id, msg_data in mapping.items():
            if msg_data.get("parent") is None or msg_data.get("parent") == "":
                root_id = msg_id
                break
        
        if not root_id:
            # Fallback: use first message
            root_id = next(iter(mapping.keys()))
        
        # Traverse tree to build message list
        messages = []
        self._traverse_messages(mapping, root_id, messages)
        
        return messages
    
    def _traverse_messages(self, mapping: dict, node_id: str, messages: list[Message]):
        """Recursively traverse message tree."""
        if node_id not in mapping:
            return
        
        node = mapping[node_id]
        message_data = node.get("message")
        
        if message_data:
            # Parse message
            msg = self._parse_message(message_data)
            if msg:
                messages.append(msg)
        
        # Process children
        children = node.get("children", [])
        for child_id in children:
            self._traverse_messages(mapping, child_id, messages)
    
    def _parse_message(self, message_ dict[str, Any]) -> Message | None:
        """Parse a single message."""
        try:
            # Get role
            author = message_data.get("author", {})
            role_str = author.get("role", "user")
            
            # Map ChatGPT roles to our MessageRole enum
            role_mapping = {
                "user": MessageRole.USER,
                "assistant": MessageRole.ASSISTANT,
                "system": MessageRole.SYSTEM,
                "tool": MessageRole.ASSISTANT,  # Tool outputs are assistant messages
            }
            role = role_mapping.get(role_str, MessageRole.USER)
            
            # Get content
            content_data = message_data.get("content", {})
            if isinstance(content_data, dict):
                parts = content_data.get("parts", [])
                content = "\n".join(str(part) for part in parts if part)
            else:
                content = str(content_data)
            
            if not content or content.strip() == "":
                return None
            
            # Get timestamp
            create_time = message_data.get("create_time")
            timestamp = datetime.fromtimestamp(create_time) if create_time else None
            
            # Get metadata
            metadata = {
                "author_name": author.get("name"),
                "message_id": message_data.get("id"),
            }
            
            # Get model if available
            model = None
            if "model_slug" in message_data:
                model = message_data["model_slug"]
            
            message = Message(
                role=role,
                content=content,
                timestamp=timestamp,
                metadata=metadata,
                model=model,
            )
            
            return message
            
        except Exception as e:
            print(f"Error parsing message: {e}")
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