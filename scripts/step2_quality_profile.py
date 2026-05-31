#!/usr/bin/env python3
"""SkillPool Step 2: Scan SKILL.md sources → Quality Profile → Weight Calibration.

Usage:
    python scripts/step2_quality_profile.py [--skill-dirs DIR1,DIR2] [--output DIR] [--calibrate]

Outputs:
    - quality_profiles.jsonl  — one QualityProfile per skill
    - calibration_report.json — weight calibration summary
    - weight_adjustments.json — recommended weight deltas
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from skillpool.csdf import CSDFParser, CSDFDocument
from skillpool.quality import QualityProfiler, QualityProfile, DEFAULT_WEIGHTS, CALIBRATION_OFFSETS


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_skill_dirs(skill_dirs: list[Path]) -> list[tuple[Path, str]]:
    """Scan directories for SKILL.md files. Returns list of (path, raw_content)."""
    results: list[tuple[Path, str]] = []
    for d in skill_dirs:
        if not d.is_dir():
            print(f"  ⚠ Skipping non-existent dir: {d}")
            continue
        for skill_md in sorted(d.rglob("SKILL.md")):
            content = skill_md.read_text(encoding="utf-8", errors="replace")
            results.append((skill_md, content))
    return results


# ---------------------------------------------------------------------------
# Quality Profiling
# ---------------------------------------------------------------------------

def profile_skills(
    skill_files: list[tuple[Path, str]],
    profiler: QualityProfiler,
) -> list[dict]:
    """Parse and profile each SKILL.md. Returns list of profile dicts."""
    parser = CSDFParser()
    profiles: list[dict] = []
    errors: list[dict] = []

    for skill_path, content in skill_files:
        try:
            doc = parser.parse(content, source_path=str(skill_path))
            profile = profiler.profile(doc)
            profiles.append({
                "name": profile.name,
                "source": str(skill_path),
                "completeness": profile.completeness,
                "accuracy": profile.accuracy,
                "usability": profile.usability,
                "maintainability": profile.maintainability,
                "overall": profile.overall,
                "weights": profile.weights,
                "calibration_note": profile.calibration_note,
            })
        except Exception as e:
            errors.append({"source": str(skill_path), "error": str(e)})

    return profiles, errors


# ---------------------------------------------------------------------------
# Weight Calibration
# ---------------------------------------------------------------------------

def calibrate_weights(profiles: list[dict]) -> dict:
    """Analyze profile distribution and recommend weight adjustments.

    Strategy:
    - If a dimension has very low variance (all skills score similarly),
      reduce its weight (it doesn't discriminate).
    - If a dimension has high variance and correlates with overall quality,
      increase its weight.
    - Target: overall accuracy ≥ 0.90 (measured as rank correlation between
      weighted score and a simple mean score).
    """
    if not profiles:
        return {"adjustments": {}, "note": "No profiles to calibrate"}

    dims = ["completeness", "accuracy", "usability", "maintainability"]
    n = len(profiles)

    # Compute per-dimension statistics
    dim_stats: dict[str, dict] = {}
    for dim in dims:
        values = [p[dim] for p in profiles]
        mean = sum(values) / n if n > 0 else 0.0
        variance = sum((v - mean) ** 2 for v in values) / n if n > 0 else 0.0
        dim_stats[dim] = {"mean": round(mean, 4), "variance": round(variance, 6)}

    # Compute simple mean score (unweighted) as ground truth
    simple_means = []
    for p in profiles:
        sm = sum(p[d] for d in dims) / len(dims)
        simple_means.append(sm)

    # Compute current weighted scores
    current_weights = DEFAULT_WEIGHTS.copy()
    weighted_scores = []
    for p in profiles:
        ws = sum(p[d] * current_weights.get(d, 0.25) for d in dims)
        weighted_scores.append(ws)

    # Spearman rank correlation (simplified)
    def rank_correlation(a: list[float], b: list[float]) -> float:
        if len(a) < 3:
            return 1.0
        n_items = len(a)
        def ranks(arr):
            sorted_indices = sorted(range(n_items), key=lambda i: arr[i])
            r = [0.0] * n_items
            for i, idx in enumerate(sorted_indices):
                r[idx] = i + 1
            return r
        ra = ranks(a)
        rb = ranks(b)
        d_sq = sum((ra[i] - rb[i]) ** 2 for i in range(n_items))
        denom = n_items * (n_items ** 2 - 1)
        if denom == 0:
            return 1.0
        return 1.0 - (6.0 * d_sq / denom)

    current_corr = rank_correlation(simple_means, weighted_scores)

    # Adjust weights: reduce weight for low-variance dims, increase for high-variance
    adjustments: dict[str, float] = {}
    total_variance = sum(dim_stats[d]["variance"] for d in dims)
    if total_variance > 0:
        for dim in dims:
            # Proportional variance weight
            var_weight = dim_stats[dim]["variance"] / total_variance
            current_w = current_weights.get(dim, 0.25)
            # Blend: 70% current + 30% variance-proportional
            new_w = 0.7 * current_w + 0.3 * var_weight
            adjustments[dim] = round(new_w - current_w, 4)
    else:
        for dim in dims:
            adjustments[dim] = 0.0

    # Apply adjustments and re-check correlation
    adjusted_weights = {d: round(current_weights.get(d, 0.25) + adjustments[d], 4) for d in dims}
    # Normalize to sum=1.0
    wsum = sum(adjusted_weights.values())
    if wsum > 0:
        adjusted_weights = {d: round(v / wsum, 4) for d, v in adjusted_weights.items()}

    adjusted_scores = []
    for p in profiles:
        ws = sum(p[d] * adjusted_weights.get(d, 0.25) for d in dims)
        adjusted_scores.append(ws)

    adjusted_corr = rank_correlation(simple_means, adjusted_scores)

    return {
        "current_weights": current_weights,
        "adjusted_weights": adjusted_weights,
        "adjustments": adjustments,
        "dim_stats": dim_stats,
        "current_rank_correlation": round(current_corr, 4),
        "adjusted_rank_correlation": round(adjusted_corr, 4),
        "calibration_improved": adjusted_corr >= current_corr,
        "accuracy_target_met": adjusted_corr >= 0.90,
        "n_profiles": n,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="SkillPool Step 2: Quality Profile + Weight Calibration")
    parser.add_argument(
        "--skill-dirs",
        default="/root/.codex/skills,/root/.codex-sessions/sessions/20260527_012347_1957890_62c85b98/.codex/skills",
        help="Comma-separated skill directories to scan",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data"),
        help="Output directory for profile files",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run weight calibration after profiling",
    )
    args = parser.parse_args()

    skill_dirs = [Path(d.strip()) for d in args.skill_dirs.split(",")]
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 2a: Scan
    print("📂 Scanning skill directories...")
    skill_files = scan_skill_dirs(skill_dirs)
    print(f"   Found {len(skill_files)} SKILL.md files")

    if not skill_files:
        print("❌ No SKILL.md files found. Exiting.")
        return 1

    # Step 2b: Profile
    print("🔍 Profiling skills...")
    profiler = QualityProfiler()
    profiles, errors = profile_skills(skill_files, profiler)

    print(f"   ✅ Profiled: {len(profiles)} skills")
    if errors:
        print(f"   ⚠ Errors: {len(errors)}")
        for e in errors[:5]:
            print(f"      - {e['source']}: {e['error']}")

    # Write profiles
    profiles_path = output_dir / "quality_profiles.jsonl"
    with open(profiles_path, "w", encoding="utf-8") as f:
        for p in profiles:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"   📝 Written: {profiles_path}")

    # Step 2c: Calibrate (optional)
    if args.calibrate:
        print("⚖ Calibrating weights...")
        calibration = calibrate_weights(profiles)
        calibration_path = output_dir / "calibration_report.json"
        with open(calibration_path, "w", encoding="utf-8") as f:
            json.dump(calibration, f, indent=2, ensure_ascii=False)
        print(f"   📝 Written: {calibration_path}")

        adjustments_path = output_dir / "weight_adjustments.json"
        with open(adjustments_path, "w", encoding="utf-8") as f:
            json.dump(calibration["adjusted_weights"], f, indent=2, ensure_ascii=False)
        print(f"   📝 Written: {adjustments_path}")

        # Summary
        print("\n📊 Calibration Summary:")
        print(f"   Current rank correlation: {calibration['current_rank_correlation']}")
        print(f"   Adjusted rank correlation: {calibration['adjusted_rank_correlation']}")
        print(f"   Accuracy target (≥0.90): {'✅ MET' if calibration['accuracy_target_met'] else '❌ NOT MET'}")
        print(f"   Adjusted weights: {calibration['adjusted_weights']}")
    else:
        print("   (Skip calibration — use --calibrate to enable)")

    # Quick stats
    if profiles:
        overalls = [p["overall"] for p in profiles]
        print(f"\n📈 Quality Stats:")
        print(f"   Min overall:  {min(overalls):.4f}")
        print(f"   Max overall:  {max(overalls):.4f}")
        print(f"   Mean overall: {sum(overalls)/len(overalls):.4f}")

    print("\n✅ Step 2 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
