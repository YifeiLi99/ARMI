"""Private setup provider verification worker."""

from .composition.credential_probe import main

if __name__ == "__main__":
    raise SystemExit(main())
