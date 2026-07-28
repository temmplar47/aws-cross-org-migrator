"""Configuration loading and persistent migration state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class NewOrgConfig:
    management_account_profile: str
    management_account_id: str
    target_ou_id: Optional[str] = None
    move_poll_timeout: int = 300


@dataclass
class SSOConfig:
    start_url: str
    sso_region: str
    role_name: str
    access_token: Optional[str] = None
    aws_profile: Optional[str] = None


@dataclass
class Settings:
    region: str = "us-east-1"
    state_file: str = "migration_state.json"
    poll_interval: int = 10
    poll_max_attempts: int = 30


@dataclass
class Config:
    new_org: NewOrgConfig
    sso: SSOConfig
    target_accounts: list[dict] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        new = NewOrgConfig(**data.get("new_organization", {}))
        sso = SSOConfig(**data.get("old_organization_sso", {}))
        settings = Settings(**data.get("settings", {}))
        return cls(
            new_org=new,
            sso=sso,
            target_accounts=data.get("target_accounts", []),
            settings=settings,
        )


class StateStore:
    """Persist per-account handshake ids and accept status."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def get(self, account_id: str) -> dict:
        return self.data.get(account_id, {})

    def set(self, account_id: str, **fields) -> None:
        entry = self.data.setdefault(account_id, {})
        entry.update(fields)
        self.save()

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
