"""JUnit export and the `arl mcp` server, driven by a real MCP client over stdio."""

import asyncio
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from arl.adapters import build_agent
from arl.junit import to_xml
from arl.models import Target
from arl.runner import run_suite
from arl.suites import load

SMOKE = load("builtin:smoke")


def test_junit_counts_failures_and_redacts_secrets():
    target = Target.load("fixtures/bad.yaml")
    results = asyncio.run(run_suite(build_agent(target), SMOKE))
    xml = to_xml(results, target.name, target.secrets)
    root = ET.fromstring(xml)
    failed = sum(r.error is None and not r.passed for r in results)
    assert int(root.get("tests")) == len(results) and int(root.get("failures")) == failed
    assert len(root.findall(".//testcase")) == len(results)
    assert not any(s.lower() in xml.lower() for s in target.secrets) and "[REDACTED]" in xml


async def _call_tools(db: str):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-c", "from arl.mcp_server import main; main()"],
                                   cwd=str(Path.cwd()))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        run = await session.call_tool("run_suite", {"target": "fixtures/bad.yaml", "suite": "builtin:smoke",
                                                    "db": db}, read_timeout_seconds=120)
        runs = await session.call_tool("list_runs", {"db": db})
    return names, run, runs


def _payload(result):
    if result.structured_content:
        data = result.structured_content
        return data.get("result", data)
    return json.loads("".join(getattr(c, "text", "") for c in result.content))


def test_mcp_server_runs_a_suite_and_redacts(tmp_path):
    db = str(tmp_path / "arl.db")
    names, run, runs = asyncio.run(_call_tools(db))
    assert {"list_suites", "init_project", "run_suite", "list_runs", "run_failures", "compare_runs"} <= names
    assert not run.is_error
    data = _payload(run)
    assert data["summary"]["runs"] == len(SMOKE) and data["failures"]
    assert "zeta-42" not in json.dumps(data).lower()
    listed = _payload(runs)
    assert listed[0]["run_id"] == data["run_id"]
