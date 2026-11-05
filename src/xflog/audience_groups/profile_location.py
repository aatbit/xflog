import hashlib
import re
import unicodedata

from . import AudienceGroup, Bucket, register

KEY = "profile-location"
MAX_LOCATION_LENGTH = 160
UNKNOWN = Bucket("unknown", "Unknown")
ALIASES = {
    "nyc": "New York City",
    "new york city": "New York City",
    "new york ny": "New York City",
    "new york city ny": "New York City",
    "us": "United States",
    "u s": "United States",
    "usa": "United States",
    "u s a": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "u k": "United Kingdom",
    "united kingdom": "United Kingdom",
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "bangalore india": "Bengaluru, India",
    "bengaluru india": "Bengaluru, India",
}
MISSING = {
    "unknown",
    "n/a",
    "n a",
    "na",
    "none",
    "null",
    "not set",
    "not specified",
    "not available",
    "undisclosed",
    "prefer not to say",
}


def location_key(label: str) -> str:
    key = re.sub(r"[.,;|]", " ", label.casefold())
    return " ".join(re.sub(r"\s*/\s*", "/", key).split())


def normalize(value) -> str | None:
    if not isinstance(value, str) or len(value) > MAX_LOCATION_LENGTH:
        return None
    label = " ".join(unicodedata.normalize("NFKC", value).split()).strip(" ,;|")
    if (
        not any(letter.isalpha() for letter in label)
        or any(unicodedata.category(letter).startswith("C") for letter in label)
        or len(label) > MAX_LOCATION_LENGTH
    ):
        return None
    label = re.sub(r"\s*[,;|]\s*", ", ", label)
    label = re.sub(r"\s*/\s*", " / ", label)
    key = location_key(label)
    if key in MISSING or len(label) > MAX_LOCATION_LENGTH:
        return None
    # Only explicit aliases merge places; fuzzy matching could conflate different cities.
    return ALIASES.get(key, label)


def capture(source: dict) -> dict:
    label = normalize(source.get("location"))
    return {"location": label} if label else {}


def assign(event: dict) -> Bucket:
    snapshot = event.get("group_data", {}).get(KEY, {})
    label = normalize(snapshot.get("location")) if isinstance(snapshot, dict) else None
    if not label:
        return UNKNOWN
    digest = hashlib.sha256(location_key(label).encode()).hexdigest()
    return Bucket(f"location-{digest}", label)


register(
    AudienceGroup(
        key=KEY,
        label="Profile location",
        description="Similar location labels delivered with new events, cleaned up without lookups. Missing labels stay Unknown.",
        buckets=(UNKNOWN,),
        capture=capture,
        assign=assign,
        dynamic_buckets=True,
    )
)
