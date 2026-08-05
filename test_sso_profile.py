"""Unit tests for Handler SSO profile create/sync and aws CLI discovery."""

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
status = Handler._ensure_sso_profile("sso-old", SSO, aws_config_path=cfg_path)
text = cfg_path.read_text(encoding="utf-8")
assert status == "created"
assert "[profile sso-old]" in text
assert "sso_start_url = https://old.awsapps.com/start" in text
assert "sso_region = us-east-1" in text
assert "sso_role_name = AdministratorAccess" in text
assert all(ord(c) < 128 for c in text), "profile block must be ASCII-only"
print("creates missing profile: OK")

# 2. Same values again -> unchanged, file untouched.
before = cfg_path.read_text(encoding="utf-8")
status = Handler._ensure_sso_profile("sso-old", SSO, aws_config_path=cfg_path)
assert status == "unchanged"
assert cfg_path.read_text(encoding="utf-8") == before
print("identical values untouched: OK")

# 3. Start URL changed in config.yaml -> profile is SYNCED (the actual bug:
#    aws sso login reads the URL from the profile, not from config.yaml).
cfg_path.write_text(
    "[profile other]\n"
    "region = eu-west-1\n"
    "\n"
    "[profile sso-old]\n"
    "# keep this comment\n"
    "sso_start_url = https://OLD-URL.awsapps.com/start\n"
    "sso_region = us-east-1\n"
    "sso_role_name = AdministratorAccess\n"
    "output = json\n"
    "\n"
    "[profile after]\n"
    "region = ap-northeast-1\n",
    encoding="utf-8",
)
status = Handler._ensure_sso_profile("sso-old", SSO, aws_config_path=cfg_path)
text = cfg_path.read_text(encoding="utf-8")
assert status == "updated", status
assert "sso_start_url = https://old.awsapps.com/start" in text
assert "https://OLD-URL" not in text
assert "# keep this comment" in text, "comments must survive"
assert "output = json" in text, "unrelated keys must survive"
assert "[profile other]" in text and "[profile after]" in text
assert "region = eu-west-1" in text and "region = ap-northeast-1" in text
print("start_url sync (legacy profile): OK")

# 4. sso_session-style profile -> the [sso-session] section is synced.
cfg_path.write_text(
    "[profile sso-old]\n"
    "sso_session = mysess\n"
    "sso_account_id = 111111111111\n"
    "sso_role_name = OldRole\n"
    "\n"
    "[sso-session mysess]\n"
    "sso_start_url = https://OLD-URL.awsapps.com/start\n"
    "sso_region = eu-central-1\n"
    "sso_registration_scopes = sso:account:access\n",
    encoding="utf-8",
)
status = Handler._ensure_sso_profile("sso-old", SSO, aws_config_path=cfg_path)
text = cfg_path.read_text(encoding="utf-8")
assert status == "updated"
assert "sso_start_url = https://old.awsapps.com/start" in text
assert "sso_region = us-east-1" in text
assert "sso_role_name = AdministratorAccess" in text, "role updates in the profile block"
assert "sso_registration_scopes = sso:account:access" in text
assert "sso_account_id = 111111111111" in text
print("start_url sync (sso-session profile): OK")

# 5. Missing profile + incomplete config -> clear error, nothing written.
try:
    Handler._ensure_sso_profile("sso-new", {"start_url": ""}, aws_config_path=cfg_path)
    raise AssertionError("expected ValueError for incomplete sso config")
except ValueError as e:
    assert "sso-new" in str(e)
assert "[profile sso-new]" not in cfg_path.read_text(encoding="utf-8")
print("incomplete config error: OK")

# 6. _find_aws_cli returns a usable path and never raises.
aws = Handler._find_aws_cli()
assert aws is None or ("aws" in aws.lower()), f"unexpected aws path: {aws}"
print("find_aws_cli: OK ->", aws)

# 7. The generated login .bat quotes the exe and ends with pause; prove the
#    quoting works by actually running the same structure with --version.
bat = Handler._write_login_bat(aws or r"C:\Program Files\Amazon\AWSCLIV2\aws.exe", "sso-old")
text = bat.read_text(encoding="ascii")
assert "sso login --profile sso-old" in text
assert text.rstrip().endswith("pause")
assert all(ord(c) < 128 for c in text), ".bat must be ASCII"
print("login bat content: OK")

if aws:
    import subprocess, tempfile
    probe = Path(tempfile.gettempdir()) / "aws_probe_test.bat"
    probe.write_bytes(f'@echo off\r\n"{aws}" --version\r\n'.encode("ascii"))
    r = subprocess.run(["cmd", "/c", str(probe)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "aws-cli" in (r.stdout + r.stderr), f"probe failed: {r.stdout} {r.stderr}"
    probe.unlink()
    print("quoted exe path executes via cmd/.bat: OK ->", (r.stdout + r.stderr).strip().split()[0])

shutil.rmtree(TMP, ignore_errors=True)
print("ALL SSO PROFILE TESTS PASSED")
