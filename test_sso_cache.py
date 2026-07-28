import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aws_cross_org_migrator.sso_cache import get_access_token, SSOCacheError

CACHE = Path("test_cache")


def reset():
    shutil.rmtree(CACHE, ignore_errors=True)
    CACHE.mkdir()


def write_entry(name: str, token: str, start_url: str = None, expires_in_hours: float = None):
    data = {"accessToken": token}
    if start_url:
        data["startUrl"] = start_url
    if expires_in_hours is not None:
        exp = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        data["expiresAt"] = exp.strftime("%Y-%m-%dT%H:%M:%SZ")
    (CACHE / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


start = "https://old.awsapps.com/start"
sha = hashlib.sha1(start.encode()).hexdigest()

# 1. Found by sha1(start_url) filename.
reset()
write_entry(sha, "TESTTOKEN123")
assert get_access_token(start_url=start, cache_dir=CACHE) == "TESTTOKEN123"
print("found by start_url hash: OK")

# 2. Direct token bypasses the cache.
assert get_access_token(access_token="DIRECT", cache_dir=CACHE) == "DIRECT"
print("found by direct token: OK")

# 3. Found by startUrl field when the filename hash differs.
reset()
write_entry("aaaa-other-name", "FIELDTOKEN", start_url=start, expires_in_hours=8)
write_entry("bbbb-wrong-org", "WRONGORG", start_url="https://new.awsapps.com/start", expires_in_hours=8)
assert get_access_token(start_url=start, cache_dir=CACHE) == "FIELDTOKEN"
print("found by startUrl field: OK")

# 4. Expired matching token -> clear error, never falls back to another org's token.
reset()
write_entry(sha, "EXPIRED", start_url=start, expires_in_hours=-1)
write_entry("bbbb-wrong-org", "WRONGORG", start_url="https://new.awsapps.com/start", expires_in_hours=8)
try:
    get_access_token(start_url=start, cache_dir=CACHE)
    raise AssertionError("expected SSOCacheError for expired token")
except SSOCacheError as e:
    assert "expired" in str(e)
print("expired matching token error: OK")

# 5. No match but exactly one live token -> single-profile fallback.
reset()
write_entry("cccc-only", "ONLYTOKEN", start_url="https://other.awsapps.com/start", expires_in_hours=8)
assert get_access_token(start_url=start, cache_dir=CACHE) == "ONLYTOKEN"
print("single-token fallback: OK")

# 6. No match and multiple live tokens -> ambiguous, refuse to guess.
reset()
write_entry("cccc-one", "TOK1", start_url="https://one.awsapps.com/start", expires_in_hours=8)
write_entry("dddd-two", "TOK2", start_url="https://two.awsapps.com/start", expires_in_hours=8)
try:
    get_access_token(start_url=start, cache_dir=CACHE)
    raise AssertionError("expected SSOCacheError for ambiguous tokens")
except SSOCacheError as e:
    assert "refusing to guess" in str(e)
print("ambiguous-token error: OK")

# 7. Empty/expired-only cache -> error.
reset()
write_entry("eeee-old", "STALE", start_url=start.replace("old", "misc"), expires_in_hours=-2)
try:
    get_access_token(start_url=None, cache_dir=CACHE)
    raise AssertionError("expected SSOCacheError for expired-only cache")
except SSOCacheError:
    pass
try:
    get_access_token(start_url="nope", cache_dir=Path("empty_cache_does_not_exist"))
    raise AssertionError("expected SSOCacheError for missing cache dir")
except SSOCacheError:
    pass
print("missing/expired token error paths: OK")

shutil.rmtree(CACHE, ignore_errors=True)
print("ALL SSO CACHE TESTS PASSED")
