"""Confirmation before any tool that changes something.

The first answer wins: a panel button (CONFIRMAR/CANCELAR) or the next spoken/typed message.
Only a short, explicit "sim" confirms; any other speech, CANCELAR or 30 s without an answer
cancel — confirming by mistake something that was not an answer would be the costly error.
"""

import queue
import re
import threading
from typing import Callable

DEADLINE_S = 30.0
_YES = re.compile(r"^(sim|pode|confirma|confirmo|isso)\b", re.IGNORECASE)
_MAX_WORDS = 4

# Queue of the confirmation open right now (one at a time). The panel buttons answer into it;
# outside a confirmation, a late click does not count for the next one.
_OPEN: list[queue.Queue | None] = [None]


def answer(yes: bool) -> None:
    """Panel CONFIRMAR/CANCELAR buttons."""
    pending = _OPEN[0]
    if pending is not None:
        pending.put(yes)


def is_yes(text: str | None) -> bool:
    text = (text or "").strip(" .,!?").strip()
    return bool(_YES.match(text)) and len(text.split()) <= _MAX_WORDS


class Confirmer:
    def __init__(self, ask: Callable[[str], None],
                 hear: Callable[[threading.Event, float], str | None],
                 shutdown: Callable[[], None], deadline_s: float = DEADLINE_S):
        """ask(summary): shows the notice and, in voice mode, speaks the question.
        hear(cancel, deadline): the next spoken or typed message (or None).
        shutdown(): removes the notice from the panel."""
        self._ask, self._listen, self._shutdown, self.deadline_s = ask, hear, shutdown, deadline_s

    def __call__(self, briefing: str) -> bool:
        replies: queue.Queue = queue.Queue()
        cancel = threading.Event()

        def listen():
            speech = self._listen(cancel, self.deadline_s)
            if not cancel.is_set():
                replies.put(is_yes(speech))

        _OPEN[0] = replies
        self._ask(briefing)
        threading.Thread(target=listen, daemon=True).start()
        try:
            return bool(replies.get(timeout=self.deadline_s))
        except queue.Empty:
            return False                   # prazo: cancela
        finally:
            _OPEN[0] = None
            cancel.set()
            self._shutdown()
