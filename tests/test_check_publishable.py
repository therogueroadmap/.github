from pathlib import Path

import pytest

from scripts.check_publishable import (
    GENERIC_PATTERNS,
    load_allow,
    load_patterns,
    main,
    scan_text,
    scan_tree,
)


def names(hits):
    return [h[1] for h in hits]


def test_flags_windows_user_path():
    assert names(scan_text("Glob: C:/Users/someone/.claude/skills", GENERIC_PATTERNS)) == ["machine-path"]


def test_flags_unix_home_path():
    assert names(scan_text("see /home/alice/project", GENERIC_PATTERNS)) == ["machine-path"]


def test_accepts_home_relative_path():
    assert scan_text("Glob: ~/.claude/skills/*/SKILL.md", GENERIC_PATTERNS) == []


def test_flags_personal_email_but_not_brand_email():
    assert names(scan_text("mail me at someone@gmail.com", GENERIC_PATTERNS)) == ["email"]
    assert scan_text("contact@therogueroadmap.com", GENERIC_PATTERNS) == []


def test_flags_secret_assignment():
    assert names(scan_text('api_key = "abcd1234efgh5678"', GENERIC_PATTERNS)) == ["secret"]


def test_flags_known_token_format():
    token = "ghp_" + "a" * 36
    assert names(scan_text(f"export GH={token}", GENERIC_PATTERNS)) == ["known-token"]


def test_load_patterns_without_private_file_returns_generic(tmp_path: Path):
    patterns = load_patterns(tmp_path / "missing.txt")
    assert set(patterns) == set(GENERIC_PATTERNS)


def test_load_patterns_reads_private_file_ignoring_comments(tmp_path: Path):
    private = tmp_path / "private-patterns.txt"
    private.write_text("# clients\nAcme Corp\n\nPROJ-\\d+\n", encoding="utf-8")
    patterns = load_patterns(private)
    assert names(scan_text("fixed PROJ-12 for Acme Corp", patterns)) == ["private"]


def test_load_allow_requires_justification(tmp_path: Path):
    (tmp_path / ".publishable-allow").write_text("example@gmail\\.com\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_allow(tmp_path)


def test_allow_drops_matching_findings(tmp_path: Path):
    (tmp_path / ".publishable-allow").write_text(
        "example@gmail\\.com  # placeholder address in docs\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("write to example@gmail.com\n", encoding="utf-8")
    assert scan_tree(tmp_path, GENERIC_PATTERNS, load_allow(tmp_path)) == []


def test_scan_tree_skips_git_scanner_checkout_and_binary_files(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("C:/Users/x/", encoding="utf-8")
    (tmp_path / ".publishable-scanner").mkdir()
    (tmp_path / ".publishable-scanner" / "a.md").write_text("C:/Users/x/", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00C:/Users/x/")
    (tmp_path / "README.md").write_text("clean content", encoding="utf-8")
    assert scan_tree(tmp_path, GENERIC_PATTERNS, []) == []


def test_scan_tree_reports_relative_path_and_line(tmp_path: Path):
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("ok\nsee C:\\Users\\bob\\repo\n", encoding="utf-8")
    assert scan_tree(tmp_path, GENERIC_PATTERNS, []) == [
        ("skills/demo/SKILL.md", 2, "machine-path", "see C:\\Users\\bob\\repo")
    ]


def test_main_exit_codes(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("PUBLISHABLE_PRIVATE_PATTERNS", str(tmp_path / "none.txt"))
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.md").write_text("fine", encoding="utf-8")
    assert main(["prog", str(clean)]) == 0
    assert "0 finding(s)" in capsys.readouterr().out
    (clean / "b.md").write_text("x@gmail.com", encoding="utf-8")
    assert main(["prog", str(clean)]) == 1


# --- hardening tests -------------------------------------------------------------------------

from scripts import check_publishable as cp  # noqa: E402


@pytest.mark.parametrize(
    "text",
    [
        '"C:\\\\Users\\\\someuser\\\\x"',
        "c:\\users\\someuser",
        "/home/john.doe/x",
        "/home/SOMEUSER/x",
        "/Users/john.doe/x",
        "/home/alice",
    ],
)
def test_machine_path_variants(text):
    assert names(scan_text(text, GENERIC_PATTERNS)) == ["machine-path"]


@pytest.mark.parametrize(
    "text",
    [
        '"password": "hunter2hunter2"',
        "password: hunter2hunter2",
        "API_KEY=abcd1234efgh5678",
    ],
)
def test_secret_variants(text):
    assert names(scan_text(text, GENERIC_PATTERNS)) == ["secret"]


@pytest.mark.parametrize(
    "text",
    ['token: "${{ secrets.GH_TOKEN }}"', "password: <your-password>", "password: short"],
)
def test_secret_placeholders_not_flagged(text):
    assert scan_text(text, GENERIC_PATTERNS) == []


def test_tilde_path_still_clean():
    assert scan_text("~/.claude/skills", GENERIC_PATTERNS) == []


@pytest.mark.parametrize(
    "text",
    ["secret: required", "token: optional", "password: changeme", "token: required_value"],
)
def test_secret_unquoted_value_without_digit_not_flagged(text):
    assert scan_text(text, GENERIC_PATTERNS) == []


@pytest.mark.parametrize("text", ['token: "requiredvalue"', 'password: "changemechange"'])
def test_secret_quoted_value_flagged_without_digit(text):
    assert names(scan_text(text, GENERIC_PATTERNS)) == ["secret"]


@pytest.mark.parametrize("text", ["https://x.com/home/page", "https://x.com/Users/page"])
def test_machine_path_not_flagged_inside_host_name(text):
    assert scan_text(text, GENERIC_PATTERNS) == []


@pytest.mark.parametrize("text", ['"/home/alice/x"', "file:///home/alice/x"])
def test_machine_path_flagged_after_quote_or_slash(text):
    assert names(scan_text(text, GENERIC_PATTERNS)) == ["machine-path"]


@pytest.mark.parametrize("codec", ["utf-16", "utf-32"])
def test_scan_tree_decodes_bom_utf16_utf32(tmp_path: Path, codec):
    (tmp_path / "a.txt").write_bytes("mail x@gmail.com".encode(codec))
    found = scan_tree(tmp_path, GENERIC_PATTERNS, [])
    assert [f[2] for f in found] == ["email"]


def test_scan_tree_falls_back_to_cp1252(tmp_path: Path):
    (tmp_path / "a.txt").write_bytes("caf\xe9 x@gmail.com".encode("cp1252"))
    assert [f[2] for f in scan_tree(tmp_path, GENERIC_PATTERNS, [])] == ["email"]


def test_main_lists_skipped_binary_before_final_line(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("PUBLISHABLE_PRIVATE_PATTERNS", str(tmp_path / "none.txt"))
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.md").write_text("fine", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x01")
    assert main(["prog", str(root)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert "skipped binary: logo.png" in lines
    assert lines[-1] == "0 finding(s)"


def test_main_missing_root_returns_2(tmp_path: Path, capsys):
    assert main(["prog", str(tmp_path / "nope")]) == 2
    assert capsys.readouterr().out.strip()


def test_main_no_files_scanned_returns_2(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["prog", str(empty)]) == 2


def test_homonymous_scanner_file_in_other_tree_is_scanned(tmp_path: Path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_publishable.py").write_text("C:/Users/x/", encoding="utf-8")
    assert [f[2] for f in scan_tree(tmp_path, GENERIC_PATTERNS, [])] == ["machine-path"]


def test_own_scanner_and_test_files_are_skipped():
    root = Path(cp.__file__).resolve().parents[1]
    found = scan_tree(root, GENERIC_PATTERNS, [])
    assert not [f for f in found if f[0] in ("scripts/check_publishable.py", "tests/test_check_publishable.py")]


def test_allow_file_scanned_only_for_tokens_and_private(tmp_path: Path):
    token = "ghp_" + "a" * 36
    (tmp_path / ".publishable-allow").write_text(
        f"C:/Users/x  # path placeholder\nfoo@gmail\\.com  # mail\n{token}  # oops\n", encoding="utf-8"
    )
    found = scan_tree(tmp_path, GENERIC_PATTERNS, load_allow(tmp_path))
    assert [(f[0], f[2]) for f in found] == [(".publishable-allow", "known-token")]


def test_allow_file_scanned_with_private_rule(tmp_path: Path):
    (tmp_path / ".publishable-allow").write_text("Acme  # client\n", encoding="utf-8")
    patterns = dict(GENERIC_PATTERNS)
    patterns["private"] = __import__("re").compile("Acme", 2)
    found = scan_tree(tmp_path, patterns, [])
    assert [f[2] for f in found] == ["private"]


def test_root_only_skip_dirs(tmp_path: Path):
    (tmp_path / ".worktrees").mkdir()
    (tmp_path / ".worktrees" / "a.md").write_text("C:/Users/x/", encoding="utf-8")
    (tmp_path / "sub" / ".worktrees").mkdir(parents=True)
    (tmp_path / "sub" / ".worktrees" / "b.md").write_text("C:/Users/x/", encoding="utf-8")
    (tmp_path / "sub" / ".publishable-scanner").mkdir()
    (tmp_path / "sub" / ".publishable-scanner" / "c.md").write_text("C:/Users/x/", encoding="utf-8")
    (tmp_path / "sub" / "node_modules").mkdir()
    (tmp_path / "sub" / "node_modules" / "d.md").write_text("C:/Users/x/", encoding="utf-8")
    found = scan_tree(tmp_path, GENERIC_PATTERNS, [])
    assert sorted(f[0] for f in found) == ["sub/.publishable-scanner/c.md", "sub/.worktrees/b.md"]


def test_allow_applies_to_match_not_line(tmp_path: Path):
    allow = [__import__("re").compile(r"example@gmail\.com")]
    hits = scan_text("example@gmail.com real@gmail.com", GENERIC_PATTERNS, allow)
    assert names(hits) == ["email"]
    assert "real@gmail.com" in hits[0][2]
    assert scan_text("example@gmail.com only", GENERIC_PATTERNS, allow) == []


def test_rule_reported_once_per_line():
    assert names(scan_text("a@gmail.com b@gmail.com", GENERIC_PATTERNS)) == ["email"]


def test_long_line_window_around_match():
    line = "x" * 400 + " leak@gmail.com " + "y" * 400
    hits = scan_text(line, GENERIC_PATTERNS)
    assert len(hits[0][2]) <= 160
    assert "leak@gmail.com" in hits[0][2]


def test_short_line_shown_whole_stripped():
    assert scan_text("   a@gmail.com  ", GENERIC_PATTERNS)[0][2] == "a@gmail.com"


def test_private_file_with_bom_is_read(tmp_path: Path):
    private = tmp_path / "p.txt"
    private.write_bytes(b"\xef\xbb\xbfAcme Corp\n")
    assert names(scan_text("Acme Corp", load_patterns(private))) == ["private"]


def test_invalid_private_regex_reports_file_and_line(tmp_path: Path):
    private = tmp_path / "p.txt"
    private.write_text("ok\n(unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"p\.txt:2"):
        load_patterns(private)


def test_private_inline_comment_is_config_error(tmp_path: Path):
    private = tmp_path / "p.txt"
    private.write_text("Acme  # client\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"p\.txt:1"):
        load_patterns(private)


def test_undecodable_private_file_is_config_error(tmp_path: Path):
    private = tmp_path / "p.txt"
    private.write_bytes(b"ok\n\xff\xfe\xfa\n")
    with pytest.raises(ValueError, match=r"p\.txt"):
        load_patterns(private)


def test_invalid_allow_regex_reports_line(tmp_path: Path):
    (tmp_path / ".publishable-allow").write_text("(bad  # why\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.publishable-allow:1"):
        load_allow(tmp_path)


def test_main_config_errors_exit_2(tmp_path: Path, monkeypatch, capsys):
    private = tmp_path / "p.txt"
    private.write_text("(unclosed\n", encoding="utf-8")
    monkeypatch.setenv("PUBLISHABLE_PRIVATE_PATTERNS", str(private))
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.md").write_text("fine", encoding="utf-8")
    assert main(["prog", str(root)]) == 2
    assert "p.txt:1" in capsys.readouterr().out
    monkeypatch.setenv("PUBLISHABLE_PRIVATE_PATTERNS", str(tmp_path / "none.txt"))
    (root / ".publishable-allow").write_text("(bad  # why\n", encoding="utf-8")
    assert main(["prog", str(root)]) == 2
