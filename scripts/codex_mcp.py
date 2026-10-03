"""Legacy diagnostic entrypoint; use installed ``rob2 mcp-codex``."""

from rob2_kit.interfaces.mcp.codex import CodexImageContent, main

__all__ = ["CodexImageContent", "main"]

if __name__ == "__main__":
    main()
