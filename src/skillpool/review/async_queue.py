"""AsyncReviewQueue — in-memory review queue with cooldown tracking."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from skillpool.review.models import ReviewStatus, ReviewTriggerRequest


@dataclass
class _QueueEntry:
    """Internal tracking entry for a submitted review."""
    review_id: str
    request: ReviewTriggerRequest
    status: ReviewStatus = ReviewStatus.QUEUED
    submitted_at: float = field(default_factory=time.time)


class AsyncReviewQueue:
    """In-memory review queue with cooldown enforcement.

    - max_concurrent: maximum number of reviews that can be PROCESSING at once
    - cooldown_seconds: minimum time between reviews for the same skill_id

    Usage:
        queue = AsyncReviewQueue()
        review_id = queue.submit(request)
        status = queue.get_status(review_id)
    """

    def __init__(self, max_concurrent: int = 10, cooldown_seconds: float = 86400.0) -> None:
        self.max_concurrent = max_concurrent
        self.cooldown_seconds = cooldown_seconds
        self._entries: dict[str, _QueueEntry] = {}
        self._skill_last_review: dict[str, float] = {}

    def submit(self, request: ReviewTriggerRequest) -> str:
        """Submit a review request. Returns the review_id.

        Raises ValueError if any affected skill is still in cooldown.
        Raises RuntimeError if max_concurrent reviews are already processing.
        """
        # Check cooldown for all affected skills
        now = time.time()
        for skill_id in request.affected_skills:
            last = self._skill_last_review.get(skill_id, 0.0)
            if now - last < self.cooldown_seconds:
                remaining = round(self.cooldown_seconds - (now - last), 1)
                raise ValueError(
                    f"Skill '{skill_id}' is in cooldown ({remaining}s remaining)"
                )

        # Check max concurrent
        processing_count = sum(
            1 for e in self._entries.values()
            if e.status == ReviewStatus.PROCESSING
        )
        if processing_count >= self.max_concurrent:
            raise RuntimeError(
                f"Max concurrent reviews ({self.max_concurrent}) reached"
            )

        review_id = uuid.uuid4().hex[:16]
        entry = _QueueEntry(
            review_id=review_id,
            request=request,
            status=ReviewStatus.QUEUED,
            submitted_at=now,
        )
        self._entries[review_id] = entry

        # Mark skill cooldown timestamps
        for skill_id in request.affected_skills:
            self._skill_last_review[skill_id] = now

        return review_id

    def get_status(self, review_id: str) -> ReviewStatus:
        """Get the current status of a review."""
        entry = self._entries.get(review_id)
        if entry is None:
            raise KeyError(f"Review '{review_id}' not found")
        return entry.status

    def set_status(self, review_id: str, status: ReviewStatus) -> None:
        """Update the status of a review entry."""
        entry = self._entries.get(review_id)
        if entry is None:
            raise KeyError(f"Review '{review_id}' not found")
        entry.status = status

    def is_in_cooldown(self, skill_id: str) -> bool:
        """Check whether a skill is currently in cooldown."""
        last = self._skill_last_review.get(skill_id, 0.0)
        return (time.time() - last) < self.cooldown_seconds

    def clear(self) -> None:
        """Clear all entries and cooldown tracking (for testing)."""
        self._entries.clear()
        self._skill_last_review.clear()
