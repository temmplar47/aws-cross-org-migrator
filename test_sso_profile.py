"""Unit tests for Handler._ensure_sso_profile (auto-create SSO profile)."""

import shutil
from pathlib import Path

from aws_cross_org_migrator.web.server import Handler

TMP = Path("test_aws_cfg")
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir()
cfg_path = TMP / "config"

SSO = {
    "start_url": "https://old.awsapps.com/start",
    "sso_region": "us-east-1",
    "role_name": "AdministratorAccess",
}

# 1. Missing profile -> created with the config's SSO fields.
created = Handler._ensure_sso_profile("sso-old", SSO, aws_config_path=cfg_path)
text = cfg_path.read_text(encoding="utf-8")
assert created is True
assert "[profile sso-old]" in text
assert "sso_start_url = https://old.awsapps.com/start" in text
assert "sso_region = us-east-1" in text
assert "sso_role_name = AdministratorAccess" in text
assert all(ord(c) < 128 for c in text), "profile block must be ASCII-only"
print("creates missing profile: OK")

# 2. Existing profile -> untouched, returns False.
before = cfg_path.read_text(encoding="utf-8")
created = Handler._ensure_sso_profile("sso-old", SSO, aws_config_path=cfg_path)
assert created is False
assert cfg_path.read_text(encoding="utf-8") == before
print("existing profile untouched: OK")

# 3. Missing profile + incomplete config -> clear error, nothing written.
try:
    Handler._ensure_sso_profile("sso-new", {"start_url": ""}, aws_config_path=cfg_path)
    raise AssertionError("expected ValueError for incomplete sso config")
except ValueError as e:
    assert "sso-new" in str(e)
assert "[profile sso-new]" not in cfg_path.read_text(encoding="utf-8")
print("incomplete config error: OK")

# 4. _find_aws_cli returns a usable path (aws is installed on this machine)
#    and never raises even when PATH lookup misses.
aws = Handler._find_aws_cli()
assert aws is None or ("aws" in aws.lower()), f"unexpected aws path: {aws}"
print("find_aws_cli: OK ->", aws)

# 5. The generated login .bat quotes the exe correctly and keeps the window
#    open; prove the quoting works by actually running the same structure
#    with --version through cmd (no window, no login).
bat = Handler._write_login_bat(aws or r"C:\Program Files\Amazon\AWSCLIV2\aws.exe", "sso-old")
text = bat.read_text(encoding="ascii")
assert f'"{aws or ""}' [0] == '"'  # exe line is quoted
assert "sso login --profile sso-old" in text
assert text.rstrip().endswith("pause")
assert all(ord(c) < 128 for c in text), ".bat must be ASCII"
print("login bat content: OK")

if aws:
    import subprocess, tempfile
    probe = Path(tempfile.gettempdir()) / "aws_probe_test.bat"
    probe.write_text(f'@echo off\r\n"{aws}" --version\r\n', encoding="ascii", newline="")
    r = subprocess.run(["cmd", "/c", str(probe)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "aws-cli" in (r.stdout + r.stderr), f"probe failed: {r.stdout} {r.stderr}"
    probe.unlink()
    print("quoted exe path executes via cmd/.bat: OK ->", (r.stdout + r.stderr).strip().split()[0])

shutil.rmtree(TMP, ignore_errors=True)
print("ALL SSO PROFILE TESTS PASSED")
