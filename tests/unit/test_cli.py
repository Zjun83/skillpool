"""Tests for SkillPool CLI commands."""

from __future__ import annotations

from click.testing import CliRunner

from skillpool.cli import main

runner = CliRunner()


class TestCLIMain:
    def test_version(self):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "4.1.0" in result.output

    def test_help(self):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "SkillPool" in result.output


class TestRegisterCommand:
    def test_register_no_args(self):
        result = runner.invoke(main, ["register"])
        assert result.exit_code == 0
        assert "Register" in result.output

    def test_register_with_name(self):
        result = runner.invoke(main, ["register", "--name", "test-skill"])
        assert result.exit_code == 0


class TestInspectCommand:
    def test_inspect(self):
        result = runner.invoke(main, ["inspect", "test-skill"])
        assert result.exit_code == 0
        assert "test-skill" in result.output


class TestListCommand:
    def test_list_skills(self):
        result = runner.invoke(main, ["list-skills"])
        assert result.exit_code == 0
        assert "List" in result.output

    def test_list_skills_with_min_score(self):
        result = runner.invoke(main, ["list-skills", "--min-score", "0.5"])
        assert result.exit_code == 0


class TestMaterializeCommand:
    def test_materialize(self):
        result = runner.invoke(main, ["materialize", "test-skill"])
        assert result.exit_code == 0
        assert "test-skill" in result.output


class TestGateCommand:
    def test_gate(self):
        result = runner.invoke(main, ["gate", "test-skill"])
        assert result.exit_code == 0
        assert "test-skill" in result.output


class TestStatusCommand:
    def test_status_no_skillpool_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_status_with_skillpool_dir(self, tmp_path, monkeypatch):
        sp_dir = tmp_path / ".skillpool"
        sp_dir.mkdir()
        (sp_dir / "registry.jsonl").write_text(
            '{"name":"test","version":"1.0.0"}\n', encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "found" in result.output
