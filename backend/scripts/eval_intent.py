"""
Measures intent-parsing accuracy against golden_set.py -- the actual
evaluation for "does the LLM get the right user intent", instead of
eyeballing individual runs.

Only checks the fields each golden-set entry actually specifies (partial
expected dicts) -- e.g. a "near_each_other" example doesn't assert on
reference_place_name, since that field is irrelevant to that intent type.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from openai import OpenAI

from golden_set import GOLDEN_SET
from query_intent import build_intent_system_prompt, parse_intent

openai_client = OpenAI()


def main():
    system_prompt = build_intent_system_prompt()

    field_correct: dict[str, int] = {}
    field_total: dict[str, int] = {}
    fully_correct = 0

    for question, expected in GOLDEN_SET:
        actual = parse_intent(openai_client, question, system_prompt=system_prompt).model_dump()

        mismatches = []
        for field, expected_value in expected.items():
            field_total[field] = field_total.get(field, 0) + 1
            actual_value = actual.get(field)
            # case-insensitive compare for string fields -- "4P's" vs "4p's"
            # shouldn't count as a miss
            match = (
                str(actual_value).lower() == str(expected_value).lower()
                if isinstance(expected_value, str)
                else actual_value == expected_value
            )
            if match:
                field_correct[field] = field_correct.get(field, 0) + 1
            else:
                mismatches.append(f"{field}: expected {expected_value!r}, got {actual_value!r}")

        status = "PASS" if not mismatches else "FAIL"
        if not mismatches:
            fully_correct += 1
        print(f"[{status}] {question}")
        for m in mismatches:
            print(f"    {m}")

    print("\n--- Per-field accuracy ---")
    for field in sorted(field_total):
        correct, total = field_correct.get(field, 0), field_total[field]
        print(f"  {field}: {correct}/{total} ({100 * correct / total:.0f}%)")

    print(f"\nFully correct: {fully_correct}/{len(GOLDEN_SET)} ({100 * fully_correct / len(GOLDEN_SET):.0f}%)")


if __name__ == "__main__":
    main()
