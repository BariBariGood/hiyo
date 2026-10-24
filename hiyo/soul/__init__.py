"""Soul — Hiyo coaching behavior and consent-aware care proposals.

Adapted from a teammate's "Soul" starter (see docs/PRODUCT_SOUL_SPEC.md).
Soul logic shapes what triggers are considered and what the call says;
hiyo/policy.py remains the sole authority on whether a call happens.
"""

from .engine import SoulEngine
from .models import CoachProfile, CoachingContext, Feedback, Observation, SoulPolicy
from .store import SoulStore

__all__ = ["SoulEngine", "SoulStore", "CoachProfile", "CoachingContext", "Feedback", "Observation", "SoulPolicy"]
