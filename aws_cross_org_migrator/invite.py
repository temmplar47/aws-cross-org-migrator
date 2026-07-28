"""Send organization invitations from the NEW organization's management account.

Uses ``organizations:InviteAccountToOrganization`` to invite each target account
into the new organization. The resulting handshake must later be accepted by the
target account itself (see ``accept.py``).
"""

from __future__ import annotations

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger(__name__)


class Inviter:
    def __init__(self, management_profile: str, region: str = "us-east-1"):
        self.client = boto3.Session(profile_name=management_profile).client(
            "organizations", region_name=region
        )

    def invite(self, target_account_id: str) -> Optional[str]:
        """Invite a single account to the organization.

        Returns the handshake id on success, or ``None`` on failure / already invited.
        """
        try:
            resp = self.client.invite_account_to_organization(
                Target={"Type": "ACCOUNT", "Id": target_account_id}
            )
            handshake = resp["Handshake"]
            handshake_id = handshake["Id"]
            logger.info(
                "Invited account %s -> handshake %s (state=%s)",
                target_account_id,
                handshake_id,
                handshake.get("State"),
            )
            return handshake_id
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("HandshakeConstraintViolationException", "DuplicateHandshakeException"):
                logger.warning(
                    "Account %s already has a pending/active handshake (invite already sent): %s",
                    target_account_id,
                    e,
                )
            elif code == "AccountAlreadyRegisteredException":
                logger.warning("Account %s is already in this organization.", target_account_id)
            else:
                logger.error("Failed to invite account %s: %s", target_account_id, e)
            return None
        except BotoCoreError as e:
            logger.error("Boto error inviting account %s: %s", target_account_id, e)
            return None

    def invite_all(self, account_ids: list[str]) -> dict[str, Optional[str]]:
        return {acc: self.invite(acc) for acc in account_ids}
