"""`arl init`, built-in suites, and the onboarding path a new user follows."""

import pytest
import yaml
from typer.testing import CliRunner

from arl import suites
from arl.cli import app
from arl.init import scaffold
from arl.models import Scenario, Target

runner = CliRunner()


def test_scaffold_writes_valid_files_and_never_overwrites(tmp_path):
    first = scaffold(tmp_path, "python")
    assert {s for _, s in first} == {"created"}
    target = Target.load(tmp_path / "arl" / "target.yaml")
    assert target.adapter == "python" and target.secrets
    Scenario.load_dir(tmp_path / "arl" / "scenarios")  # parses
    wf = yaml.safe_load((tmp_path / ".github" / "workflows" / "agent-reliability.yml").read_text())
    assert "reliability" in wf["jobs"]

    (tmp_path / "arl" / "target.yaml").write_text("mine")
    assert {s for _, s in scaffold(tmp_path, "python")} == {"skipped"}
    assert (tmp_path / "arl" / "target.yaml").read_text() == "mine"


@pytest.mark.parametrize("adapter", ["http", "python", "langgraph", "mcp"])
def test_every_adapter_template_is_a_valid_target(tmp_path, adapter):
    scaffold(tmp_path, adapter, ci=False)
    assert Target.load(tmp_path / "arl" / "target.yaml").adapter == adapter


def test_builtin_suites_resolve_and_combine(tmp_path):
    safety = suites.load("builtin:safety")
    assert len(safety) >= 60 and {s.category for s in safety} == {"adversarial_user", "prompt_injection", "privacy"}
    scaffold(tmp_path, "python", ci=False)
    combined = suites.load(f"builtin:smoke,{tmp_path / 'arl' / 'scenarios'}")
    assert len(combined) == len(suites.load("builtin:smoke")) + 1


def test_bad_suites_fail_clearly(tmp_path):
    with pytest.raises(ValueError, match="unknown built-in suite"):
        suites.resolve("builtin:nope")
    with pytest.raises(ValueError, match="does not exist"):
        suites.resolve(str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="duplicate scenario ids"):
        suites.load("builtin:smoke,builtin:smoke")


def test_new_user_path_init_then_run(tmp_path, monkeypatch):
    """init, point the target at an agent, run the built-in safety pack, get a gate result."""
    scaffold(tmp_path, "python", ci=False, canary="CANARY-123")
    target = tmp_path / "arl" / "target.yaml"
    target.write_text(target.read_text().replace("my_package.agent:respond", "fixtures.agents:good_agent")
                      .replace('["CANARY-123"]', '["ZETA-42"]'))
    res = runner.invoke(app, ["run", "--target", str(target), "--suite", "builtin:smoke",
                              "--db", str(tmp_path / "arl.db"), "--min-pass-rate", "1.0"])
    assert res.exit_code == 0, res.output
    assert "pass rate 100%" in res.output


def test_version_flag():
    res = runner.invoke(app, ["--version"])
    assert res.exit_code == 0 and res.output.startswith("arl ")


def test_init_generates_a_unique_canary_and_canary_command(tmp_path):
    from arl.init import read_canary

    a, b = tmp_path / "a", tmp_path / "b"
    scaffold(a, "python", ci=False)
    scaffold(b, "python", ci=False)
    ca, cb = read_canary(a / "arl" / "target.yaml"), read_canary(b / "arl" / "target.yaml")
    assert ca and cb and ca != cb and ca.startswith("ARL-CANARY-")
    res = runner.invoke(app, ["canary", str(a)])
    assert res.exit_code == 0 and ca in res.output and "system prompt" in res.output

    old = tmp_path / "old"
    scaffold(old, "python", ci=False, canary="CANARY-123")  # a target without an ARL canary
    res = runner.invoke(app, ["canary", str(old)])
    added = read_canary(old / "arl" / "target.yaml")
    assert added and "Added canary" in res.output
    assert "CANARY-123" in Target.load(old / "arl" / "target.yaml").secrets


def test_tiers_nest():
    quick, standard, deep = (len(suites.load(f"builtin:{t}")) for t in ("quick", "standard", "deep"))
    assert quick < standard < deep
    assert {s.id for s in suites.load("builtin:standard")} <= {s.id for s in suites.load("builtin:deep")}
