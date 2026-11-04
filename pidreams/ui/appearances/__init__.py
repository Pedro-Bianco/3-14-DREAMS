"""Center-panel appearances: the single catalog of ids and names.

The settings list CATALOG in its order; the `appearance` preference stores the id.
"""

import logging

from pidreams.ui.appearances.brain import BrainCanvas
from pidreams.ui.appearances.core import CoreCanvas
from pidreams.ui.appearances.orb import OrbCanvas
from pidreams.ui.appearances.face import FaceCanvas

log = logging.getLogger(__name__)

DEFAULT = "rosto"

# id → (name in the settings, class, fallback if it fails)
CATALOG = {
    "rosto": ("Rosto", FaceCanvas, "orbe"),
    "nucleo": ("Núcleo de energia (estilo ficção científica)", CoreCanvas, "rosto"),
    "cerebro": ("Cérebro digital", BrainCanvas, "rosto"),
    "orbe": ("Orbe", OrbCanvas, "rosto"),
}


def names() -> dict[str, str]:
    return {id_: name for id_, (name, _, _) in CATALOG.items()}


def max_size(id_: str) -> int:
    return CATALOG.get(id_, CATALOG[DEFAULT])[1].MAX_SIZE


def fallback(id_: str) -> str:
    return CATALOG.get(id_, CATALOG[DEFAULT])[2]


def create(id_: str, parent, size: int, bg: str, on_fail=None):
    """Creates the requested appearance; an unknown id becomes the face. If creating it
    fails, tries the fallback and then the rest of the catalog: the panel is never empty."""
    if id_ not in CATALOG:
        id_ = DEFAULT
    order = [id_, fallback(id_)] + [i for i in CATALOG if i not in (id_, fallback(id_))]
    for attempt in order:
        try:
            appearance = CATALOG[attempt][1](parent, size=size, bg=bg, on_fail=on_fail)
            appearance.id = attempt
            return appearance
        except Exception as e:
            log.warning(f"[Appearance] '{attempt}' did not open ({e!r}); trying the next one")
    raise RuntimeError("nenhuma aparência pôde ser criada")
