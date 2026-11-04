"""Gera pidreams/ui/assets/face_mesh.json a partir do rosto canônico do MediaPipe (Apache-2.0).

Uso: python -m tests.tools.build_face_mesh caminho/canonical_face_model.obj
O OBJ vem de https://github.com/google-ai-edge/mediapipe (modules/face_geometry/data).
Modificação: vértices arredondados, triângulos e suas arestas únicas; sem textura.
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "pidreams" / "ui" / "assets" / "face_mesh.json"


def main(path):
    vertices, edges, triangles = [], set(), []
    for line in open(path, encoding="utf-8"):
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            vertices.append([round(float(x), 3) for x in parts[1:4]])
        elif parts[0] == "f":
            ids = [int(p.split("/")[0]) - 1 for p in parts[1:]]
            triangles.append(ids)
            for a, b in zip(ids, ids[1:] + ids[:1]):
                edges.add((min(a, b), max(a, b)))
    OUT.write_text(json.dumps({
        "source": "MediaPipe canonical face model (Apache-2.0, Copyright The MediaPipe Authors); "
                  "converted: rounded vertices, triangles and their unique edges, no texture",
        "vertices": vertices, "edges": sorted(edges), "triangles": triangles}, separators=(",", ":")), encoding="utf-8")
    print(f"{len(vertices)} vértices, {len(edges)} arestas → {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
