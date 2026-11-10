"""JUnit XML export, so any CI system (GitLab, Jenkins, Azure, CircleCI) shows scenario results natively.

One <testsuite> per category, one <testcase> per scenario run. A run that crashed is an <error>;
a run with failed checks is a <failure> listing them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import RunResult
from .redact import redactor

XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def to_xml(results: list[RunResult], name: str = "arl", secrets: list[str] = ()) -> str:
    """Target secrets are replaced with [REDACTED]: CI logs are often public."""
    redact = redactor(list(secrets))

    def clean(text: str) -> str:
        return XML_INVALID.sub("\ufffd", redact(text))  # control characters aren't allowed in XML 1.0
    root = ET.Element("testsuites", name=name, tests=str(len(results)),
                      failures=str(sum(r.error is None and not r.passed for r in results)),
                      errors=str(sum(r.error is not None for r in results)),
                      time=f"{sum(r.latency_s for r in results):.3f}")
    by_cat: dict[str, list[RunResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    for cat, runs in sorted(by_cat.items()):
        suite = ET.SubElement(root, "testsuite", name=cat, tests=str(len(runs)),
                              failures=str(sum(r.error is None and not r.passed for r in runs)),
                              errors=str(sum(r.error is not None for r in runs)),
                              time=f"{sum(r.latency_s for r in runs):.3f}")
        for r in runs:
            case = ET.SubElement(suite, "testcase", classname=f"{name}.{cat}",
                                 name=f"{r.scenario_id}#{r.repeat}", time=f"{r.latency_s:.3f}")
            if r.error is not None:
                ET.SubElement(case, "error", message=clean(r.error[:500]), type="AgentError").text = clean(r.error)
            elif not r.passed:
                failed = [c for c in r.checks if not c.passed]
                el = ET.SubElement(case, "failure", message=clean(", ".join(c.name for c in failed)[:500]),
                                   type="CheckFailed")
                el.text = clean("\n".join(f"{c.name}: {c.detail}" for c in failed) + "\n\n" + "\n".join(
                    f"[{m['role']}] {m['content']}" for m in r.transcript))
    ET.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write(path: str | Path, results: list[RunResult], name: str = "arl", secrets: list[str] = ()) -> None:
    Path(path).write_bytes(to_xml(results, name, secrets).encode("utf-8"))
