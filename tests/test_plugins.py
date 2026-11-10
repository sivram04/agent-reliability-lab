"""Plugin registry: checks, mutators, rubrics and adapters from a module."""

import asyncio
import random

import pytest
from typer.testing import CliRunner

from arl import plugins
from arl.adapters import ADAPTERS, build_agent
from arl.cli import app
from arl.judges import RUBRICS, rubrics_for
from arl.models import Criteria, Scenario, Target
from arl.redteam import MUTATORS
from arl.runner import run_suite


@pytest.fixture(scope="module", autouse=True)
def loaded():
    checks = list(plugins.CHECKS)
    plugins.load(["fixtures.example_plugin"])
    yield
    plugins.CHECKS[:] = checks
    for registry, key in ((ADAPTERS, "echo"), (MUTATORS, "shout"), (RUBRICS, "tone")):
        registry.pop(key, None)
    plugins._loaded.discard("fixtures.example_plugin")


def _scenario(**extra):
    return Scenario(id="p1", category="task_success", goal="g", turns=["hello"], criteria=Criteria(extra=extra))


def test_registries_receive_plugin_entries():
    assert "echo" in ADAPTERS and "shout" in MUTATORS and "tone" in RUBRICS
    assert MUTATORS["shout"]("hi", random.Random(0)) == "HI!!!"


def test_plugin_adapter_and_opt_in_check():
    agent = build_agent(Target(name="e", adapter="echo"))
    strict, loose, off = (asyncio.run(run_suite(agent, [_scenario(**x)]))[0]
                          for x in ({"max_sorry": 1}, {"max_sorry": 5}, {}))
    assert not strict.passed and loose.passed
    assert not any(c.name == "max_sorry" for c in off.checks)


def test_broken_check_fails_only_itself():
    @plugins.check
    def explode(ctx):
        raise RuntimeError("boom")

    try:
        r = asyncio.run(run_suite(build_agent(Target(name="e", adapter="echo")), [_scenario()]))[0]
        bad = [c for c in r.checks if c.name == "plugin:explode"]
        assert bad and not bad[0].passed and "boom" in bad[0].detail
    finally:
        plugins.CHECKS.remove(explode)


def test_unknown_names_fail_clearly():
    with pytest.raises(ValueError, match="unknown adapter"):
        build_agent(Target(name="x", adapter="nope"))
    with pytest.raises(ValueError, match="unknown rubric"):
        rubrics_for(Scenario(id="x", category="task_success", goal="g", criteria=Criteria(rubrics=["nope"])))


def test_cli_plugin_flag():
    res = CliRunner().invoke(app, ["--plugin", "definitely_missing_mod", "suites"])
    assert res.exit_code != 0 and "cannot import plugin" in res.output
