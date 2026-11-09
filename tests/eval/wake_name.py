"""Live measurement of how Whisper writes the assistant's name at the start of a sentence, with and
without the hotwords hint (sets PI_VARIANTS and the hint in pidreams/agent/wake_name.py).

    python -m tests.eval.wake_name --falas 50

Say the phrases of the script (half starting with "PI, ...", half without the name), one at a time.
Each speech is transcribed twice from the same audio (no hint / hint), which stays in memory and is
dropped; only the text is printed. The microphone keeps recording while the previous speech is
transcribed, so a quick next phrase is not cut (the first run lost 5 starts that way).
"""

import argparse
import asyncio

from pidreams.agent.wake_name import hotwords, strip_name
from pidreams.audio.recorder import AudioRecorder
from pidreams.stt.transcriber import Transcriber


async def main(count: int) -> None:
    recorder, transcriber = AudioRecorder(), Transcriber()
    await recorder.calibrate()
    hint = hotwords("PI dreams")
    totals = {"sem dica": 0, "com dica": 0}
    pending: list[asyncio.Task] = []

    def both(audio, n):
        plain, hinted = transcriber.transcribe(audio), transcriber.transcribe(audio, hotwords=hint)
        if not (plain or hinted):
            return
        marks = []
        for label, text in (("sem dica", plain), ("com dica", hinted)):
            called = bool(text) and strip_name(text, "PI dreams") is not None
            totals[label] += called
            marks.append(f"{'CHAMOU ' if called else 'ignorou'} {text!r}")
        print(f"{n:2d} sem dica: {marks[0]}\n   com dica: {marks[1]}", flush=True)

    print(f"Pronto. Fale até {count} frases, uma por vez.", flush=True)
    for n in range(1, count + 1):
        audio = await recorder.record_until_silence()
        pending.append(asyncio.create_task(asyncio.to_thread(both, audio, n)))
    await asyncio.gather(*pending)
    print(f"\nChamadas reconhecidas: sem dica {totals['sem dica']}, com dica {totals['com dica']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--falas", type=int, default=50)
    asyncio.run(main(parser.parse_args().falas))
