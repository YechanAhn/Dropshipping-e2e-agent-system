"""
Feedback loop package for DropAgent.

Provides modules for tracking product performance, running A/B tests on
listing variations, and retraining scoring models based on real-world
outcomes.

Modules:
    - performance_tracker: Per-product KPI tracking and scoring-weight feedback.
    - ab_tester: A/B testing for product listing variations.
    - model_retrainer: Automated retraining of scoring models.
"""

from dropagent.feedback.performance_tracker import PerformanceTracker

__all__ = [
    "PerformanceTracker",
]
