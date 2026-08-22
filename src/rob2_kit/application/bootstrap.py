"""Install process-wide hardening hooks at the application boundary."""

from __future__ import annotations

_INSTALLED = False


def install_runtime_hardening() -> None:
    """Install deterministic adapters once without changing canonical models."""

    global _INSTALLED
    if _INSTALLED:
        return

    from . import preflight

    original_suggest = preflight._suggest

    def suggest(
        alias: str, relative: str, media: str
    ) -> tuple[preflight.RoleSuggestion, ...]:
        name = relative.rsplit("/", 1)[-1].casefold()
        administrative = (
            "disclos",
            "conflict",
            "competing",
            "coi",
            "copyright",
            "license",
            "consort-checklist",
            "reporting-checklist",
        )
        if any(token in name for token in administrative):
            return (
                preflight.RoleSuggestion(
                    role="other",
                    rule_id="filename_administrative",
                    observed_facts=(f"media_type={media}",),
                ),
            )
        return original_suggest(alias, relative, media)

    preflight._suggest = suggest

    from .registry_runtime import install_registry_source_hook

    install_registry_source_hook()
    _INSTALLED = True