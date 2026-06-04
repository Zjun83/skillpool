#!/usr/bin/env python3
"""Sign artifacts using cosign (production) or sigstore-keyless (CI fallback).

Usage:
    python scripts/sign_artifact.py <artifact_path> [--key <key-path>] [--keyless]

Production (with key):
    python scripts/sign_artifact.py sbom.json --key cosign.key

CI (keyless, uses SIGSTORE_IDENTITY_TOKEN):
    python scripts/sign_artifact.py sbom.json --keyless
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def sign_cosign_key(artifact_path: str, key_path: str) -> bool:
    """Sign artifact using cosign with a local key pair."""
    if not shutil.which("cosign"):
        print("ERROR: cosign not found in PATH", file=sys.stderr)
        return False

    sig_path = f"{artifact_path}.sig"
    cmd = [
        "cosign", "sign-blob",
        "--key", key_path,
        "--tlog-upload=false",  # Skip transparency log for local signing
        "--output-signature", sig_path,
        artifact_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Signed: {artifact_path}")
        print(f"Signature: {sig_path}")
        return True
    else:
        print(f"Signing failed: {result.stderr}", file=sys.stderr)
        return False


def sign_cosign_keyless(artifact_path: str) -> bool:
    """Sign artifact using cosign keyless mode (for CI)."""
    if not shutil.which("cosign"):
        print("ERROR: cosign not found in PATH", file=sys.stderr)
        return False

    sig_path = f"{artifact_path}.sig"
    cert_path = f"{artifact_path}.cert"
    cmd = [
        "cosign", "sign-blob",
        "--yes",
        "--output-signature", sig_path,
        "--output-certificate", cert_path,
        artifact_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Signed (keyless): {artifact_path}")
        print(f"Signature: {sig_path}")
        print(f"Certificate: {cert_path}")
        return True
    else:
        print(f"Keyless signing failed: {result.stderr}", file=sys.stderr)
        return False


def verify_signature(artifact_path: str, key_path: str | None = None) -> bool:
    """Verify artifact signature."""
    if not shutil.which("cosign"):
        print("ERROR: cosign not found in PATH", file=sys.stderr)
        return False

    sig_path = f"{artifact_path}.sig"
    if not Path(sig_path).exists():
        print(f"Signature not found: {sig_path}", file=sys.stderr)
        return False

    cmd = ["cosign", "verify-blob", "--insecure-ignore-tlog"]
    if key_path:
        cmd.extend(["--key", key_path])
    else:
        cert_path = f"{artifact_path}.cert"
        cmd.extend(["--certificate", cert_path])

    cmd.extend(["--signature", sig_path, artifact_path])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Verified: {artifact_path}")
        return True
    else:
        print(f"Verification failed: {result.stderr}", file=sys.stderr)
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python sign_artifact.py <artifact_path> [--key <key-path>] [--keyless]")
        sys.exit(1)

    artifact = sys.argv[1]
    if not Path(artifact).exists():
        print(f"Artifact not found: {artifact}", file=sys.stderr)
        sys.exit(1)

    if "--keyless" in sys.argv:
        success = sign_cosign_keyless(artifact)
    elif "--key" in sys.argv:
        idx = sys.argv.index("--key")
        key_path = sys.argv[idx + 1]
        success = sign_cosign_key(artifact, key_path)
    else:
        # Default: try keyless
        success = sign_cosign_keyless(artifact)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
