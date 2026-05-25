"""Unit tests for skillpool.registry module."""

import pytest

from skillpool.registry import Registry, SkillEntry


class TestSkillEntry:
    """Tests for SkillEntry model."""

    def test_create_entry_defaults(self):
        entry = SkillEntry(name="test-skill")
        assert entry.name == "test-skill"
        assert entry.version == "0.1.0"
        assert entry.quality_score == 0.0
        assert entry.registered_at == ""

    def test_create_entry_with_all_fields(self):
        entry = SkillEntry(
            name="full-skill",
            version="1.2.3",
            quality_score=0.85,
            registered_at="2025-01-01T00:00:00Z",
            tags=["ai", "coding"],
            description="A full test skill",
        )
        assert entry.name == "full-skill"
        assert entry.version == "1.2.3"
        assert entry.quality_score == 0.85
        assert entry.tags == ["ai", "coding"]


class TestRegistry:
    """Tests for Registry class."""

    def test_create_registry(self, tmp_path):
        reg = Registry(registry_path=tmp_path / ".skillpool" / "registry.jsonl")
        assert reg._path == tmp_path / ".skillpool" / "registry.jsonl"

    def test_register_skill(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        entry = SkillEntry(name="test-skill", description="A test skill")
        reg.register(entry)
        found = reg.get("test-skill")
        assert found is not None
        assert found.name == "test-skill"

    def test_register_duplicate_raises(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        entry = SkillEntry(name="dup-skill", description="dup")
        reg.register(entry)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(SkillEntry(name="dup-skill", description="dup again"))

    def test_delete_skill(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        entry = SkillEntry(name="temp-skill", description="temp")
        reg.register(entry)
        result = reg.delete("temp-skill")
        assert result is True
        assert reg.get("temp-skill") is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        result = reg.delete("no-such-skill")
        assert result is False

    def test_list_entries(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        for i in range(3):
            entry = SkillEntry(name=f"skill-{i}", description=f"Skill {i}")
            reg.register(entry)
        skills = reg.list_entries()
        assert len(skills) == 3

    def test_list_entries_with_min_score(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        reg.register(SkillEntry(name="high-skill", description="high", quality_score=0.9))
        reg.register(SkillEntry(name="low-skill", description="low", quality_score=0.3))
        high_skills = reg.list_entries(min_score=0.7)
        assert len(high_skills) == 1
        assert high_skills[0].name == "high-skill"

    def test_persistence(self, tmp_path):
        reg1 = Registry(registry_path=tmp_path / "registry.jsonl")
        entry = SkillEntry(name="persist-skill", description="persist", quality_score=0.7)
        reg1.register(entry)
        reg2 = Registry(registry_path=tmp_path / "registry.jsonl")
        found = reg2.get("persist-skill")
        assert found is not None
        assert found.name == "persist-skill"
        assert found.quality_score == 0.7

    def test_update_entry(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        entry = SkillEntry(name="update-skill", description="update", quality_score=0.5)
        reg.register(entry)
        reg.update("update-skill", {"quality_score": 0.8})
        found = reg.get("update-skill")
        assert found.quality_score == 0.8

    def test_count(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        assert reg.count() == 0
        reg.register(SkillEntry(name="skill-a", description="a"))
        reg.register(SkillEntry(name="skill-b", description="b"))
        assert reg.count() == 2
