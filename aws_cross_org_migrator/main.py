"""Command-line entry point for the cross-org AWS account migration tool.

Typical end-to-end usage
------------------------
1. Configure AWS CLI:
     # New org management account
     aws configure --profile mgmt-new
     # Old org IAM Identity Center user (for login only; creds come from SSO)
     aws configure sso --profile sso-old

2. Fill in config.yaml (copy from config.example.yaml).

3. Send invites from the new org:
     python -m aws_cross_org_migrator invite -c config.yaml

4. Log the old-org Identity Center user into the access portal (produces the
   SSO token this tool reads):
     aws sso login --profile sso-old

5. Accept each invite AS the target account (temp creds via SSO):
     python -m aws_cross_org_migrator accept -c config.yaml

6. (Optional) move accepted accounts into an OU:
     python -m aws_cross_org_migrator move -c config.yaml

Or run the whole thing, pausing for the SSO login between steps:
     python -m aws_cross_org_migrator run -c config.yaml

Or launch the friendly web UI (no extra dependencies):
     python -m aws_cross_org_migrator web -c config.yaml
     # opens http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Config, StateStore
from .invite import Inviter
from .accept import HandshakeAcceptor
from .move import AccountMover
from .sso_cache import get_access_token, SSOCacheError
from .web import run_server


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _account_ids(cfg: Config) -> list[str]:
    return [a["id"] for a in cfg.target_accounts]


def _load(cfg_path: str) -> tuple[Config, StateStore]:
    cp = Path(cfg_path)
    # auto-create from example if missing
    if not cp.exists():
        example = cp.with_name("config.example.yaml")
        if example.exists():
            import shutil
            shutil.copy(example, cp)
            print("\n  [OK] config.yaml not found, copied from config.example.yaml.\n")
        else:
            cp.write_text(
                "new_organization:\n  management_account_profile: mgmt-new\n"
                "  management_account_id: '111111111111'\n"
                "old_organization_sso:\n"
                "  start_url: https://my-old-org.awsapps.com/start\n"
                "  sso_region: ap-southeast-1\n"
                "  role_name: AWSAdministratorAccess\n"
                "target_accounts:\n  - id: '222222222222'\n    email: account@example.com\n"
                "settings:\n  region: us-east-1\n",
                encoding="utf-8",
            )
            print("\n  [OK] config.yaml not found, created default. Edit and re-run.\n")
    cfg = Config.from_file(cfg_path)
    state = StateStore(cfg.settings.state_file)
    return cfg, state


def _require_token(cfg: Config) -> None:
    """Fail fast if the SSO token is not present (user hasn't logged in yet)."""
    try:
        get_access_token(start_url=cfg.sso.start_url, access_token=cfg.sso.access_token)
    except SSOCacheError as e:
        logging.error(
            "SSO access token missing. The old-org IAM Identity Center user must "
            "log into the AWS access portal first:\n"
            "    aws sso login --profile <sso-profile>\n"
            "Details: %s", e,
        )
        sys.exit(2)


def cmd_invite(args) -> int:
    cfg, state = _load(args.config)
    inviter = Inviter(cfg.new_org.management_account_profile, region=cfg.settings.region)
    ids = _account_ids(cfg)
    print(f">> Sending invites for {len(ids)} account(s) from new org...")
    results = inviter.invite_all(ids)
    for acc, hs_id in results.items():
        state.set(acc, handshake_id=hs_id, invited=bool(hs_id))
        print(f"   {acc}: {'invited -> ' + hs_id if hs_id else 'FAILED / already invited'}")
    return 0


def cmd_accept(args) -> int:
    cfg, state = _load(args.config)
    _require_token(cfg)
    acceptor = HandshakeAcceptor(
        start_url=cfg.sso.start_url,
        role_name=cfg.sso.role_name,
        sso_region=cfg.sso.sso_region,
        new_mgmt_account_id=cfg.new_org.management_account_id,
        access_token=cfg.sso.access_token,
        orgs_region=cfg.settings.region,
        poll_interval=cfg.settings.poll_interval,
        poll_max_attempts=cfg.settings.poll_max_attempts,
    )
    ids = _account_ids(cfg)
    print(f">> Accepting invites for {len(ids)} account(s) via SSO temp creds...")
    results = acceptor.accept_all(ids, {a: state.get(a).get("handshake_id") for a in ids})
    for r in results:
        state.set(r.account_id, accepted=r.accepted, accept_error=r.error)
        status = "ACCEPTED" if r.accepted else f"FAILED ({r.error})"
        print(f"   {r.account_id}: {status}")
    return 0 if all(r.accepted for r in results) else 1


def cmd_move(args) -> int:
    cfg, state = _load(args.config)
    if not cfg.new_org.target_ou_id:
        print("!! target_ou_id not set in config; skipping move step.")
        return 0
    mover = AccountMover(
        cfg.new_org.management_account_profile,
        region=cfg.settings.region,
        timeout=cfg.new_org.move_poll_timeout,
    )
    ids = _account_ids(cfg)
    for acc in ids:
        if state.get(acc).get("accepted"):
            ok = mover.move(acc, cfg.new_org.target_ou_id)
            state.set(acc, moved=ok)
            print(f"   {acc}: {'moved' if ok else 'MOVE FAILED'}")
    return 0


def cmd_run(args) -> int:
    cfg, state = _load(args.config)
    # Step 1: invite
    inviter = Inviter(cfg.new_org.management_account_profile, region=cfg.settings.region)
    ids = _account_ids(cfg)
    results = inviter.invite_all(ids)
    for acc, hs_id in results.items():
        state.set(acc, handshake_id=hs_id, invited=bool(hs_id))

    # Step 2: require SSO login, then accept
    print("\n>>> Ensure the old-org IAM Identity Center user is logged into the "
          "AWS access portal (`aws sso login --profile <sso-profile>`) before continuing.")
    _require_token(cfg)
    acceptor = HandshakeAcceptor(
        start_url=cfg.sso.start_url,
        role_name=cfg.sso.role_name,
        sso_region=cfg.sso.sso_region,
        new_mgmt_account_id=cfg.new_org.management_account_id,
        access_token=cfg.sso.access_token,
        orgs_region=cfg.settings.region,
        poll_interval=cfg.settings.poll_interval,
        poll_max_attempts=cfg.settings.poll_max_attempts,
    )
    results = acceptor.accept_all(ids, {a: state.get(a).get("handshake_id") for a in ids})
    for r in results:
        state.set(r.account_id, accepted=r.accepted, accept_error=r.error)
        print(f"   {r.account_id}: {'ACCEPTED' if r.accepted else 'FAILED'}")

    # Step 3: optional move
    if cfg.new_org.target_ou_id:
        mover = AccountMover(
            cfg.new_org.management_account_profile,
            region=cfg.settings.region,
            timeout=cfg.new_org.move_poll_timeout,
        )
        for acc in ids:
            if state.get(acc).get("accepted"):
                ok = mover.move(acc, cfg.new_org.target_ou_id)
                state.set(acc, moved=ok)
    return 0


def cmd_status(args) -> int:
    _, state = _load(args.config)
    print("Account migration state:")
    if not state.data:
        print("  (no recorded state yet)")
    for acc, info in state.data.items():
        print(f"  {acc}: invited={info.get('invited')} accepted={info.get('accepted')} "
              f"moved={info.get('moved')} handshake={info.get('handshake_id')}")
    return 0


def cmd_web(args) -> int:
    run_server(
        config_path=args.config,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default="config.yaml", help="Path to config YAML.")
    common.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")

    p = argparse.ArgumentParser(
        prog="aws_cross_org_migrator",
        parents=[common],
        description="Migrate AWS accounts from an old org to a new org via IAM Identity Center SSO.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("invite", parents=[common], help="Send org invitations from the new org's management account.")
    sub.add_parser("accept", parents=[common], help="Accept invites as each target account via SSO temp creds.")
    sub.add_parser("move", parents=[common], help="Move accepted accounts into the configured OU.")
    sub.add_parser("status", parents=[common], help="Show recorded migration state.")
    sub.add_parser("run", parents=[common], help="Run invite -> (SSO login) -> accept -> move end-to-end.")

    web = sub.add_parser("web", parents=[common], help="Launch the friendly local web UI.")
    web.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    web.add_argument("--port", type=int, default=8787, help="Bind port (default 8787).")
    web.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    handlers = {
        "invite": cmd_invite,
        "accept": cmd_accept,
        "move": cmd_move,
        "status": cmd_status,
        "run": cmd_run,
        "web": cmd_web,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
