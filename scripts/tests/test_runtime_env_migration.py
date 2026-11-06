import pytest

from scripts.migrate_runtime_env import apply, render, values


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_preserves_original_comments_quotes_and_existing_settings_byte_for_byte(newline):
    before = newline.join([
        "# 私有备注，不能丢失", "ENVIRONMENT=dev",
        'SMTP_PASSWORD="one # quoted value" # inline note',
        "# API_WORKERS=9 仅为注释", "API_WORKERS=2 # active value",
        'JWT_SECRET="line1\nline2"', "",
    ]).encode()
    after, added = render(before)
    assert after.startswith(before)
    assert values(after)["SMTP_PASSWORD"] == "one # quoted value"
    assert values(after)["JWT_SECRET"] == "line1\nline2"
    assert values(after)["API_WORKERS"] == "2"
    assert "API_WORKERS" not in added
    assert render(after) == (after, [])
    if newline == "\r\n":
        assert b"\n" not in after[len(before):].replace(b"\r\n", b"")


def test_backup_is_exact_and_result_private(tmp_path):
    path = tmp_path / ".env.dev"
    before = b"# never rewrite this\nENVIRONMENT=dev\nJWT_SECRET=secret\n"
    path.write_bytes(before)
    after, _ = render(before)
    backup = apply(path, before, after, tmp_path / "backups")
    assert backup.read_bytes() == before
    assert path.read_bytes() == after
    assert path.stat().st_mode & 0o777 == 0o600
    assert backup.stat().st_mode & 0o777 == 0o600


def test_production_requires_explicit_origins_and_never_weakens_existing_policy():
    before = b"ENVIRONMENT=prod\n# custom policy\nALLOW_MISSING_ORIGIN=false\n"
    with pytest.raises(ValueError, match="prod-origins"):
        render(before)
    after, added = render(before, prod_origins="https://mobile.example.test,https://admin.example.test")
    assert after.startswith(before)
    assert values(after)["ALLOW_MISSING_ORIGIN"] == "false"
    assert "ALLOW_MISSING_ORIGIN" not in added
    assert values(after)["ALLOW_QUERY_TOKEN"] == "false"


def test_duplicate_keys_and_concurrent_edits_fail_without_overwriting(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        render(b"ENVIRONMENT=dev\nJWT_SECRET=a\nJWT_SECRET=b\n")
    path = tmp_path / ".env.dev"
    before = b"ENVIRONMENT=dev\n"
    after, _ = render(before)
    path.write_bytes(before + b"# concurrent edit\n")
    with pytest.raises(ValueError, match="changed"):
        apply(path, before, after, tmp_path / "backups")
    assert path.read_bytes().endswith(b"# concurrent edit\n")
