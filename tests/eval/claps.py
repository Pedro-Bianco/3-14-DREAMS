"""Live evaluation of the two-clap detector (sets RISE and the timings in pidreams/audio/claps.py).

    python -m tests.eval.claps --minutos 30

Part 1: clap twice, 20 times, from different spots in the room (goal: >= 18 detections).
Part 2: normal use — typing, talking, music, doors (goal: <= 1 detection in 30 min).
Prints only the time and the loudness numbers of each detection, and the totals; no audio is kept.
"""

import argparse
import time

from pidreams.audio import claps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutos", type=float, default=30.0)
    parser.add_argument("--microfone", type=int, default=None, help="device index (default: Windows')")
    args = parser.parse_args()

    detections: list[float] = []
    start = time.monotonic()

    def heard():
        detections.append(time.monotonic() - start)
        print(f"  {len(detections):3d}  duas palmas em {detections[-1] / 60:5.1f} min  ({listener.last})", flush=True)

    listener = claps.ClapListener(args.microfone, on_claps=heard, ignore=lambda: False)
    listener.detector.on_snap = lambda peak, room: print(
        f"       batida: pico {peak:.3f}, sala {room:.4f} ({peak / max(room, 1e-6):.0f}x)", flush=True)
    listener.start()
    print(f"Ouvindo por {args.minutos:.0f} min (RISE={claps.RISE}, MIN_LEVEL={claps.MIN_LEVEL}). Ctrl+C encerra.")
    try:
        while time.monotonic() - start < args.minutos * 60:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    print(f"\nTotal: {len(detections)} detecções em {(time.monotonic() - start) / 60:.1f} min")


if __name__ == "__main__":
    main()
