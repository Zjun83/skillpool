"""Tests for ParadigmRegistry — 4D 范式 Skill 注册 + 查询。"""

from __future__ import annotations


import pytest

from skillpool.paradigm import Paradigm, ParadigmEntry, ParadigmRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ParadigmRegistry:
    """Fresh ParadigmRegistry (no disk persistence)."""
    return ParadigmRegistry()


@pytest.fixture
def loaded(registry: ParadigmRegistry) -> ParadigmRegistry:
    """Registry with all 4 defaults registered."""
    registry.register_defaults()
    return registry


# ---------------------------------------------------------------------------
# 1. register_defaults() registers all 4 paradigms
# ---------------------------------------------------------------------------


class TestRegisterDefaults:
    def test_registers_four(self, registry: ParadigmRegistry) -> None:
        registry.register_defaults()
        assert len(registry.list_all()) == 4

    @pytest.mark.parametrize("paradigm", list(Paradigm))
    def test_each_paradigm_present(self, loaded: ParadigmRegistry, paradigm: Paradigm) -> None:
        entry = loaded.get(paradigm)
        assert entry is not None
        assert entry.paradigm is paradigm

    def test_idempotent(self, registry: ParadigmRegistry) -> None:
        registry.register_defaults()
        registry.register_defaults()
        assert len(registry.list_all()) == 4


# ---------------------------------------------------------------------------
# 2. get() returns correct ParadigmEntry
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.parametrize("paradigm", list(Paradigm))
    def test_returns_entry(self, loaded: ParadigmRegistry, paradigm: Paradigm) -> None:
        entry = loaded.get(paradigm)
        assert isinstance(entry, ParadigmEntry)
        assert entry.paradigm is paradigm
        assert isinstance(entry.csdf, dict)
        assert isinstance(entry.registered_at, str)

    def test_returns_none_for_unregistered(self, registry: ParadigmRegistry) -> None:
        assert registry.get(Paradigm.TDD) is None


# ---------------------------------------------------------------------------
# 3. get_by_name() case-insensitive lookup
# ---------------------------------------------------------------------------


class TestGetByName:
    def test_uppercase(self, loaded: ParadigmRegistry) -> None:
        entry = loaded.get_by_name("TDD")
        assert entry is not None
        assert entry.paradigm is Paradigm.TDD

    def test_lowercase(self, loaded: ParadigmRegistry) -> None:
        entry = loaded.get_by_name("bdd")
        assert entry is not None
        assert entry.paradigm is Paradigm.BDD

    def test_mixed_case(self, loaded: ParadigmRegistry) -> None:
        entry = loaded.get_by_name("DocsDD")
        assert entry is not None
        assert entry.paradigm is Paradigm.DOCS_DD

    def test_not_found(self, loaded: ParadigmRegistry) -> None:
        assert loaded.get_by_name("nonexistent") is None


# ---------------------------------------------------------------------------
# 4. list_all() returns 4 entries
# ---------------------------------------------------------------------------


class TestListAll:
    def test_count(self, loaded: ParadigmRegistry) -> None:
        assert len(loaded.list_all()) == 4

    def test_empty_before_register(self, registry: ParadigmRegistry) -> None:
        assert len(registry.list_all()) == 0

    def test_all_paradigm_types(self, loaded: ParadigmRegistry) -> None:
        paradigms = {e.paradigm for e in loaded.list_all()}
        assert paradigms == set(Paradigm)


# ---------------------------------------------------------------------------
# 5. unregister() removes entry
# ---------------------------------------------------------------------------


class TestUnregister:
    def test_removes_entry(self, loaded: ParadigmRegistry) -> None:
        result = loaded.unregister(Paradigm.TDD)
        assert result is True
        assert loaded.get(Paradigm.TDD) is None
        assert len(loaded.list_all()) == 3

    def test_returns_false_for_missing(self, registry: ParadigmRegistry) -> None:
        result = registry.unregister(Paradigm.TDD)
        assert result is False

    def test_double_unregister(self, loaded: ParadigmRegistry) -> None:
        assert loaded.unregister(Paradigm.BDD) is True
        assert loaded.unregister(Paradigm.BDD) is False


# ---------------------------------------------------------------------------
# 6. validate() catches missing required fields
# ---------------------------------------------------------------------------


class TestValidate:
    REQUIRED_FIELDS = ("id", "name", "version", "dimension", "paradigm", "checklist")

    def test_catches_all_missing(self, registry: ParadigmRegistry) -> None:
        registry.register(Paradigm.TDD, {"id": "only-id"})
        errors = registry.validate(Paradigm.TDD)
        missing = {e.split(": ")[1] for e in errors}
        assert "name" in missing
        assert "version" in missing
        assert "dimension" in missing
        assert "paradigm" in missing
        assert "checklist" in missing

    def test_valid_csdf_no_errors(self, loaded: ParadigmRegistry) -> None:
        errors = loaded.validate(Paradigm.TDD)
        assert errors == []

    def test_empty_string_treated_as_missing(self, registry: ParadigmRegistry) -> None:
        registry.register(
            Paradigm.BDD,
            {
                "id": "x",
                "name": "",
                "version": "1.0",
                "dimension": "D7",
                "paradigm": "bdd",
                "checklist": [],
            },
        )
        errors = registry.validate(Paradigm.BDD)
        field_names = [e.split(": ")[1] for e in errors]
        assert "name" in field_names

    def test_empty_checklist_treated_as_missing(self, registry: ParadigmRegistry) -> None:
        registry.register(
            Paradigm.SDD,
            {
                "id": "x",
                "name": "SDD",
                "version": "1.0",
                "dimension": "D7",
                "paradigm": "sdd",
                "checklist": [],
            },
        )
        errors = registry.validate(Paradigm.SDD)
        field_names = [e.split(": ")[1] for e in errors]
        assert "checklist" in field_names


# ---------------------------------------------------------------------------
# 7. Each paradigm CSDF has id, name, version, dimension, paradigm, checklist
# ---------------------------------------------------------------------------


class TestCSDFStructure:
    REQUIRED_KEYS = {"id", "name", "version", "dimension", "paradigm", "checklist"}

    @pytest.mark.parametrize("paradigm", list(Paradigm))
    def test_has_required_keys(self, loaded: ParadigmRegistry, paradigm: Paradigm) -> None:
        entry = loaded.get(paradigm)
        assert entry is not None
        missing = self.REQUIRED_KEYS - set(entry.csdf.keys())
        assert missing == set(), f"{paradigm.value} missing keys: {missing}"

    @pytest.mark.parametrize("paradigm", list(Paradigm))
    def test_checklist_is_nonempty_list(self, loaded: ParadigmRegistry, paradigm: Paradigm) -> None:
        entry = loaded.get(paradigm)
        assert isinstance(entry.csdf["checklist"], list)
        assert len(entry.csdf["checklist"]) > 0

    @pytest.mark.parametrize("paradigm", list(Paradigm))
    def test_paradigm_field_matches_enum(self, loaded: ParadigmRegistry, paradigm: Paradigm) -> None:
        entry = loaded.get(paradigm)
        assert entry.csdf["paradigm"] == paradigm.value


class TestEmergencyOverride:
    """Tests for emergency override actions (WARN/DEGRADE/QUARANTINE/KILL)."""

    def test_apply_warn_override(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        override = registry.apply_override(OverrideLevel.WARN, "tdd", "Test warning")
        assert override.level == OverrideLevel.WARN
        assert override.target == "tdd"
        assert override.revoked is False

    def test_apply_degrade_override(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        registry.register_defaults()
        override = registry.apply_override(OverrideLevel.DEGRADE, "bdd", "Performance issue")
        assert override.level == OverrideLevel.DEGRADE
        # DEGRADE should not change lifecycle state
        entry = registry.get(Paradigm.BDD)
        assert entry.csdf["lifecycle_state"] == "ACTIVE"

    def test_quarantine_sets_lifecycle(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        registry.register_defaults()
        registry.apply_override(OverrideLevel.QUARANTINE, "sdd", "Security concern")
        entry = registry.get(Paradigm.SDD)
        assert entry.csdf["lifecycle_state"] == "QUARANTINED"

    def test_kill_sets_lifecycle(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        registry.register_defaults()
        registry.apply_override(OverrideLevel.KILL, "docsdd", "Critical failure")
        entry = registry.get(Paradigm.DOCS_DD)
        assert entry.csdf["lifecycle_state"] == "KILLED"

    def test_revoke_override(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        registry.apply_override(OverrideLevel.WARN, "tdd", "Warning")
        assert registry.revoke_override("tdd") is True
        assert registry.revoke_override("tdd") is False  # Already revoked

    def test_revoke_restores_lifecycle(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        registry.register_defaults()
        registry.apply_override(OverrideLevel.QUARANTINE, "sdd", "Issue")
        registry.revoke_override("sdd")
        entry = registry.get(Paradigm.SDD)
        assert entry.csdf["lifecycle_state"] == "ACTIVE"

    def test_get_active_overrides(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        registry.apply_override(OverrideLevel.WARN, "tdd", "Warn")
        registry.apply_override(OverrideLevel.DEGRADE, "bdd", "Degrade")
        registry.revoke_override("tdd")
        active = registry.get_active_overrides()
        assert len(active) == 1
        assert active[0].target == "bdd"

    def test_get_override_level_highest(self, registry: ParadigmRegistry) -> None:
        from skillpool.paradigm import OverrideLevel

        registry.apply_override(OverrideLevel.WARN, "tdd", "Low")
        registry.apply_override(OverrideLevel.KILL, "tdd", "Critical")
        level = registry.get_override_level("tdd")
        assert level == OverrideLevel.KILL

    def test_get_override_level_none(self, registry: ParadigmRegistry) -> None:
        assert registry.get_override_level("nonexistent") is None
