"""Tests for TraceCeiling and AuditHashChain."""

from skillpool.cost.trace_ceiling import TraceCeiling
from skillpool.cost.audit_hash import AuditHashChain


class TestTraceCeiling:
    def test_allows_below_ceiling(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        allowed, reason = tc.check("trace-1", 1.0)
        assert allowed is True
        assert reason == "ok"

    def test_allows_exactly_at_ceiling(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 4.0)
        allowed, _ = tc.check("trace-1", 1.0)
        assert allowed is True

    def test_rejects_above_ceiling(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 4.0)
        allowed, reason = tc.check("trace-1", 2.0)
        assert allowed is False
        assert "ceiling exceeded" in reason

    def test_circuit_broken_at_ceiling(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 5.0)
        assert tc.is_circuit_broken("trace-1") is True

    def test_not_circuit_broken_below_ceiling(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 3.0)
        assert tc.is_circuit_broken("trace-1") is False

    def test_unknown_trace_not_broken(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        assert tc.is_circuit_broken("unknown") is False

    def test_independent_traces(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 5.0)
        assert tc.is_circuit_broken("trace-1") is True
        assert tc.is_circuit_broken("trace-2") is False
        allowed, _ = tc.check("trace-2", 1.0)
        assert allowed is True

    def test_cumulative_cost(self) -> None:
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 2.0)
        tc.record_trace_cost("trace-1", 2.0)
        allowed, _ = tc.check("trace-1", 2.0)
        assert allowed is False  # 4.0 + 2.0 > 5.0


class TestAuditHashChain:
    def test_empty_chain_verifies(self) -> None:
        chain = AuditHashChain()
        assert chain.verify_chain() is True
        assert chain.get_chain() == []

    def test_single_record(self) -> None:
        chain = AuditHashChain()
        h = chain.append({"agent_id": "test", "cost": 1.0})
        assert len(h) == 64  # SHA-256 hex
        assert chain.verify_chain() is True

    def test_multiple_records(self) -> None:
        chain = AuditHashChain()
        chain.append({"agent_id": "a", "cost": 1.0})
        chain.append({"agent_id": "b", "cost": 2.0})
        chain.append({"agent_id": "c", "cost": 3.0})
        assert len(chain.get_chain()) == 3
        assert chain.verify_chain() is True

    def test_chain_hashes_are_different(self) -> None:
        chain = AuditHashChain()
        h1 = chain.append({"agent_id": "a", "cost": 1.0})
        h2 = chain.append({"agent_id": "a", "cost": 1.0})
        # Same data but different previous hash → different hash
        assert h1 != h2

    def test_compute_hash_deterministic(self) -> None:
        h1 = AuditHashChain.compute_hash("0" * 64, {"a": 1})
        h2 = AuditHashChain.compute_hash("0" * 64, {"a": 1})
        assert h1 == h2

    def test_different_data_different_hash(self) -> None:
        h1 = AuditHashChain.compute_hash("0" * 64, {"a": 1})
        h2 = AuditHashChain.compute_hash("0" * 64, {"a": 2})
        assert h1 != h2

    def test_tampered_record_detected(self) -> None:
        chain = AuditHashChain()
        chain.append({"agent_id": "a", "cost": 1.0})
        chain.append({"agent_id": "b", "cost": 2.0})
        # Tamper with the first record
        chain._records[0] = {"agent_id": "a", "cost": 999.0}
        assert chain.verify_chain() is False

    def test_tampered_hash_detected(self) -> None:
        chain = AuditHashChain()
        chain.append({"agent_id": "a", "cost": 1.0})
        chain._hashes[0] = "0" * 64
        assert chain.verify_chain() is False
