"""Smoke test for the web UI: endpoints + SSE streaming + config save."""

import json
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8805"


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=5).read())


def post(path, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=5).read())


def test():
    # config + status
    cfg = get("/api/config")
    assert "new_org" in cfg and "sso" in cfg, "config payload malformed"
    print("config OK:", cfg["new_org"]["management_account_profile"])

    st = get("/api/status")
    assert "accounts" in st, "status payload malformed"
    print("status OK: accounts =", len(st["accounts"]))

    tok = get("/api/token")
    assert "present" in tok
    print("token OK:", tok)

    # sso-login without a configured aws_profile -> friendly error, no window
    r = post("/api/sso-login", {})
    assert not r.get("ok") and r.get("need_profile"), f"unexpected sso-login reply: {r}"
    print("sso-login need_profile OK")

    # save config
    new_cfg = {
        "new_org": {"management_account_profile": "mgmt-new",
                     "management_account_id": "111111111111", "target_ou_id": ""},
        "sso": {"start_url": "https://x.awsapps.com/start", "sso_region": "ap-southeast-1",
                 "role_name": "Admin"},
        "settings": {"region": "us-east-1"},
        "target_accounts": [{"id": "222222222222", "email": "a@b.com"}],
    }
    r = post("/api/config", new_cfg)
    assert r.get("ok"), f"save failed: {r}"
    st2 = get("/api/status")
    assert st2["accounts"][0]["id"] == "222222222222"
    print("save+reload OK:", st2["accounts"][0])

    # SSE: capture events while triggering an action
    events = []

    def reader():
        req = urllib.request.urlopen(BASE + "/api/logs", timeout=10)
        for line in req:
            t = line.decode().rstrip()
            if t.startswith("data: "):
                events.append(json.loads(t[6:]))
            if len(events) >= 8:
                break

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    time.sleep(0.8)
    act = post("/api/action", {"action": "accept"})
    assert act.get("ok"), f"action failed: {act}"
    th.join(8)
    assert events, "no SSE events captured"
    print("SSE OK: captured", len(events), "events; first:", events[0]["level"], events[0]["msg"][:50])

    # one-click clear: accounts + state wiped, then restore config
    time.sleep(1.5)  # let the accept action finish so /api/clear is not busy
    r = post("/api/clear", {})
    assert r.get("ok"), f"clear failed: {r}"
    st3 = get("/api/status")
    assert st3["accounts"] == [], f"accounts not cleared: {st3}"
    cfg3 = get("/api/config")
    assert cfg3["target_accounts"] == [], "config target_accounts not cleared"
    print("clear OK: accounts + state wiped")
    r = post("/api/config", new_cfg)
    assert r.get("ok"), "config restore failed"
    print("config restored after clear")

    print("\nALL WEB TESTS PASSED")


if __name__ == "__main__":
    test()
