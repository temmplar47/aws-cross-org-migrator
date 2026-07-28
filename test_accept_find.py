"""Unit test for HandshakeAcceptor._find_handshake matching logic."""

from aws_cross_org_migrator.accept import HandshakeAcceptor

MGMT_ID = "111111111111"


def handshake(hid, state="OPEN", action="INVITE", mgmt_id=MGMT_ID):
    return {
        "Id": hid,
        "Arn": f"arn:aws:organizations::{mgmt_id}:handshake/o-exampleorgid/invite/{hid}",
        "State": state,
        "Action": action,
        # Note: the ORGANIZATION party id is the org id WITHOUT account id —
        # matching must go through the ARN, never this field.
        "Parties": [
            {"Id": "exampleorgid", "Type": "ORGANIZATION"},
            {"Id": "222222222222", "Type": "ACCOUNT"},
        ],
    }


class StubPaginator:
    def __init__(self, handshakes):
        self._handshakes = handshakes

    def paginate(self):
        yield {"Handshakes": self._handshakes}


class StubOrgsClient:
    def __init__(self, handshakes):
        self._handshakes = handshakes

    def get_paginator(self, name):
        assert name == "list_handshakes_for_account"
        return StubPaginator(self._handshakes)


def acceptor():
    return HandshakeAcceptor(
        start_url="https://example.awsapps.com/start",
        role_name="AdministratorAccess",
        sso_region="us-east-1",
        new_mgmt_account_id=MGMT_ID,
    )


# 1. Finds the OPEN INVITE whose ARN embeds the new mgmt account id.
client = StubOrgsClient([handshake("h-good")])
assert acceptor()._find_handshake(client) == "h-good"
print("finds matching OPEN INVITE: OK")

# 2. Skips non-OPEN and non-INVITE handshakes.
client = StubOrgsClient([
    handshake("h-accepted", state="ACCEPTED"),
    handshake("h-enable", action="ENABLE_ALL_FEATURES"),
    handshake("h-good2"),
])
assert acceptor()._find_handshake(client) == "h-good2"
print("skips non-OPEN / non-INVITE: OK")

# 3. Ignores invites from a different organization (different mgmt account).
client = StubOrgsClient([handshake("h-other-org", mgmt_id="999999999999")])
assert acceptor()._find_handshake(client) is None
print("ignores other org's invite: OK")

# 4. Tolerates a handshake without an Arn field.
hs = handshake("h-noarn")
del hs["Arn"]
client = StubOrgsClient([hs, handshake("h-good3")])
assert acceptor()._find_handshake(client) == "h-good3"
print("tolerates missing Arn: OK")

print("ALL ACCEPT FIND TESTS PASSED")
