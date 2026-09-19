from dataclasses import dataclass
from pathlib import Path

import av

from . import config


class SourceSelectionError(ValueError):
    """Raised when no audio track satisfies the requested source policy."""


@dataclass(frozen=True)
class CandidateExplanation:
    """A candidate plus the reason it was or was not eligible for selection."""

    stream: dict
    reason: str


# ISO 639-2 (bibliographic) <-> ISO 639-1 pairs for languages media taggers
# commonly disagree on. Unlisted codes just match themselves.
_LANGUAGE_ALIAS_PAIRS = {
    "eng": "en",
    "fre": "fr",
    "fra": "fr",
    "ger": "de",
    "deu": "de",
    "spa": "es",
    "ita": "it",
    "por": "pt",
    "chi": "zh",
    "zho": "zh",
    "jpn": "ja",
    "kor": "ko",
    "rus": "ru",
    "dut": "nl",
    "nld": "nl",
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


def probe_audio_streams(video: Path) -> list[dict]:
    """Returns audio stream entries (index, codec_name, profile, channels,
    channel_layout, tags) in container order, read directly via PyAV."""
    with av.open(str(video)) as container:
        return [
            {
                "index": stream.index,
                "codec_name": stream.codec_context.name,
                "profile": stream.profile,
                "channels": stream.codec_context.channels,
                # some PCM-in-MKV streams carry no explicit layout mask; PyAV
                # then reports a generic "N channels" name that won't match
                # any DOWNMIX_TO_5_1 key, which is the desired fallback.
                "channel_layout": stream.layout.name if stream.layout else "",
                "bit_rate": stream.codec_context.bit_rate,
                "tags": dict(stream.metadata),
            }
            for stream in container.streams.audio
        ]


def _is_commentary(stream: dict) -> bool:
    title = (stream.get("tags", {}).get("title") or "").lower()
    return any(keyword in title for keyword in config.COMMENTARY_KEYWORDS)


def _codec_tier(stream: dict) -> int:
    """Returns the fidelity tier used only after layout/channel preference."""
    codec = stream.get("codec_name", "")
    profile = (stream.get("profile") or "").upper()
    if codec in config.LOSSLESS_CODECS or codec.startswith("pcm_"):
        return 2
    if codec == "dts" and "MA" in profile:
        return 2
    return 1


def explain_source_candidates(
    streams: list[dict],
    *,
    preferred_language: str = config.PREFERRED_LANGUAGE,
    source_track: int | None = None,
    prefer_5_1: bool = False,
    allow_stereo: bool = False,
) -> list[CandidateExplanation]:
    """Explain source eligibility in input stream order for CLI reporting."""
    if source_track is not None:
        return [
            CandidateExplanation(
                stream,
                "selected by --source-track"
                if stream.get("index") == source_track
                else "not requested",
            )
            for stream in streams
        ]

    candidates = [s for s in streams if not _is_commentary(s)] or list(streams)
    aliases = language_aliases(preferred_language)
    preferred = [
        s
        for s in candidates
        if (s.get("tags", {}).get("language") or "").lower() in aliases
    ]
    pool = preferred or candidates

    return [
        CandidateExplanation(
            stream,
            "excluded commentary"
            if stream not in candidates
            else "different language"
            if stream not in pool
            else "stereo/mono not allowed"
            if not allow_stereo and stream.get("channels", 0) <= 2
            else "eligible"
            + ("; 5.1 preferred" if prefer_5_1 and stream.get("channels") == 6 else ""),
        )
        for stream in streams
    ]


def select_source_stream(
    streams: list[dict],
    *,
    preferred_language: str = config.PREFERRED_LANGUAGE,
    source_track: int | None = None,
    prefer_5_1: bool = False,
    allow_stereo: bool = False,
) -> dict:
    """Select a deterministic source, prioritising language then surround.

    Fidelity and bitrate break ties only after channel/layout preference, so a
    lossless stereo stream cannot suppress a usable 5.1/7.1 dialogue source.
    """
    if not streams:
        raise SourceSelectionError("No audio streams found")

    if source_track is not None:
        selected = next((s for s in streams if s.get("index") == source_track), None)
        if selected is None:
            raise SourceSelectionError(
                f"Requested source track {source_track} is not an audio stream"
            )
        if selected.get("channels", 0) <= 2 and not allow_stereo:
            raise SourceSelectionError(
                "Requested source track is stereo/mono; pass --allow-stereo to permit it"
            )
        return selected

    candidates = [s for s in streams if not _is_commentary(s)] or list(streams)
    aliases = language_aliases(preferred_language)
    preferred = [
        s
        for s in candidates
        if (s.get("tags", {}).get("language") or "").lower() in aliases
    ]
    pool = preferred or candidates

    if not allow_stereo:
        pool = [s for s in pool if s.get("channels", 0) > 2]
        if not pool:
            raise SourceSelectionError(
                "No surround source track qualifies; pass --allow-stereo to permit stereo/mono"
            )

    def rank(stream: dict) -> tuple[int, int, int, int, int]:
        channels = stream.get("channels", 0) or 0
        # A 5.1 override changes only the channel-count tie-breaker.
        channel_rank = (1 if channels == 6 else 0) if prefer_5_1 else channels
        return (
            1 if channels > 2 else 0,
            channel_rank,
            channels if prefer_5_1 else 0,
            _codec_tier(stream),
            stream.get("bit_rate", 0) or 0,
        )

    # max is stable, retaining input stream order for an exact tie.
    return max(pool, key=rank)
