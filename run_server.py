"""Stable entry point for LM Studio. Launch with this project's virtualenv Python."""

from personal_mcp.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["serve"]))
