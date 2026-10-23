"""Approved imported views and deterministic shot-aware view ordering.

An asset entry identifies one library variant. This module never merges variants,
infers approval from a frozen flag, or promotes a look/action image to identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferenceView:
    path: str
    role: str
    view: str
    framing: str


def confirmed_reference_views(asset: object) -> tuple[ReferenceView, ...]:
    """Read only explicitly confirmed views; frozen alone is not approval."""
    if not isinstance(asset, Mapping):
        return ()
    values = asset.get("reference_views")
    if not isinstance(values, list):
        return ()
    result: list[ReferenceView] = []
    for value in values:
        if not isinstance(value, Mapping) or value.get("confirmed") is not True:
            continue
        path = value.get("path")
        role = value.get("role")
        view = value.get("view", "unknown")
        framing = value.get("framing", "unknown")
        if (
            isinstance(path, str)
            and path
            and role in ("identity", "look", "action", "space")
            and isinstance(view, str)
            and isinstance(framing, str)
        ):
            result.append(ReferenceView(path, role, view, framing))
    return tuple(result)


def _prompt_text(prompt: object) -> str:
    if isinstance(prompt, str):
        return prompt.casefold()
    if isinstance(prompt, Mapping):
        return " ".join(_prompt_text(value) for value in prompt.values())
    return ""


def _shot_preferences(image_prompt: object) -> tuple[str, str]:
    text = _prompt_text(image_prompt)
    view = "front"
    for candidate, words in (
        ("left", ("left profile", "left side", "左侧", "左脸")),
        ("right", ("right profile", "right side", "右侧", "右脸")),
        ("back", ("from behind", "back view", "rear view", "背面", "背影", "背对")),
    ):
        if any(word in text for word in words):
            view = candidate
            break
    framing = (
        "headshot"
        if any(
            word in text for word in ("close-up", "close up", "closeup", "headshot", "portrait", "特写", "近景", "大头")
        )
        else "full_body"
    )
    return view, framing


def ordered_reference_views(views: Sequence[ReferenceView], image_prompt: object) -> tuple[ReferenceView, ...]:
    """Identity anchor first, then shot-relevant appearance and angle support.

    Front headshots anchor identity even for a rear/full-body shot. Secondary
    references favor the requested angle/framing, and action views remain pose
    guidance only. Stable input order breaks ties.
    """
    target_view, target_framing = _shot_preferences(image_prompt)

    def match(view: ReferenceView) -> tuple[bool, bool, bool]:
        return view.framing != target_framing, view.view != target_view, view.view != "front"

    identities = [view for view in views if view.role == "identity"]
    anchor = min(
        identities,
        key=lambda view: (view.framing != "headshot", view.view != "front", *match(view)),
        default=None,
    )
    remaining = [view for view in views if view is not anchor]
    roles = (
        {"look": 0, "identity": 1, "space": 2, "action": 3}
        if target_framing == "full_body"
        else {"identity": 0, "look": 1, "space": 2, "action": 3}
    )
    remaining.sort(key=lambda view: (roles[view.role], *match(view)))
    return ((anchor,) if anchor is not None else ()) + tuple(remaining)


def has_reference_views(asset: object) -> bool:
    """A declared import must not fall back to an unapproved legacy original."""
    return isinstance(asset, Mapping) and bool(asset.get("reference_views"))
