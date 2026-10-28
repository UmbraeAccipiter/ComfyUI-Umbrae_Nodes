# umbrae_nodes/modules/clause/contract.py — umbrae_nodes v0.8.8
# Ported from ComfyUI-WildcardClause (contract.py) to run on the umbrae wildcard
# engine (umbrae_wildcards.py) instead of Impact Pack's. Routes live under
# /umbrae/clause/, the node is UmbraeWildcardClauseExpander, the feedback event
# is umbrae-clause-feedback, so it runs alongside the original package.
"""Canonical Wildcard Clause override field contract (Phase 1)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ENGINE_VERSION = "3.1.0"
SCHEMA_VERSION = "1.0"

SKIP_OVERRIDE_SENTINEL = "\uE002"


@dataclass(frozen=True)
class OverrideField:
    id: str
    kind: str
    group: Literal["scene", "character"]
    label: str
    tooltip: str
    example: str
    order: int
    precedes: tuple[str, ...] = ()


OVERRIDE_FIELDS: tuple[OverrideField, ...] = (
    OverrideField(
        id="wardrobe_override",
        kind="wardrobe",
        group="scene",
        label="Wardrobe",
        tooltip="Replaces the /leaf/…/wardrobe slot in scene composers.",
        example="wearing a white linen shirt and black shorts",
        order=0,
        precedes=("jewelry_override",),
    ),
    OverrideField(
        id="environment_override",
        kind="environment",
        group="scene",
        label="Environment",
        tooltip="Replaces the /leaf/…/environment slot.",
        example="in a misty pine forest with soft undergrowth",
        order=1,
    ),
    OverrideField(
        id="medium_override",
        kind="medium",
        group="scene",
        label="Medium / Opener",
        tooltip=(
            "Replaces the /leaf/.../medium opener (selfie, candid, portrait, illustration, etc.). "
            "Example: An anime-style illustration of"
        ),
        example="An anime-style illustration of",
        order=2,
    ),
    OverrideField(
        id="lighting_override",
        kind="lighting",
        group="scene",
        label="Lighting",
        tooltip="Replaces the /leaf/…/lighting slot.",
        example="soft diffused daylight from the left",
        order=3,
    ),
    OverrideField(
        id="treatment_override",
        kind="treatment",
        group="scene",
        label="Treatment",
        tooltip="Replaces the /leaf/…/treatment slot.",
        example="natural color with fine film grain",
        order=4,
    ),
    OverrideField(
        id="age_override",
        kind="age",
        group="character",
        label="Age",
        tooltip="Replaces /common/age/ atom pools.",
        example="a woman around twenty-five",
        order=5,
    ),
    OverrideField(
        id="hair_override",
        kind="hair",
        group="character",
        label="Hair Style",
        tooltip="Replaces /common/hair/ style pools (not hair-color).",
        example="Her long wavy auburn hair falls loose over her shoulders",
        order=6,
    ),
    OverrideField(
        id="body_override",
        kind="body",
        group="character",
        label="Body Archetype",
        tooltip="Replaces build-female + breast-size + butt-size stack",
        example=(
            "a lithe slender figure with a narrow waist and long legs, "
            "modest breasts, and a rounded backside"
        ),
        order=7,
    ),
    OverrideField(
        id="eye_color_override",
        kind="eye_color",
        group="character",
        label="Eye Color",
        tooltip="Replaces /eye-color/ atom pools.",
        example="green",
        order=8,
    ),
    OverrideField(
        id="nationality_override",
        kind="nationality",
        group="character",
        label="Nationality",
        tooltip="Replaces /nationality/ atom pools.",
        example="japanese",
        order=9,
    ),
    OverrideField(
        id="skin_override",
        kind="skin",
        group="character",
        label="Skin Finish",
        tooltip=(
            "Separate sentence after \"She has …\" — skin finish, not ethnicity skin tone"
        ),
        example="Visible pores and a candid skin finish",
        order=10,
    ),
    OverrideField(
        id="face_override",
        kind="face",
        group="character",
        label="Face Features",
        tooltip="Replaces face-features atom pool",
        example="a soft oval face with full lips",
        order=11,
    ),
    OverrideField(
        id="jewelry_override",
        kind="jewelry",
        group="character",
        label="Jewelry",
        tooltip="Replaces piercing / accessories pools under wardrobe composers.",
        example="with a delicate navel piercing",
        order=12,
    ),
    OverrideField(
        id="skin_tone_override",
        kind="skin_tone",
        group="character",
        label="Skin Tone",
        tooltip="Ethnicity phrase skin tone (/skin-tone/ pools)",
        example="warm olive",
        order=13,
    ),
    OverrideField(
        id="hair_color_override",
        kind="hair_color",
        group="character",
        label="Hair Color",
        tooltip="Hair color palette token in ethnicity phrase",
        example="auburn",
        order=14,
    ),
    OverrideField(
        id="breast_size_override",
        kind="breast_size",
        group="character",
        label="Breast Size",
        tooltip="Breast size phrase in body stack",
        example="modest breasts",
        order=15,
    ),
    OverrideField(
        id="butt_size_override",
        kind="butt_size",
        group="character",
        label="Butt Size",
        tooltip="Butt size phrase in body stack",
        example="a rounded backside",
        order=16,
    ),
)

OVERRIDE_PARAM_TO_KIND: dict[str, str] = {f.id: f.kind for f in OVERRIDE_FIELDS}
OVERRIDE_INPUT_KEYS: tuple[str, ...] = tuple(f.id for f in OVERRIDE_FIELDS)
SCENE_OVERRIDE_KEYS: tuple[str, ...] = tuple(
    f.id for f in OVERRIDE_FIELDS if f.group == "scene"
)
CHARACTER_OVERRIDE_KEYS: tuple[str, ...] = tuple(
    f.id for f in OVERRIDE_FIELDS if f.group == "character"
)
