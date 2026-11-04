"""The voices the settings offer: the default Pocket TTS voice (downloaded with the install) and the
optional Kokoro ones (downloaded when one is chosen)."""

# Voice name in the settings → its Pocket TTS voice state in pidreams/assets/voices.
# "pocket-baritono" was designed from a text description (a polished, formal baritone) and picked by
# ear on 2026-11-04 over every Kokoro, Supertonic and Pocket preset voice.
POCKET = {"pocket-baritono": "baritono.safetensors"}

# Voice name in the settings → Kokoro voice: one voice id, or a blend {voice id: weight}. Kokoro v1.0
# has three Brazilian Portuguese voices (Alex, Santa, Dora); the others always speak with Portuguese
# pronunciation. Chosen by ear on 2026-11-04: Onyx (an American voice reading Portuguese) and an even
# Alex + Santa blend, both liked with the "forte" assistant effect.
KOKORO = {
    "kokoro-alex": "pm_alex",
    "kokoro-santa": "pm_santa",
    "kokoro-dora": "pf_dora",
    "kokoro-onyx": "am_onyx",
    "kokoro-alex-santa": {"pm_alex": 0.5, "pm_santa": 0.5},
}
DEFAULT = "pocket-baritono"


def choices() -> list[str]:
    return [*POCKET, *KOKORO]


def resolve(name: str) -> str:
    """A voice saved by an older version that no longer exists becomes the default."""
    return name if name in POCKET or name in KOKORO else DEFAULT


def is_kokoro(name: str) -> bool:
    return resolve(name) in KOKORO
