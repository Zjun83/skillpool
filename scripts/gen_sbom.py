"""Generate CycloneDX 1.5 JSON SBOM from pip environment.

Usage: python scripts/gen_sbom.py [--output sbom.json]
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def generate_sbom(output_path: str = "sbom.json") -> str:
    """Generate CycloneDX 1.5 JSON SBOM."""
    # Get installed packages
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True,
    )
    packages = json.loads(result.stdout)

    # Get project metadata
    import importlib.metadata
    try:
        meta = importlib.metadata.metadata("skillpool")
        pkg_version = meta.get("Version", "4.3.0")
        pkg_name = meta.get("Name", "skillpool")
    except importlib.metadata.PackageNotFoundError:
        pkg_version = "4.3.0"
        pkg_name = "skillpool"

    components = []
    for pkg in packages:
        name = pkg["name"]
        version = pkg["version"]
        if name.lower() == "skillpool":
            continue  # Root component, not a dependency
        purl = f"pkg:pypi/{name}@{version}"
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": purl,
            "bom-ref": purl,
        })

    sbom = {
        "$schema": "https://cyclonedx.org/schema/bom-1.5.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{_uuid()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "name": pkg_name,
                "version": pkg_version,
                "bom-ref": f"pkg:pypi/{pkg_name}@{pkg_version}",
            },
            "tools": [
                {
                    "name": "skillpool-gen-sbom",
                    "version": "1.0.0",
                },
            ],
        },
        "components": components,
    }

    output = Path(output_path)
    output.write_text(json.dumps(sbom, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(output)


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


if __name__ == "__main__":
    out = "sbom.json"
    if len(sys.argv) > 2 and sys.argv[1] == "--output":
        out = sys.argv[2]
    path = generate_sbom(out)
    print(f"SBOM written to {path}")