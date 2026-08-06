"""
Small labeled test set for measuring intent-parsing accuracy. Each entry is
(question, expected QueryIntent fields as a dict -- only fields we actually
care about asserting; anything omitted isn't checked).

Deliberately covers each relationship type at least twice, plus a few
questions with no relationship aspect (plain filtered lookups), since those
are the ones most likely to be silently misclassified as "none".
"""

GOLDEN_SET = [
    (
        "What bars in Indiranagar are near each other?",
        {"category": "bars", "area": "Indiranagar", "relationship": "near_each_other"},
    ),
    (
        "Which cafes in Koramangala are close to one another?",
        {"category": "cafes", "area": "Koramangala", "relationship": "near_each_other"},
    ),
    (
        "What are the top rated S-tier cafes?",
        {"category": "cafes", "tier": "S", "relationship": "none", "sort_by": "rating"},
    ),
    (
        "Show me the best rated breweries",
        {"category": "breweries", "relationship": "none", "sort_by": "rating"},
    ),
    (
        "Which areas are near Koramangala?",
        {"area": "Koramangala", "relationship": "expand_to_adjacent_areas"},
    ),
    (
        "What neighborhoods border Indiranagar?",
        {"area": "Indiranagar", "relationship": "expand_to_adjacent_areas"},
    ),
    (
        "What restaurant do you suggest to visit after eating pizza at 4P's in Indiranagar?",
        {"relationship": "near_reference_place", "reference_place_name": "4P's"},
    ),
    (
        "I'm at Third Wave Coffee, what dessert place is nearby?",
        {"relationship": "near_reference_place", "reference_place_name": "Third Wave Coffee", "category": "dessert shops"},
    ),
    (
        "List cafes in Whitefield",
        {"category": "cafes", "area": "Whitefield", "relationship": "none"},
    ),
    (
        "What A-tier coffee roasters are there in Bengaluru?",
        {"category": "coffee roasters", "tier": "A", "relationship": "none"},
    ),
]
