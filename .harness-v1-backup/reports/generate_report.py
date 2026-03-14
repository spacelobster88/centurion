"""Generate the final project report as PDF."""
from fpdf import FPDF
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS = ROOT / ".harness"


def sanitize(text):
    """Replace Unicode characters that Helvetica can't handle."""
    return text.replace("\u2014", "--").replace("\u2013", "-").replace("\u2192", "->").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')

def main():
    tasks = json.loads((HARNESS / "tasks.json").read_text())

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, "Centurion - Final Project Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "AI Agent Orchestration Engine", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 6, "Completed: 2026-03-04", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(8)

    def section(title):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    def text(content):
        pdf.set_font("Helvetica", "", 10)
        pdf.set_x(10)
        pdf.multi_cell(190, 5, sanitize(content))
        pdf.ln(2)

    def bullet(content):
        pdf.set_font("Helvetica", "", 10)
        pdf.set_x(10)
        pdf.multi_cell(190, 5, "  - " + sanitize(content))

    # 1. Overview
    section("1. Project Overview")
    text(
        "Centurion is an AI Agent Orchestration Engine that manages fleets of AI agents "
        "using a Roman military hierarchy. It maps Kubernetes concepts to a Roman metaphor: "
        "Engine=Control Plane, Legion=Namespace, Century=ReplicaSet+HPA, "
        "Legionary=Pod, Optio=Autoscaler, Aquilifer=EventBus."
    )
    text(
        "Tech stack: Python 3.12+, FastAPI, Uvicorn, SQLite (aiosqlite), Anthropic SDK, "
        "MCP (Model Context Protocol), httpx."
    )

    # 2. Timeline
    section("2. Timeline")
    text(
        "Started: 2026-03-03 08:55 UTC\n"
        "Completed: 2026-03-04 06:15 UTC\n"
        "Total tasks: 16 (1 architecture + 13 engineering + 3 QA)\n"
        "All tasks completed with zero blockers."
    )

    # 3. Architecture
    section("3. Architecture Phase (1 task)")
    bullet("arch-1: Core engine architecture and module layout")
    text(
        "Designed hierarchy mapping (Roman/Centurion/K8s), module layout with 6 packages, "
        "resource scheduling with admission control, 3 agent types, 3 running modes."
    )

    # 4. Engineering
    section("4. Engineering Phase (13 tasks)")
    eng_tasks = [t for t in tasks["tasks"] if t["phase"] == "engineering"]
    for t in eng_tasks:
        notes = t.get("notes", "")
        bullet(f"{t['id']}: {t['title']} -- {notes}")
    pdf.ln(2)
    text("Total production code: ~2,726 lines across 18 Python files.")

    # 5. QA
    section("5. QA Phase (3 tasks)")
    bullet("qa-1: Existing test suite -- 87/87 passed (61.60s)")
    bullet("qa-2: MCP tools tests -- 67 new tests, all passing")
    bullet("qa-3: Full regression -- 154/154 passed across 9 files (61.92s)")
    pdf.ln(2)
    text("Total test code: ~1,450+ lines across 9 test files.")

    # 6. Key files
    section("6. Key Files Created")
    key_files = [
        "centurion/core/engine.py -- Centurion orchestrator (140 lines)",
        "centurion/core/century.py -- Agent squads + Optio autoscaler (364 lines)",
        "centurion/core/legion.py -- Deployment groups (159 lines)",
        "centurion/core/legionary.py -- Individual agents (95 lines)",
        "centurion/core/scheduler.py -- K8s admission control (177 lines)",
        "centurion/core/events.py -- EventBus/Aquilifer (82 lines)",
        "centurion/agent_types/ -- 5 files: base, cli, api, shell, registry",
        "centurion/api/router.py -- 17 REST endpoints",
        "centurion/db/ -- SQLite schema (5 tables) + async repository",
        "centurion/mcp/tools.py -- 17 MCP tools (292 lines)",
        "tests/ -- 9 test files, 154 total tests",
    ]
    for f in key_files:
        bullet(f)

    # 7. Issues
    pdf.ln(2)
    section("7. Issues Encountered and Resolved")
    text(
        "1. Missing production deps: httpx and mcp[cli] not in pyproject.toml main "
        "dependencies. Fixed during MCP registration phase."
    )
    text(
        "2. MCP tools tests: 9 minor assertion mismatches (missing params=None kwarg). "
        "Fixed during qa-2. Not a production code bug."
    )
    text("3. No failures in existing 87 tests on first run. Clean codebase.")

    # 8. MCP Registration
    section("8. MCP Server Registration")
    text(
        "Centurion registered in ~/.claude/settings.json as MCP server.\n"
        "17 tools: fleet_status, hardware_status, raise_legion, list_legions, "
        "get_legion, disband_legion, add_century, get_century, scale_century, "
        "remove_century, submit_task, submit_batch, get_task, cancel_task, "
        "list_legionaries, get_legionary, list_agent_types."
    )

    # 9. Recommendations
    section("9. Recommendations")
    bullet("Start Centurion server before using MCP tools")
    bullet("Add integration tests against live FastAPI server")
    bullet("Add CI/CD pipeline (GitHub Actions)")
    bullet("Add authentication/authorization for REST API")
    bullet("Add rate limiting and circuit breakers for agent spawning")
    bullet("Consider Prometheus metrics for monitoring")
    bullet("Consider PostgreSQL adapter for production scale")

    out = HARNESS / "reports" / "final-report.pdf"
    pdf.output(str(out))
    print(f"Report saved to {out}")


if __name__ == "__main__":
    main()
