"""
Data models for chat conversations.

These models represent the structure of conversations imported from various
AI chat platforms.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessageRole(Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationType(Enum):
    """Type of conversation based on content."""
    CODING = "coding"
    LEARNING = "learning"
    BRAINSTORMING = "brainstorming"
    PROBLEM_SOLVING = "problem_solving"
    CREATIVE_WRITING = "creative_writing"
    RESEARCH = "research"
    GENERAL = "general"
    TASK_COMPLETION = "task_completion"


@dataclass
class Message:
    """Represents a single message in a conversation."""
    role: MessageRole
    content: str
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Optional fields for additional context
    model: str | None = None  # AI model used (e.g., "gpt-4", "claude-3-sonnet")
    tokens: int | None = None  # Token count if available
    
    def is_user_message(self) -> bool:
        """Check if this is a user message."""
        return self.role == MessageRole.USER
    
    def is_assistant_message(self) -> bool:
        """Check if this is an assistant message."""
        return self.role == MessageRole.ASSISTANT
    
    def contains_code(self) -> bool:
        """Check if message contains code blocks."""
        return "```" in self.content or self.content.count("`") >= 2
    
    def word_count(self) -> int:
        """Get approximate word count."""
        return len(self.content.split())


@dataclass
class Conversation:
    """Represents a complete conversation thread."""
    id: str
    title: str
    messages: list[Message]
    created_at: datetime
    updated_at: datetime | None = None
    platform: str = "unknown"  # chatgpt, claude, gemini
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Derived fields (populated by analysis)
    conversation_type: ConversationType | None = None
    topics: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
    
    def message_count(self) -> int:
        """Get total number of messages."""
        return len(self.messages)
    
    def user_message_count(self) -> int:
        """Get number of user messages."""
        return sum(1 for msg in self.messages if msg.is_user_message())
    
    def assistant_message_count(self) -> int:
        """Get number of assistant messages."""
        return sum(1 for msg in self.messages if msg.is_assistant_message())
    
    def total_word_count(self) -> int:
        """Get total word count across all messages."""
        return sum(msg.word_count() for msg in self.messages)
    
    def contains_code(self) -> bool:
        """Check if conversation contains any code."""
        return any(msg.contains_code() for msg in self.messages)
    
    def get_first_user_message(self) -> Message | None:
        """Get the first user message (often the prompt)."""
        for msg in self.messages:
            if msg.is_user_message():
                return msg
        return None
    
    def get_conversation_text(self, include_roles: bool = True) -> str:
        """Get full conversation as text."""
        lines = []
        for msg in self.messages:
            if include_roles:
                role_label = msg.role.value.title()
                lines.append(f"**{role_label}:** {msg.content}")
            else:
                lines.append(msg.content)
            lines.append("")  # Empty line between messages
        return "\n".join(lines)
    
    def duration(self) -> float | None:
        """Get conversation duration in hours."""
        if not self.updated_at:
            return None
        delta = self.updated_at - self.created_at
        return delta.total_seconds() / 3600


@dataclass
class ConversationThread:
    """
    Represents a logical thread of related conversations.
    
    Used to group multiple conversations that are part of the same
    topic or project across different chat sessions.
    """
    id: str
    name: str
    conversations: list[Conversation]
    start_date: datetime
    end_date: datetime | None = None
    recurring_topics: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    
    def conversation_count(self) -> int:
        """Get number of conversations in this thread."""
        return len(self.conversations)
    
    def total_messages(self) -> int:
        """Get total messages across all conversations."""
        return sum(conv.message_count() for conv in self.conversations)
    
    def span_days(self) -> int | None:
        """Get number of days spanned by this thread."""
        if not self.end_date:
            return None
        delta = self.end_date - self.start_date
        return delta.days


@dataclass
class KnowledgeGem:
    """
    Represents a valuable piece of knowledge extracted from conversations.
    
    These are facts, insights, code snippets, or decisions that should be
    remembered and easily retrievable.
    """
    gem_type: str  # fact, decision, code_snippet, insight, technique, resource
    content: str
    source_conversation_id: str
    source_message_index: int | None = None
    context: str | None = None  # Surrounding context
    importance: float = 1.0  # 0.0-1.0
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now())
    
    # Categorization
    category: str | None = None  # programming, design, learning, etc.
    language: str | None = None  # For code snippets
    
    @classmethod
    def create_fact(cls, content: str, source_id: str, **kwargs) -> "KnowledgeGem":
        """Create a fact gem."""
        return cls(gem_type="fact", content=content, source_conversation_id=source_id, **kwargs)
    
    @classmethod
    def create_decision(cls, content: str, source_id: str, **kwargs) -> "KnowledgeGem":
        """Create a decision gem."""
        return cls(gem_type="decision", content=content, source_conversation_id=source_id, **kwargs)
    
    @classmethod
    def create_code(cls, content: str, source_id: str, language: str | None = None, **kwargs) -> "KnowledgeGem":
        """Create a code snippet gem."""
        return cls(gem_type="code_snippet", content=content, source_conversation_id=source_id, language=language, **kwargs)
    
    @classmethod
    def create_insight(cls, content: str, source_id: str, **kwargs) -> "KnowledgeGem":
        """Create an insight gem."""
        return cls(gem_type="insight", content=content, source_conversation_id=source_id, **kwargs)


@dataclass
class PromptPattern:
    """
    Represents a recurring prompt pattern used by the user.
    
    Used to identify common ways the user interacts with AI and suggest
    templates for future use.
    """
    pattern: str
    frequency: int
    examples: list[str] = field(default_factory=list)
    category: str | None = None
    suggested_template: str | None = None
    tags: list[str] = field(default_factory=list)
    
    def add_example(self, example: str):
        """Add an example of this pattern."""
        if len(self.examples) < 10:  # Keep top 10 examples
            self.examples.append(example)


@dataclass
class ImportStats:
    """Statistics from an import operation."""
    total_conversations: int = 0
    total_messages: int = 0
    total_gems_extracted: int = 0
    conversations_by_type: dict[str, int] = field(default_factory=dict)
    gems_by_type: dict[str, int] = field(default_factory=dict)
    date_range: tuple[datetime, datetime] | None = None
    platform: str = "unknown"
    
    def summary(self) -> str:
        """Get a summary of import stats."""
        lines = [
            f"Import Summary ({self.platform})",
            f"=" * 50,
            f"Total Conversations: {self.total_conversations}",
            f"Total Messages: {self.total_messages}",
            f"Knowledge Gems Extracted: {self.total_gems_extracted}",
        ]
        
        if self.date_range:
            start, end = self.date_range
            lines.append(f"Date Range: {start.date()} to {end.date()}")
        
        if self.conversations_by_type:
            lines.append("\nConversations by Type:")
            for ctype, count in sorted(self.conversations_by_type.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  - {ctype}: {count}")
        
        if self.gems_by_type:
            lines.append("\nGems by Type:")
            for gtype, count in sorted(self.gems_by_type.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  - {gtype}: {count}")
        
        return "\n".join(lines)