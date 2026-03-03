"""Centurion — AI Agent Orchestration Engine.

Spawn and command an army of AI agents with Roman military precision.
"""

from centurion.config import CenturionConfig, ResourceRequirements, ResourceSpec
from centurion.core.century import Century, CenturyConfig
from centurion.core.engine import Centurion
from centurion.core.events import CenturionEvent, EventBus
from centurion.core.legion import Legion, LegionQuota
from centurion.core.legionary import Legionary, LegionaryStatus
from centurion.core.scheduler import CenturionScheduler

__all__ = [
    "Century",
    "CenturyConfig",
    "Centurion",
    "CenturionConfig",
    "CenturionEvent",
    "CenturionScheduler",
    "EventBus",
    "Legion",
    "LegionQuota",
    "Legionary",
    "LegionaryStatus",
    "ResourceRequirements",
    "ResourceSpec",
]

__version__ = "0.1.0"
