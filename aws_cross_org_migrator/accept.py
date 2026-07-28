"""Accept organization invitations AS each target account.

For each target account, this module:
  1. Reads the cached IAM Identity Center (SSO) access token.
  2. Calls ``sso:get_role_credentials`` for that account + role, obtaining a set
     of *temporary* credentials scoped to the target account.
  3. Uses those temporary credentials to call ``organizations:AcceptHandshake``
     **as the target account**, joining the new organization.

This is exactly the "log into the access portal, get temporary creds, accept the
invite for each account" flow the user described.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError

from .sso_cache import get_access_token, SSOCacheError

logger = logging.getLogger(__name__)


@dataclass
class AcceptResult:
    account_id: str
    handshake_id: Optional[str]
    accepted: bool
    error: Optional[str] = None


class HandshakeAcceptor:
    def __init__(
        self,
        start_url: str,
        role_name: str,
        sso_region: str,
        new_mgmt_account_id: str,
        access_token: Optional[str] = None,
        orgs_region: str = "us-east-1",
        poll_interval: int = 10,
        poll_max_attempts: int = 30,
        cache_dir=None,
    ):
        self.start_url = start_url
        self.role_name = role_name
        self.sso_region = sso_region
        self.new_mgmt_account_id = new_mgmt_account_id
        self.access_token = access_token
        self.orgs_region = orgs_region
        self.poll_interval = poll_interval
        self.poll_max_attempts = poll_max_attempts
        self.cache_dir = cache_dir
        self._sso_client = None

    # -- token / sso ----------------------------------------------------------
    def _get_token(self) -> str:
        try:
            return get_access_token(
                start_url=self.start_url,
                access_token=self.access_token,
                cache_dir=self.cache_dir,
            )
        except SSOCacheError as e:
            raise RuntimeError(
                "Could not obtain SSO access token. Ensure the IAM Identity Center "
                "user has logged into the AWS access portal "
                "(`aws sso login --profile <sso-profile>`). " + str(e)
            ) from e

    def _sso(self):
        if self._sso_client is None:
            token = self._get_token()
            # get_role_credentials needs the token only at call time; create a
            # plain client in the SSO region (no long-lived creds required).
            self._sso_client = boto3.client(
                "sso", region_name=self.sso_region,
                aws_access_key_id="", aws_secret_access_key="", aws_session_token="",
            )
            self._access_token = token
        return self._sso_client

    def _role_credentials(self, account_id: str) -> dict:
        """Return temporary creds for `account_id` via the SSO session."""
        sso = self._sso()
        resp = sso.get_role_credentials(
            roleName=self.role_name,
            accountId=account_id,
            accessToken=self._access_token,
        )
        rc = resp["roleCredentials"]
        return {
            "aws_access_key_id": rc["accessKeyId"],
            "aws_secret_access_key": rc["secretAccessKey"],
            "aws_session_token": rc["sessionToken"],
        }

    # -- handshake discovery --------------------------------------------------
    def _find_handshake(self, orgs_client) -> Optional[str]:
        """Locate the INVITE handshake from the new org for this account.

        The ORGANIZATION party of a handshake carries the *organization* id
        (e.g. ``exampleorgid``), not the management account id, so the reliable
        way to confirm the inviter is the handshake ARN, which embeds the
        inviting management account id:
        ``arn:aws:organizations::<mgmt-account-id>:handshake/o-.../invite/h-...``
        """
        paginator = orgs_client.get_paginator("list_handshakes_for_account")
        for page in paginator.paginate():
            for hs in page.get("Handshakes", []):
                if hs.get("State") != "OPEN":
                    continue
                if hs.get("Action") != "INVITE":
                    continue
                arn_parts = hs.get("Arn", "").split(":")
                if len(arn_parts) > 4 and arn_parts[4] == self.new_mgmt_account_id:
                    return hs["Id"]
        return None

    # -- accept ---------------------------------------------------------------
    def accept_one(self, account_id: str, handshake_id: Optional[str] = None) -> AcceptResult:
        try:
            creds = self._role_credentials(account_id)
        except (ClientError, BotoCoreError) as e:
            msg = (
                f"Failed to get SSO role credentials for account {account_id}: {e}. "
                "Verify the IAM Identity Center user is assigned this account+role "
                f"(role '{self.role_name}') and that the role can assume."
            )
            logger.error(msg)
            return AcceptResult(account_id, handshake_id, accepted=False, error=msg)

        orgs = boto3.Session(**creds).client(
            "organizations", region_name=self.orgs_region
        )

        if not handshake_id:
            handshake_id = self._find_handshake(orgs)
        if not handshake_id:
            msg = (
                f"No OPEN INVITE handshake from new org {self.new_mgmt_account_id} "
                f"found for account {account_id}. Ensure the new org already sent the invite."
            )
            logger.warning(msg)
            return AcceptResult(account_id, None, accepted=False, error=msg)

        try:
            resp = orgs.accept_handshake(HandshakeId=handshake_id)
            state = resp["Handshake"].get("State")
            logger.info(
                "Account %s accepted handshake %s (state=%s)",
                account_id, handshake_id, state,
            )
            return AcceptResult(account_id, handshake_id, accepted=True)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "HandshakeStateException":
                # Already transitioning; treat as accepted if it eventually resolves.
                if self._wait_accepted(orgs, handshake_id):
                    return AcceptResult(account_id, handshake_id, accepted=True)
            msg = (
                f"Failed to accept handshake {handshake_id} for account {account_id}: {e}. "
                "The role must allow `organizations:AcceptHandshake`."
            )
            logger.error(msg)
            return AcceptResult(account_id, handshake_id, accepted=False, error=msg)
        except BotoCoreError as e:
            msg = f"Boto error accepting handshake for {account_id}: {e}"
            logger.error(msg)
            return AcceptResult(account_id, handshake_id, accepted=False, error=msg)

    def _wait_accepted(self, orgs_client, handshake_id: str) -> bool:
        for _ in range(self.poll_max_attempts):
            try:
                hs = orgs_client.describe_handshake(HandshakeId=handshake_id)["Handshake"]
                if hs.get("State") in ("ACCEPTED", "DELETED"):
                    return True
            except ClientError:
                # Handshake may have been replaced after account moved.
                return True
            time.sleep(self.poll_interval)
        return False

    def accept_all(self, account_ids: list[str], handshake_map: Optional[dict] = None) -> list[AcceptResult]:
        handshake_map = handshake_map or {}
        return [self.accept_one(a, handshake_map.get(a)) for a in account_ids]
