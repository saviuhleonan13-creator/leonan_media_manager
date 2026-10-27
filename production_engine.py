"""Production Engine MVP: read-only filename-based media proposal."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEOS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
NAME = re.compile(
    r"^EP(?P<ep>\d{1,3})[_ -]+(?P<kind>IMG|IMAGE|TAKE|T)[_ -]*0?"
    r"(?P<take>[1-8])(?P<tail>.*)$", re.IGNORECASE
)
VERSION = re.compile(r"(?:^|[_ -])V(\d+)(?:\.(\d+))?(?=$|[_ .(-])", re.IGNORECASE)


def parse_filename(filename: str) -> dict | None:
    path = Path(filename)
    ext = path.suffix.lower()
    if ext not in IMAGES | VIDEOS:
        return None
    match = NAME.fullmatch(path.stem)
    if not match:
        return None
    is_image = ext in IMAGES
    if match["kind"].upper() not in ({"IMG", "IMAGE"} if is_image else {"TAKE", "T"}):
        return None
    version_match = VERSION.search(match["tail"])
    version = None
    if version_match:
        version = "V" + version_match[1] + (
            "." + version_match[2] if version_match[2] else ""
        )
    return {
        "episode": f"EP{int(match['ep']):02d}",
        "take": int(match["take"]),
        "type": "image" if is_image else "video",
        "filename": filename,
        "version": version,
    }


def preview(source: Path, episode: str, expected: int = 7) -> dict:
    folder = source.expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("A pasta selecionada nao existe")
    match = re.fullmatch(r"EP0*(\d{1,3})", episode.upper())
    if not match or not 1 <= expected <= 8:
        raise ValueError("Use --episode EP14 e --expected-takes entre 1 e 8")
    code = f"EP{int(match[1]):02d}"
    takes = [
        {"take": n, "images": [], "videos": [], "warnings": [], "review_needed": True}
        for n in range(1, expected + 1)
    ]
    unmatched = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() not in IMAGES | VIDEOS:
            continue
        parsed = parse_filename(path.name)
        if parsed is None:
            unmatched.append(path.name)
            continue
        if parsed["episode"] != code:
            continue
        if parsed["take"] > expected:
            unmatched.append(path.name)
            continue
        row = takes[parsed["take"] - 1]
        field = "images" if parsed["type"] == "image" else "videos"
        row[field].append({"filename": path.name, "version": parsed["version"]})
    for row in takes:
        for field in ("images", "videos"):
            if not row[field]:
                row["warnings"].append(f"Arquivo ausente: {field}")
            if len(row[field]) > 1:
                row["warnings"].append(f"Multiplas versoes de {field}: revisar manualmente")
            if any(item["version"] is None for item in row[field]):
                row["warnings"].append(f"Versao nao confirmada de {field}: nao inventar V1")
    return {
        "mode": "READ_ONLY_PREVIEW",
        "episode": code,
        "source": str(folder),
        "takes": takes,
        "unmatched_media": unmatched,
        "note": "Apenas nomes de arquivos; nenhuma midia ou banco foi modificado.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Proposta de midias sem importacao")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--expected-takes", type=int, default=7)
    args = parser.parse_args()
    try:
        result = preview(args.source, args.episode, args.expected_takes)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
