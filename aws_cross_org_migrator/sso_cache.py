"""Read a cached AWS SSO access token.

When a user runs `aws sso login --profile <sso-profile>`, AWS CLI v2 writes a
JSON blob containing the ``accessToken`` to ``~/.aws/sso/cache/<sha1>.json``.
The blob is either a single object, or an object with an ``accessToken`` field.
This module locates and parses that token so the migration tool can reuse the
IAM Identity Center session instead of re-authenticating interactively.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class SSOCacheError(Exception):
    """Raised when an SSO access token cannot be located or parsed."""


def _cache_dir() -> Path:
    return Path(os.environ.get("AWS_SSO_CACHE_DIR", Path.home() / ".aws" / "sso" / "cache"))


def _sha1_hex(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


@dataclass
class _CacheEntry:
    path: Path
    token: str
    start_url: Optional[str]
    expires_at: Optional[datetime]

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(timezone.utc)


def _parse_expires_at(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_entry(path: Path) -> Optional[_CacheEntry]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    token = data.get("accessToken")
    if not token:
        # Some cache entries store the token under a nested key.
        token = (data.get("accessTokenDetails") or {}).get("accessToken")
    if not token:
        return None
    return _CacheEntry(
        path=path,
        token=token,
        start_url=data.get("startUrl"),
        expires_at=_parse_expires_at(data.get("expiresAt")),
    )


def get_access_token(
    start_url: Optional[str] = None,
    access_token: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> str:
    """Return a valid SSO access token.

    Precedence:
      1. ``access_token`` passed directly (e.g. from config).
      2. The cached token matching ``start_url`` — by filename ``sha1(start_url)``
         or by the ``startUrl`` field inside the cache entry.
      3. The only unexpired token in the cache (single-profile setups). If several
         unexpired tokens exist but none matches ``start_url``, this is ambiguous
         (picking one at random could silently target the wrong Identity Center
         instance), so an error is raised instead.

    Expired tokens are never returned.

    Args:
        start_url: The IAM Identity Center start URL (used to locate the cache file).
        access_token: A token provided directly, bypassing the cache lookup.
        cache_dir: Override for the SSO cache directory (mainly for tests).

    Returns:
        A non-empty SSO access token string.

    Raises:
        SSOCacheError: If no valid token could be found.
    """
    if access_token:
        return access_token

    base = cache_dir or _cache_dir()
    if not base.exists():
        raise SSOCacheError(
            f"SSO cache directory not found: {base}. "
            "Run `aws sso login --profile <sso-profile>` first."
        )

    entries: list[_CacheEntry] = []
    for path in sorted(base.glob("*.json")):
        # `blobs.json` is a legacy index, not a token file.
        if path.name == "blobs.json":
            continue
        entry = _load_entry(path)
        if entry:
            entries.append(entry)

    if start_url:
        hash_name = f"{_sha1_hex(start_url)}.json"
        matches = [
            e for e in entries
            if e.path.name == hash_name or e.start_url == start_url
        ]
        live = [e for e in matches if not e.expired]
        if live:
            return live[0].token
        if matches:
            raise SSOCacheError(
                f"The cached SSO token for {start_url} expired at "
                f"{matches[0].expires_at}. Run `aws sso login --profile "
                "<sso-profile>` to refresh it."
            )

    live = [e for e in entries if not e.expired]
    if not live:
        raise SSOCacheError(
            "No valid SSO access token found in cache "
            f"({len(entries)} expired or unusable). "
            "Run `aws sso login --profile <sso-profile>` first."
        )
    if start_url and len(live) > 1:
        found = ", ".join(str(e.start_url or e.path.name) for e in live)
        raise SSOCacheError(
            f"No cached SSO token matches start URL {start_url}, and multiple "
            f"other tokens exist ({found}) — refusing to guess. Check that "
            "`start_url` in the config matches the URL used for `aws sso login`."
        )
    return live[0].token
