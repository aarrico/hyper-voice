import json
import subprocess
from pathlib import Path

from . import config

# ISO 639-2 (bibliographic) <-> ISO 639-1 pairs for languages media taggers
# commonly disagree on. Unlisted codes just match themselves.
_LANGUAGE_ALIAS_PAIRS = {
    "eng": "en", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de",
    "spa": "es", "ita": "it", "por": "pt", "chi": "zh", "zho": "zh",
    "jpn": "ja", "kor": "ko", "rus": "ru", "dut": "nl", "nld": "nl",
}
_LANGUAGE_ALIAS_PAIRS.update({v: k for k, v in list(_LANGUAGE_ALIAS_PAIRS.items())})


def language_aliases(language: str) -> set[str]:
    """Returns the set of tag values that should match a given language code,
    covering the ISO 639-2/639-1 split taggers disagree on (e.g. eng vs en)."""
    code = language.lower()
    aliases = {code}
    if code in _LANGUAGE_ALIAS_PAIRS:
        aliases.add(_LANGUAGE_ALIAS_PAIRS[code])
    return aliases


def probe_audio_streams(video: Path, *, ffprobe_path: str = config.FFPROBE_PATH) -> list[dict]:
    """Returns ffprobe's audio stream entries (index, codec_name, profile,
    channels, channel_layout, tags) in container order."""
    cmd = [
        ffprobe_path,
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index,codec_name,profile,channels,channel_layout:stream_tags=title,language",
        "-of",
        "json",
        str(video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["streams"]


def _is_commentary(stream: dict) -> bool:
    title = (stream.get("tags", {}).get("title") or "").lower()
    return any(keyword in title for keyword in config.COMMENTARY_KEYWORDS)


def _codec_tier(stream: dict) -> int:
    """Lossless-vs-lossy tier, so a lossless track always outranks a lossy one
    regardless of channel count (avoids re-compressing an already-lossy track)."""
    codec = stream.get("codec_name", "")
    profile = (stream.get("profile") or "").upper()
    if codec in config.LOSSLESS_CODECS or codec.startswith("pcm_"):
        return 2
    if codec == "dts" and "MA" in profile:
        return 2
    return 1


def select_source_stream(streams: list[dict], *, preferred_language: str = config.PREFERRED_LANGUAGE) -> dict:
    candidates = [s for s in streams if not _is_commentary(s)] or list(streams)

    aliases = language_aliases(preferred_language)
    preferred = [
        s for s in candidates
        if (s.get("tags", {}).get("language") or "").lower() in aliases
    ]
    pool = preferred or candidates

    return max(pool, key=lambda s: (_codec_tier(s), s.get("channels", 0)))
