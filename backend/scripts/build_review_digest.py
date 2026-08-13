"""
Prep step for the famous_for / things_to_try extraction (context doc §8.1,
Specialty node + FAMOUS_FOR edge, and the things_to_try Place property).

Not an extraction script itself -- the extraction is done directly by
reading review text (vocabulary discovery bottom-up, then per-place
tagging), not via an LLM API call. This script just reshapes
normalized_places.json into a plain-text digest (name + area + raw
reviews only, dropping lat/lng/rating/etc.) so that reading is fast and
distraction-free.

Input:  backend/data/normalized_places.json
Output: backend/data/review_digest.txt
"""

import json
from pathlib import Path

IN_PATH = Path(__file__).parent.parent / "data" / "normalized_places.json"
OUT_PATH = Path(__file__).parent.parent / "data" / "review_digest.txt"


def main():
    places = json.loads(IN_PATH.read_text(encoding="utf-8"))

    lines = []
    for p in places:
        lines.append(f"=== {p['name']} | id: {p['id']} | area: {p['area']} ===")
        for i, review in enumerate(p.get("review_texts", []), start=1):
            cleaned = " ".join(review.split())  # collapse newlines/whitespace for compact scanning
            lines.append(f"[{i}] {cleaned}")
        lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(places)} places to {OUT_PATH}")


if __name__ == "__main__":
    main()
