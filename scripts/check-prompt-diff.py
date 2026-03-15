#!/usr/bin/env python3
"""Static diff scanner for prompt-related security issues.

Scans git diff output for suspicious patterns that may indicate prompt
injection, role override attempts, encoded payloads, or other prompt
security concerns.

Usage:
    python scripts/check-prompt-diff.py

Exit codes:
    0 - No high-severity issues (warnings may still be present)
    1 - High-severity issues found
    2 - Script error
"""

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Files to scan in the diff
PROMPT_FILE_PATTERNS = [
    "centurion/skill.py",
    "centurion/agent_types/claude_api.py",
    "*prompt*",
    "*instruction*",
    "*system_prompt*",
    "docs/**/*.md",
]

# Git diff path filters (passed to git diff -- <paths>)
DIFF_PATHS = [
    "centurion/skill.py",
    "centurion/agent_types/claude_api.py",
    "**/*prompt*",
    "**/*instruction*",
    "**/*system_prompt*",
    "docs/",
]


@dataclass
class Finding:
    file: str
    pattern: str
    severity: str  # "high", "medium", "low"
    detail: str
    line: int = 0

    def to_dict(self) -> dict:
        d = {"file": self.file, "pattern": self.pattern,
             "severity": self.severity, "detail": self.detail}
        if self.line:
            d["line"] = self.line
        return d


@dataclass
class ScanStats:
    files_scanned: int = 0
    lines_changed: int = 0


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Role override / injection attempts
ROLE_OVERRIDE_PATTERNS = [
    # "ignore previous/all/above instructions" and variants
    (re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above|earlier|preceding)\s+"
        r"(instructions|directives|prompts|rules|guidelines)",
        re.IGNORECASE,
    ), "Role override: ignore-previous-instructions"),
    # "you are now ...", "act as ...", "pretend you are ..."
    (re.compile(
        r"(?:you\s+are\s+now|act\s+as|pretend\s+(?:you\s+are|to\s+be)|"
        r"assume\s+the\s+role\s+of|switch\s+to\s+(?:being|role))",
        re.IGNORECASE,
    ), "Role override: role-switch attempt"),
    # Bare "system:" at start of a line in added content
    (re.compile(r"^system\s*:", re.IGNORECASE | re.MULTILINE),
     "Role override: raw system-role tag"),
    # "new instructions:" / "updated instructions:"
    (re.compile(
        r"(?:new|updated|revised|override)\s+instructions\s*:",
        re.IGNORECASE,
    ), "Role override: instruction replacement"),
]

# Encoded / obfuscated payloads
ENCODED_PAYLOAD_PATTERNS = [
    # Base64 blobs (40+ chars of base64 alphabet, padded)
    (re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
     "Encoded payload: possible base64 blob"),
    # Hex escape sequences (\x41\x42 ...)
    (re.compile(r"(?:\\x[0-9a-fA-F]{2}){4,}"),
     "Encoded payload: hex escape sequence"),
    # Unicode escapes (\u0041 ...)
    (re.compile(r"(?:\\u[0-9a-fA-F]{4}){4,}"),
     "Encoded payload: unicode escape sequence"),
]

# Delimiter manipulation
DELIMITER_PATTERNS = [
    # Triple backticks immediately followed by "system", "user", "assistant"
    (re.compile(r"```\s*(?:system|user|assistant)", re.IGNORECASE),
     "Delimiter manipulation: code-fence role injection"),
    # XML-style tags that look like role boundaries
    (re.compile(
        r"<\s*/?\s*(?:system|user|assistant|instruction|prompt)\s*>",
        re.IGNORECASE,
    ), "Delimiter manipulation: XML role tag"),
]

# Unusual control characters (outside normal whitespace)
CONTROL_CHAR_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)

# Minimum added-line count increase to flag prompt length regression.
# Only flag if a single file gains more than this many net added lines
# that look like prompt/instruction content.
PROMPT_LENGTH_REGRESSION_THRESHOLD = 80


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------

def get_diff() -> str:
    """Get the git diff of prompt-related files against origin/main."""
    cmd = ["git", "diff", "origin/main...HEAD", "--unified=0", "--"] + DIFF_PATHS
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: try without the triple-dot (e.g. shallow clone)
        cmd_fallback = ["git", "diff", "origin/main", "HEAD",
                        "--unified=0", "--"] + DIFF_PATHS
        result = subprocess.run(cmd_fallback, capture_output=True, text=True)
    return result.stdout


def parse_diff(raw_diff: str) -> dict[str, list[tuple[int, str]]]:
    """Parse unified diff into {filename: [(line_no, added_line), ...]}."""
    files: dict[str, list[tuple[int, str]]] = {}
    current_file = None
    current_line = 0

    for line in raw_diff.splitlines():
        # New file header
        if line.startswith("+++ b/"):
            current_file = line[6:]
            if current_file not in files:
                files[current_file] = []
        # Hunk header
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            if match:
                current_line = int(match.group(1))
        # Added line
        elif line.startswith("+") and not line.startswith("+++"):
            if current_file is not None:
                files[current_file].append((current_line, line[1:]))
            current_line += 1
        elif not line.startswith("-") and not line.startswith("\\"):
            current_line += 1

    return files


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_line(file: str, line_no: int, text: str) -> list[Finding]:
    """Scan a single added line for suspicious patterns."""
    findings: list[Finding] = []

    # Role overrides (high severity)
    for pattern, label in ROLE_OVERRIDE_PATTERNS:
        if pattern.search(text):
            findings.append(Finding(
                file=file, pattern=label, severity="high",
                detail=_truncate(text), line=line_no,
            ))

    # Encoded payloads (medium severity)
    for pattern, label in ENCODED_PAYLOAD_PATTERNS:
        if pattern.search(text):
            # Skip common false positives: URLs, import paths, hashes in
            # lock files, standard base64 that is clearly a hash/checksum.
            if _is_likely_false_positive_encoding(text):
                continue
            findings.append(Finding(
                file=file, pattern=label, severity="medium",
                detail=_truncate(text), line=line_no,
            ))

    # Delimiter manipulation (high severity)
    for pattern, label in DELIMITER_PATTERNS:
        if pattern.search(text):
            findings.append(Finding(
                file=file, pattern=label, severity="high",
                detail=_truncate(text), line=line_no,
            ))

    # Control characters (medium severity)
    if CONTROL_CHAR_PATTERN.search(text):
        findings.append(Finding(
            file=file, pattern="Unusual control characters",
            severity="medium",
            detail=f"Control character found in added line",
            line=line_no,
        ))

    return findings


def check_length_regression(
    files: dict[str, list[tuple[int, str]]],
) -> list[Finding]:
    """Flag files where the prompt content grew significantly."""
    findings: list[Finding] = []
    for file, lines in files.items():
        if len(lines) > PROMPT_LENGTH_REGRESSION_THRESHOLD:
            findings.append(Finding(
                file=file,
                pattern="Prompt length regression",
                severity="low",
                detail=(
                    f"{len(lines)} lines added — review for unintended "
                    f"prompt size increase (threshold: "
                    f"{PROMPT_LENGTH_REGRESSION_THRESHOLD})"
                ),
            ))
    return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 120) -> str:
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _is_likely_false_positive_encoding(text: str) -> bool:
    """Heuristic to skip common base64-like strings that are not payloads."""
    stripped = text.strip()
    # URLs often have long base64-ish segments
    if re.match(r"https?://", stripped):
        return True
    # Python import / from statements
    if re.match(r"(?:from|import)\s+", stripped):
        return True
    # Looks like a hash (sha256, etc.) — exactly 64 hex chars
    if re.fullmatch(r"[a-fA-F0-9]{64}", stripped):
        return True
    # Lines that are purely a variable assignment to a hash-like value
    if re.match(r"\w+\s*=\s*['\"][a-fA-F0-9+/=]{40,}['\"]", stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        raw_diff = get_diff()
    except FileNotFoundError:
        print(json.dumps({
            "error": "git not found — cannot compute diff",
            "findings": [],
            "severity": "error",
        }))
        return 2

    if not raw_diff.strip():
        report = {
            "findings": [],
            "severity": "none",
            "stats": {"files_scanned": 0, "lines_changed": 0},
        }
        print(json.dumps(report, indent=2))
        return 0

    files = parse_diff(raw_diff)
    findings: list[Finding] = []

    total_lines = 0
    for file, lines in files.items():
        total_lines += len(lines)
        for line_no, text in lines:
            findings.extend(scan_line(file, line_no, text))

    # Length regression check
    findings.extend(check_length_regression(files))

    # Deduplicate findings (same file + pattern + line)
    seen = set()
    unique: list[Finding] = []
    for f in findings:
        key = (f.file, f.pattern, f.line)
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # Determine overall severity
    severities = {f.severity for f in unique}
    if "high" in severities:
        overall = "high"
    elif "medium" in severities:
        overall = "medium"
    elif "low" in severities:
        overall = "low"
    else:
        overall = "none"

    report = {
        "findings": [f.to_dict() for f in unique],
        "severity": overall,
        "stats": {
            "files_scanned": len(files),
            "lines_changed": total_lines,
        },
    }

    print(json.dumps(report, indent=2))

    return 1 if overall == "high" else 0


if __name__ == "__main__":
    sys.exit(main())
