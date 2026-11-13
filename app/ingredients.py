"""Ingredient names for matching: the word sets Search ranks with, and the key that finds an earlier recipe's match.

words() is the light normalizer Match With Search always had (lowercase words, simple singulars, articles dropped).
key() goes further for From Previous Recipe: quantities, units and preparation words are dropped too, so
"2 cups Chopped fresh Tomatoes, divided" and "tomato" are the same ingredient. Pure functions, no database access.
"""
from __future__ import annotations

import re
from typing import Optional

STOP = {"a", "an", "the", "of", "and", "with", "or"}

# Units that can lead or trail a name when a line was split by hand ("2 cups flour").
UNITS = {"cup", "c", "tbsp", "tablespoon", "tbs", "tsp", "teaspoon", "oz", "ounce", "lb", "pound", "g", "gram", "kg", "kilogram",
         "ml", "milliliter", "l", "liter", "litre", "pt", "pint", "qt", "quart", "gal", "gallon", "floz", "clove", "can", "jar",
         "pinch", "dash", "slice", "piece", "stick", "package", "pkg", "packet", "bunch", "sprig", "handful", "head", "stalk"}
# Preparation, size and state words that do not change which food it is. Words that do (whole, dried, ground, smoked,
# canned, sweet, unsalted, brown, red) stay in the key.
PREP = {"chopped", "diced", "minced", "sliced", "grated", "shredded", "crushed", "cubed", "halved", "quartered", "peeled", "seeded",
        "trimmed", "rinsed", "drained", "mashed", "melted", "softened", "beaten", "sifted", "packed", "divided", "fresh", "freshly",
        "large", "medium", "small", "big", "ripe", "finely", "roughly", "coarsely", "thinly", "thickly", "lightly", "boneless",
        "skinless", "cold", "warm", "hot", "optional", "extra", "about", "approximately", "plus", "more", "taste", "needed",
        "for", "to", "into", "in", "pieces", "piece", "chunk", "chunks", "cut", "room", "temperature", "juiced", "zested"}


def singular(w: str) -> str:
    """Simple singulars: eggs, berries, tomatoes, cloves. Words ending in ss, us or is (hummus, asparagus) stay."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("oes"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def words(text: Optional[str]) -> frozenset:
    """Lowercase word set with light singulars, articles dropped."""
    return frozenset(singular(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP)


def key(text: Optional[str]) -> Optional[str]:
    """The ingredient an imported name stands for, or None when nothing is left. Lowercase, anything in brackets and after the
    first comma dropped (the note), numbers, fractions, units and preparation words dropped, plural to singular, words
    sorted so word order never matters. "2 cups Chopped fresh Tomatoes, divided" and "tomato" both give "tomato"."""
    t = re.sub(r"\([^)]*\)", " ", (text or "").lower()).split(",")[0]
    t = re.sub(r"[¼-¾⅐-⅞]", " ", t)
    out = set()
    for w in re.findall(r"[a-z]+", t):  # digits are never part of a name: "2", "1/2", "250g" lose their numbers
        if w in STOP or w in PREP:
            continue
        s = singular(w)
        if s in UNITS or w in UNITS or s in PREP:
            continue
        out.add(s)
    return " ".join(sorted(out)) or None
