"""AuditHashChain — SHA-256 hash chain for cost record integrity."""

from __future__ import annotations

import hashlib
import json


class AuditHashChain:
    """Maintain a tamper-evident hash chain over cost records.

    Each record's hash is computed from the previous hash + current record data,
    creating a linked chain where any modification to a prior record invalidates
    all subsequent hashes.
    """

    def __init__(self) -> None:
        self._hashes: list[str] = []
        self._records: list[dict] = []

    @staticmethod
    def compute_hash(previous_hash: str, record_data: dict) -> str:
        """Compute SHA-256 hash from previous hash and record data."""
        payload = previous_hash + json.dumps(record_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def append(self, record_data: dict) -> str:
        """Append a record to the chain and return its hash."""
        previous = self._hashes[-1] if self._hashes else "0" * 64
        new_hash = self.compute_hash(previous, record_data)
        self._hashes.append(new_hash)
        self._records.append(record_data)
        return new_hash

    def verify_chain(self) -> bool:
        """Verify the entire hash chain is consistent.

        Recomputes every hash from scratch and checks against stored values.
        Returns True if the chain is intact.
        """
        previous = "0" * 64
        for i, record in enumerate(self._records):
            expected = self.compute_hash(previous, record)
            if self._hashes[i] != expected:
                return False
            previous = expected
        return True

    def get_chain(self) -> list[str]:
        """Return a copy of the hash chain."""
        return list(self._hashes)
