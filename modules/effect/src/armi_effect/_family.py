"""Derived effect classification; see DESIGN.md for stored effect facts."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EffectFamily:
    capability_kind: str
    operation_class: str
    purpose: str


_FAMILIES = {
    "creator_response": EffectFamily(
        "creator.scene.reply", "send", "respond_to_creator"
    ),
    "local_inbox_delivery": EffectFamily(
        "local.other-human-inbox.deliver", "send", "respond_to_other_human"
    ),
    "external_group_delivery": EffectFamily(
        "external.group.message.send", "send", "respond_to_other_human"
    ),
    "external_private_delivery": EffectFamily(
        "external.private.message.send", "send", "respond_to_other_human"
    ),
    "codex_delegation": EffectFamily(
        "codex.delegated-work", "execute", "delegate_codex_work"
    ),
}


def effect_family(effect_kind: str) -> EffectFamily:
    return _FAMILIES[effect_kind]
