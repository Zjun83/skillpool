"""Extended tests for skillpool.registry — covering missing branches."""

from skillpool.registry import Registry, SkillEntry


class TestRegistryForceOverwrite:
    """Test force=True on register (covers line 71)."""

    def test_register_force_overwrites_existing(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        entry_v1 = SkillEntry(name="force-skill", description="v1", quality_score=0.5)
        reg.register(entry_v1)
        entry_v2 = SkillEntry(name="force-skill", description="v2", quality_score=0.9)
        result = reg.register(entry_v2, force=True)
        assert result.description == "v2"
        assert result.quality_score == 0.9
        assert reg.count() == 1


class TestRegistryListWithTags:
    """Test list_entries with tags filter (covers line 89-90)."""

    def test_list_entries_with_tags(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        reg.register(SkillEntry(name="tagged-skill", description="t", tags=["ai", "code"]))
        reg.register(SkillEntry(name="untagged-skill", description="u", tags=[]))
        result = reg.list_entries(tags=["ai"])
        assert len(result) == 1
        assert result[0].name == "tagged-skill"

    def test_list_entries_with_multiple_tags(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        reg.register(SkillEntry(name="multi-tag", description="m", tags=["ai", "code", "test"]))
        result = reg.list_entries(tags=["test", "other"])
        assert len(result) == 1


class TestRegistryUpdateNonexistent:
    """Test update on nonexistent skill (covers line 105)."""

    def test_update_nonexistent_returns_none(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        result = reg.update("ghost-skill", {"quality_score": 0.5})
        assert result is None


class TestRegistryIterEntries:
    """Test iter_entries generator (covers lines 122-133)."""

    def test_iter_entries_yields_skills(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        reg.register(SkillEntry(name="iter-a", description="a"))
        reg.register(SkillEntry(name="iter-b", description="b"))
        names = [e.name for e in reg.iter_entries()]
        assert names == ["iter-a", "iter-b"]

    def test_iter_entries_empty(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        names = list(reg.iter_entries())
        assert names == []

    def test_iter_entries_skips_malformed(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        reg.register(SkillEntry(name="good-skill", description="good"))
        # Append a malformed line
        with open(reg._path, "a") as f:
            f.write("not-json\n")
        names = [e.name for e in reg.iter_entries()]
        assert names == ["good-skill"]


class TestRegistryReadAllMalformed:
    """Test _read_all with malformed lines (covers lines 54-55)."""

    def test_read_all_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "registry.jsonl"
        path.write_text('{"name":"ok"}\nBADLINE\n{"name":"also-ok"}\n')
        reg = Registry(registry_path=path)
        entries = reg._read_all()
        assert len(entries) == 2


class TestRegistryRegisteredAtAutoSet:
    """Test that registered_at is auto-set (covers line 50)."""

    def test_registered_at_auto_set(self, tmp_path):
        reg = Registry(registry_path=tmp_path / "registry.jsonl")
        entry = SkillEntry(name="auto-ts", description="auto")
        result = reg.register(entry)
        assert result.registered_at != ""
        assert "T" in result.registered_at  # ISO format
