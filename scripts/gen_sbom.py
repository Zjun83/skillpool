#!/usr/bin/env python3
"""Generate CycloneDX 1.5 JSON SBOM for SkillPool."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path


def get_dependencies() -> list[dict]:
    """Extract dependencies from pip list."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True,
    )
    packages = json.loads(result.stdout)
    deps = []
    for pkg in packages:
        if pkg["name"].lower().startswith("skillpool"):
            continue
        deps.append({
            "bom-ref": f"pkg:pypi/{pkg['name'].lower()}@{pkg['version']}",
            "type": "library",
            "name": pkg["name"],
            "version": pkg["version"],
            "purl": f"pkg:pypi/{pkg['name'].lower()}@{pkg['version']}",
        })
    return deps


def generate_sbom(output_path: str | None = None) -> dict:
    """Generate CycloneDX 1.5 JSON SBOM."""
    try:
        import importlib.metadata
        version = importlib.metadata.version("skillpool")
    except Exception:
        version = "0.0.0"

    components = get_dependencies()

    sbom = {
        "$schema": "https://cyclonedx.org/schema/bom-1.5.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "bom-ref": "pkg:pypi/skillpool",
                "type": "application",
                "name": "skillpool",
                "version": version,
            },
            "tools": [{"vendor": "SkillPool", "name": "gen_sbom", "version": "1.0.0"}],
        },
        "components": components,
    }

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(sbom, f, indent=2)
        print(f"SBOM written to {output_path} ({len(components)} components)")

    return sbom


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "sbom.json"
    generate_sbom(output)
