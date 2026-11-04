"""Fail when publishable files contain machine paths, personal emails, secrets or private patterns.

Generic rules live here and run in CI. Private rules (client names, personal data) live in a
local file outside every repo: $PUBLISHABLE_PRIVATE_PATTERNS or
~/.config/publishable/private-patterns.txt, one regex per line, '#' for full-line comments
(a ' #' inside a rule line is a configuration error).
A repo may accept known false positives in .publishable-allow: '<regex>  # <justification>'.
An allow regex is applied to the text of each individual match (not to the whole line), so
allowing one address never hides another address on the same line. The .publishable-allow
file itself is scanned only with the 'known-token' and 'private' rules, without allow.

Only the current tree is scanned, not the git history. Exit codes: 0 clean, 1 findings,
2 configuration or usage error.
"""
import codecs
import os
import re
import sys
from pathlib import Path

GENERIC_PATTERNS = {
    "machine-path": re.compile(
        r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+|(?<![\w.-])/home[\\/]+[^\\/\s]+|(?<![\w.-])/Users[\\/]+[^\\/\s]+",
        re.IGNORECASE,
    ),
    "email": re.compile(r"[\w.+-]+@(gmail|hotmail|outlook|yahoo|icloud)\.com", re.IGNORECASE),
    "secret": re.compile(
        r"(api[_-]?key|secret|token|password)['\"]?\s*[:=]\s*(?:"
        r"['\"](?!\$\{|<)[^'\"\s]{8,}"
        r"|(?!\$\{|<)(?=[^'\"\s]*\d)[^'\"\s]{8,}"
        r")",
        re.IGNORECASE,
    ),
    "known-token": re.compile(
        r"gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|sk-ant-[A-Za-z0-9_-]{20,}"
        r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    ),
}
# Skipped at any depth.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache"}
# Skipped only directly under the scan root.
ROOT_SKIP_DIRS = {".publishable-scanner", ".worktrees"}
# The scanner and its tests contain the patterns on purpose; matched by identity, not by name.
SKIP_FILES = {
    Path(__file__).resolve(),
    Path(__file__).resolve().parents[1] / "tests" / "test_check_publishable.py",
}
ALLOW_FILE = ".publishable-allow"
ALLOW_FILE_RULES = ("known-token", "private")
WINDOW = 160
BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def default_private_file():
    env = os.environ.get("PUBLISHABLE_PRIVATE_PATTERNS")
    return Path(env) if env else Path.home() / ".config" / "publishable" / "private-patterns.txt"


def read_config_lines(path):
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as err:
        lineno = data[: err.start].count(b"\n") + 1
        raise ValueError(f"{path}:{lineno}: file is not valid UTF-8") from err


def load_patterns(private_file):
    patterns = dict(GENERIC_PATTERNS)
    if private_file is not None and Path(private_file).is_file():
        compiled = []
        for lineno, line in enumerate(read_config_lines(private_file), start=1):
            rule = line.strip()
            if not rule or rule.startswith("#"):
                continue
            if " #" in rule:
                raise ValueError(f"{private_file}:{lineno}: inline comments are not allowed in private rules")
            try:
                compiled.append(re.compile(rule, re.IGNORECASE))
            except re.error as err:
                raise ValueError(f"{private_file}:{lineno}: invalid regex: {err}") from err
        if compiled:
            try:
                patterns["private"] = re.compile("|".join(f"(?:{c.pattern})" for c in compiled), re.IGNORECASE)
            except re.error as err:
                raise ValueError(f"{private_file}: cannot combine private rules: {err}") from err
    return patterns


def load_allow(root):
    path = Path(root) / ALLOW_FILE
    if not path.is_file():
        return []
    allow = []
    for lineno, line in enumerate(read_config_lines(path), start=1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        regex, sep, reason = line.partition(" #")
        if not sep or not reason.strip():
            raise ValueError(f"{ALLOW_FILE}:{lineno}: missing '# justification'")
        try:
            allow.append(re.compile(regex.strip()))
        except re.error as err:
            raise ValueError(f"{ALLOW_FILE}:{lineno}: invalid regex: {err}") from err
    return allow


def display(line, start):
    """Strip the line; long lines are shown as a window around the match offset."""
    stripped = line.strip()
    if len(stripped) <= WINDOW:
        return stripped
    offset = max(0, start - (len(line) - len(line.lstrip())))
    begin = max(0, offset - 60)
    return stripped[begin : begin + WINDOW]


def scan_text(text, patterns, allow=()):
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in patterns.items():
            for match in pattern.finditer(line):
                if not any(a.search(match.group(0)) for a in allow):
                    hits.append((lineno, name, display(line, match.start())))
                    break
    return hits


def decode(data):
    """Return decoded text, or None when the content is binary."""
    for bom, codec in BOMS:
        if data.startswith(bom):
            try:
                return data.decode(codec)
            except UnicodeDecodeError:
                return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return None


def scan_tree_full(root, patterns, allow):
    """Return (findings, skipped_binary_paths, scanned_file_count)."""
    root = Path(root)
    findings, skipped, scanned = [], [], 0
    allow_patterns = {k: v for k, v in patterns.items() if k in ALLOW_FILE_RULES}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        if rel.parts[0] in ROOT_SKIP_DIRS or path.resolve() in SKIP_FILES:
            continue
        text = decode(path.read_bytes())
        if text is None:
            skipped.append(rel.as_posix())
            continue
        scanned += 1
        if rel.parts == (ALLOW_FILE,):
            hits = scan_text(text, allow_patterns)
        else:
            hits = scan_text(text, patterns, allow)
        findings.extend((rel.as_posix(), lineno, name, line) for lineno, name, line in hits)
    return findings, skipped, scanned


def scan_tree(root, patterns, allow):
    return scan_tree_full(root, patterns, allow)[0]


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError, OSError):
        pass
    root = Path(argv[1]) if len(argv) > 1 else Path(".")
    if not root.is_dir():
        print(f"error: scan root is not a directory: {root}")
        return 2
    try:
        patterns = load_patterns(default_private_file())
    except ValueError as err:
        print(err)
        return 2
    print("private patterns: loaded" if "private" in patterns else "private patterns: none (generic rules only)")
    try:
        allow = load_allow(root)
    except ValueError as err:
        print(err)
        return 2
    findings, skipped, scanned = scan_tree_full(root, patterns, allow)
    if scanned == 0:
        print(f"error: no files were scanned under {root}")
        return 2
    for rel, lineno, name, line in findings:
        print(f"{rel}:{lineno}: [{name}] {line}")
    for rel in skipped:
        print(f"skipped binary: {rel}")
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
