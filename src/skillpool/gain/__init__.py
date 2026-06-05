"""GainTracker — Four-dimension scoring and gain quantification for skill combinations.

Tracks skill execution outcomes across four dimensions:
  1. Effectiveness — Task goal achievement degree
  2. Efficiency   — Resource consumption reasonableness
  3. Quality      — Output sustainability
  4. Gain         — Combination marginal contribution (A alone vs A+B)

Supports both implicit tracking (auto-collected from execution) and
explicit scoring (agent-provided ratings). Zero-burden by default.

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import json
import logging

from pathlib import Path

from pydantic import BaseModel, Field

from skillpool.config import get_data_dir
from skillpool.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


class GainScores(BaseModel):
    """Four-dimension gain scores for a skill execution."""

    effectiveness: float = Field(default=0.0, ge=0.0, le=10.0, description="Task goal achievement (0-10)")
    efficiency: float = Field(default=0.0, ge=0.0, le=10.0, description="Resource consumption (0-10)")
    quality: float = Field(default=0.0, ge=0.0, le=10.0, description="Output sustainability (0-10)")
    gain: float = Field(default=0.0, ge=-10.0, le=10.0, description="Combination marginal contribution (-10 to +10)")


class SkillExecution(BaseModel):
    """Record of a single skill execution with outcome data."""

    execution_id: str = Field(default="", description="Unique execution ID")
    skill_ids: list[str] = Field(description="Skill(s) used in this execution")
    timestamp: str = Field(default="", description="ISO 8601 timestamp")
    intent: str = Field(default="", description="Original agent intent")
    scores: GainScores = Field(default_factory=GainScores)
    duration_ms: int = Field(default=0, description="Execution duration in ms")
    token_count: int = Field(default=0, description="Token consumption")
    success: bool = Field(default=True, description="Whether execution succeeded")
    source: str = Field(default="implicit", description="implicit or explicit scoring")


class GainReport(BaseModel):
    """Aggregated gain report for a skill or combination."""

    skill_id: str
    execution_count: int = 0
    avg_effectiveness: float = 0.0
    avg_efficiency: float = 0.0
    avg_quality: float = 0.0
    avg_gain: float = 0.0
    combined_score: float = 0.0


class GainTracker:
    """Tracks and quantifies skill combination gains.

    Usage:
        tracker = GainTracker(data_dir=Path("~/.skillpool/gain"))
        tracker.record(SkillExecution(
            skill_ids=["multi-dim-review", "karpathy-guidelines"],
            intent="code review",
            scores=GainScores(effectiveness=8.5, efficiency=7.0, quality=9.0, gain=1.5),
            source="explicit",
        ))
        report = tracker.report("multi-dim-review")
    """

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or get_data_dir() / "gain"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._executions: list[SkillExecution] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Lazy-load execution history from disk."""
        if self._loaded:
            return
        log_file = self.data_dir / "executions.jsonl"
        if log_file.exists():
            for line in log_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._executions.append(SkillExecution(**json.loads(line)))
                except Exception as e:
                    logger.warning("Failed to parse execution record: %s", e)
                    continue
        self._loaded = True

    def record(self, execution: SkillExecution) -> None:
        """Record a skill execution outcome.

        Writes immediately to disk for persistence.
        """
        self._ensure_loaded()
        if not execution.timestamp:
            execution.timestamp = utc_now().isoformat()
        if not execution.execution_id:
            execution.execution_id = f"exec-{len(self._executions) + 1:06d}"

        self._executions.append(execution)

        # Append to log file
        log_file = self.data_dir / "executions.jsonl"
        with open(log_file, "a") as f:
            f.write(execution.model_dump_json() + "\n")

    def record_implicit(
        self,
        skill_ids: list[str],
        intent: str = "",
        duration_ms: int = 0,
        token_count: int = 0,
        success: bool = True,
    ) -> None:
        """Record an implicit (auto-collected) execution.

        Derives basic scores from available metrics:
        - effectiveness: 7.0 if success, 3.0 if failure
        - efficiency: based on duration (lower = better)
        - quality: neutral 5.0 (no data to assess)
        - gain: 0.0 (unknown for single execution)
        """
        eff_score = 7.0 if success else 3.0
        # Efficiency: 10 for <30s, 8 for <2min, 5 for <5min, 3 for longer
        if duration_ms < 30_000:
            eff_score_eff = 10.0
        elif duration_ms < 120_000:
            eff_score_eff = 8.0
        elif duration_ms < 300_000:
            eff_score_eff = 5.0
        else:
            eff_score_eff = 3.0

        scores = GainScores(
            effectiveness=eff_score,
            efficiency=eff_score_eff,
            quality=5.0,  # No data to assess
            gain=0.0,  # Unknown for single execution
        )

        self.record(
            SkillExecution(
                skill_ids=skill_ids,
                intent=intent,
                scores=scores,
                duration_ms=duration_ms,
                token_count=token_count,
                success=success,
                source="implicit",
            )
        )

    def report(self, skill_id: str, last_n: int = 50) -> GainReport:
        """Generate aggregated gain report for a skill.

        Args:
            skill_id: Skill ID to report on
            last_n: Consider only the last N executions

        Returns:
            GainReport with aggregated scores
        """
        self._ensure_loaded()

        # Find executions involving this skill
        relevant = [e for e in self._executions if skill_id in e.skill_ids]
        relevant = relevant[-last_n:]  # Last N only

        if not relevant:
            return GainReport(skill_id=skill_id)

        n = len(relevant)
        avg_eff = sum(e.scores.effectiveness for e in relevant) / n
        avg_effi = sum(e.scores.efficiency for e in relevant) / n
        avg_qual = sum(e.scores.quality for e in relevant) / n
        avg_gain = sum(e.scores.gain for e in relevant) / n

        # Combined score: weighted average
        combined = (
            avg_eff * 0.35  # Effectiveness 35%
            + avg_effi * 0.20  # Efficiency 20%
            + avg_qual * 0.25  # Quality 25%
            + max(0, avg_gain) * 0.20  # Gain 20% (only positive contributes)
        )

        return GainReport(
            skill_id=skill_id,
            execution_count=n,
            avg_effectiveness=round(avg_eff, 2),
            avg_efficiency=round(avg_effi, 2),
            avg_quality=round(avg_qual, 2),
            avg_gain=round(avg_gain, 2),
            combined_score=round(combined, 2),
        )

    def combination_gain(self, skill_a: str, skill_b: str) -> float:
        """Calculate the marginal gain of using A+B vs A alone.

        Compares executions where A+B were used together vs A alone.
        Returns the effectiveness difference (positive = B helps A).
        """
        self._ensure_loaded()

        together = [e for e in self._executions if skill_a in e.skill_ids and skill_b in e.skill_ids]
        alone = [e for e in self._executions if skill_a in e.skill_ids and skill_b not in e.skill_ids]

        if not together or not alone:
            return 0.0

        avg_together = sum(e.scores.effectiveness for e in together) / len(together)
        avg_alone = sum(e.scores.effectiveness for e in alone) / len(alone)

        return round(avg_together - avg_alone, 2)

    def get_top_combinations(self, intent: str = "", top_k: int = 5) -> list[dict]:
        """Get top-performing skill combinations based on historical gain data.

        Args:
            intent: Optional intent text to filter by (keyword match on skill_ids)
            top_k: Maximum results to return

        Returns:
            List of dicts with skill_id, avg_gain, execution_count, last_execution
        """
        self._ensure_loaded()

        # Aggregate gain per skill_id
        skill_stats: dict[str, dict] = {}
        for ex in self._executions:
            for sid in ex.skill_ids:
                if sid not in skill_stats:
                    skill_stats[sid] = {"total_gain": 0.0, "count": 0, "last": ""}
                skill_stats[sid]["total_gain"] += ex.scores.effectiveness
                skill_stats[sid]["count"] += 1
                if ex.timestamp > skill_stats[sid]["last"]:
                    skill_stats[sid]["last"] = ex.timestamp

        # Filter by intent if provided
        if intent:
            intent_lower = intent.lower()
            skill_stats = {
                k: v
                for k, v in skill_stats.items()
                if k.lower() in intent_lower or any(w in k.lower() for w in intent_lower.split())
            }

        # Sort by average gain
        results = []
        for sid, stats in skill_stats.items():
            avg_gain = stats["total_gain"] / stats["count"] if stats["count"] > 0 else 0.0
            results.append(
                {
                    "skill_id": sid,
                    "avg_gain": round(avg_gain, 2),
                    "execution_count": stats["count"],
                    "last_execution": stats["last"],
                }
            )

        return sorted(results, key=lambda x: x["avg_gain"], reverse=True)[:top_k]

    def get_gain_history(self, skill_id: str) -> list[dict]:
        """Get execution history for a specific skill.

        Returns list of dicts with timestamp, gain, skill_ids.
        """
        self._ensure_loaded()
        return [
            {"timestamp": ex.timestamp, "gain": ex.scores.effectiveness, "skill_ids": ex.skill_ids}
            for ex in self._executions
            if skill_id in ex.skill_ids
        ]
