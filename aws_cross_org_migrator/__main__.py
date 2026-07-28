"""Allow `python -m aws_cross_org_migrator ...`."""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
