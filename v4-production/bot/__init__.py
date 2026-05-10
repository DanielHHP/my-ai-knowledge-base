"""Bot package providing knowledge-base interaction capabilities.

Exposes the :class:`KnowledgeBot` main entry point and supporting classes
for intent recognition, search, subscription management, and permission
control.
"""

from bot.knowledge_bot import (
    Intent,
    KnowledgeBot,
    KnowledgeSearchEngine,
    Permission,
    PermissionManager,
    SubscriptionManager,
    recognize_intent,
)

__all__ = [
    "Intent",
    "KnowledgeBot",
    "KnowledgeSearchEngine",
    "Permission",
    "PermissionManager",
    "SubscriptionManager",
    "recognize_intent",
]
