#!/usr/bin/env python3
"""
Auto-recognize an AWS account from AK/SK and create the management-account
CLI profile (aws-mgmt-<account_id>) used by aws-cross-org-migrator.

This implements the same "auto-recognition" logic as the web UI's
/api/resolve-credentials endpoint: STS identify -> profile name aws-mgmt-<id>.

Usage:
    python setup_new_org_profile.py <ACCESS_KEY_ID> <SECRET_ACCESS_KEY> [REGION]
"""
import sys
import boto3
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        print("Usage: python setup_new_org_profile.py <AK> <SK> [region]")
        sys.exit(2)

    ak, sk = sys.argv[1], sys.argv[2]
    region = sys.argv[3] if len(sys.argv) > 3 else "us-east-1"

    # 1) STS -> account id (auto-recognition core)
    sts = boto3.client(
        "sts", region_name=region,
        aws_access_key_id=ak, aws_secret_access_key=sk,
    )
    ident = sts.get_caller_identity()
    account_id = ident["Account"]
    arn = ident["Arn"]
    print(f"STS identified account: {account_id}")
    print(f"ARN: {arn}")

    # 2) Org membership / master check
    org_master = False
    org_id = None
    try:
        orgs = boto3.client(
            "organizations", region_name="us-east-1",
            aws_access_key_id=ak, aws_secret_access_key=sk,
        )
        org = orgs.describe_organization()["Organization"]
        org_id = org["Id"]
        org_master = (org["MasterAccountId"] == account_id)
        print(f"Organization: {org_id} (master={org['MasterAccountId']})")
    except Exception as e:
        print(f"Org check skipped: {e}")

    # 3) Profile name = aws-mgmt-<account_id> (matches config.yaml convention)
    profile = f"aws-mgmt-{account_id}"
    print(f"Suggested profile: {profile}")

    # 4) Write to ~/.aws/credentials and ~/.aws/config (no dup sections)
    aws_dir = Path.home() / ".aws"
    aws_dir.mkdir(parents=True, exist_ok=True)
    cred_path = aws_dir / "credentials"
    cfg_path = aws_dir / "config"

    cred_text = cred_path.read_text(encoding="utf-8") if cred_path.exists() else ""
    if f"[{profile}]" not in cred_text:
        with open(cred_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{profile}]\naws_access_key_id = {ak}\naws_secret_access_key = {sk}\n")
        print(f"Wrote [{profile}] to credentials")
    else:
        print(f"[{profile}] already present in credentials")

    cfg_text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    prof_sec = f"[profile {profile}]"
    if prof_sec not in cfg_text:
        with open(cfg_path, "a", encoding="utf-8") as f:
            f.write(f"\n{prof_sec}\nregion = {region}\n")
        print(f"Wrote {prof_sec} to config")
    else:
        print(f"{prof_sec} already present in config")

    # 5) Summary
    print("\n========== SUMMARY ==========")
    print(f"  Profile:       {profile}")
    print(f"  Account ID:    {account_id}")
    print(f"  Is Org Master: {org_master}")
    print(f"  Organization:  {org_id}")
    if not org_master:
        print("  WARNING: account is NOT the organization master account.")
        print("           aws-cross-org-migrator needs the NEW org's management")
        print("           account (MasterAccountId) to invite/accept handshakes.")


if __name__ == "__main__":
    main()
