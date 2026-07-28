"""After acceptance, optionally move the account into a target OU.

This runs from the NEW organization's management account. Acceptance must
complete first, because the account is not yet visible to the new org until
the handshake is ACCEPTED.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger(__name__)


class AccountMover:
    def __init__(self, management_profile: str, region: str = "us-east-1", timeout: int = 300):
        self.client = boto3.Session(profile_name=management_profile).client(
            "organizations", region_name=region
        )
        self.timeout = timeout

    def move(self, account_id: str, ou_id: str) -> bool:
        # Wait until the account appears in the new org.
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self._account_in_org(account_id):
                break
            logger.info("Waiting for account %s to appear in new org...", account_id)
            time.sleep(10)
        else:
            logger.error("Account %s never appeared in new org within timeout.", account_id)
            return False

        try:
            self.client.move_account(
                AccountId=account_id, SourceParentId=self._root_id(), DestinationParentId=ou_id
            )
            logger.info("Moved account %s into OU %s", account_id, ou_id)
            return True
        except (ClientError, BotoCoreError) as e:
            logger.error("Failed to move account %s: %s", account_id, e)
            return False

    def _root_id(self) -> str:
        return self.client.list_roots()["Roots"][0]["Id"]

    def _account_in_org(self, account_id: str) -> bool:
        try:
            self.client.describe_account(AccountId=account_id)
            return True
        except ClientError:
            return False
