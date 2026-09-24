"""Normalize first, reject impersonation/profanity, then supply plain isolated text."""

import re
import unicodedata

BANNED_PHRASES = ("guaranteed", "sure thing", "easy money", "can't lose")
BLOCKED_WORDS = frozenset({"fuck", "shit", "bitch", "cunt", "nigger", "nigga", "faggot"})
IMPERSONATORS = ("oracle", "exness", "moderator", "admin", "officialsupport")


def normalized(text: str, limit: int = 180) -> str:
    text = unicodedata.normalize("NFKC", text)
    return " ".join(
        "".join(
            c for c in text if unicodedata.category(c) not in {"Cc", "Cf", "Cs"} or c == "\u200d"
        ).split()
    )[:limit]


def safe_text(text: str) -> bool:
    value = normalized(text).casefold().replace("’", "'")
    compact = re.sub(r"[^a-z]", "", value.translate(str.maketrans("01345@$", "oieasas")))
    if re.search(r"\b(balance|equity|free\s+margin|password)\b|p\s*[&/]\s*l", value):
        return False
    return not any(word in compact for word in BLOCKED_WORDS) and not any(
        phrase in value for phrase in BANNED_PHRASES
    )


def handle_key(value: str) -> str | None:
    value = normalized(value, 64).lstrip("@").strip()
    if not value or not safe_text(value) or any(c in value for c in '<>"&\\\n'):
        return None
    confusables = str.maketrans(
        {
            "а": "a",
            "е": "e",
            "х": "x",
            "о": "o",
            "і": "i",
            "ѕ": "s",
            "с": "c",
            "р": "p",
            "α": "a",
            "ο": "o",
            "ρ": "p",
            "ι": "i",
        }
    )
    skeleton = (
        value.casefold().translate(confusables).translate(str.maketrans("01345@$", "oieasas"))
    )
    compact = re.sub(r"[^a-z]", "", skeleton)
    if any(word in compact for word in IMPERSONATORS):
        return None
    return value.casefold()


def display_handle(value: str) -> str:
    value = normalized(value, 64).lstrip("@")
    # Count complete combining/ZWJ clusters, so truncation does not detach a mark.
    clusters: list[str] = []
    for c in value:
        if clusters and (
            unicodedata.combining(c)
            or c == "\u200d"
            or clusters[-1].endswith("\u200d")
            or c == "\ufe0f"
            or 0x1F3FB <= ord(c) <= 0x1F3FF
        ):
            clusters[-1] += c
        else:
            clusters.append(c)
    return "".join(clusters) if len(clusters) <= 18 else "".join(clusters[:17]) + "…"
