from dataclasses import dataclass

# Constants
EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v"}
COMMENTARY_KEYWORDS = ("commentary", "director", "cast")
LOSSLESS_CODECS = {"truehd", "flac", "alac", "mlp"}

# Tunable parameters (all overridable via CLI flags in cli.py)
LOUDNORM_I = -16.0  # target integrated loudness (LUFS)
LOUDNORM_TP = -1.5  # true peak ceiling (dBTP)
LOUDNORM_LRA = 11.0  # target loudness range
MAX_WORKERS = 4
PREFERRED_LANGUAGE = "eng"
NEW_TRACK_TITLE = "Dialogue Enhance (5.1)"


@dataclass(frozen=True)
class OutputProfile:
    """The delivery defaults for one derived audio-track policy."""

    codec: str
    bitrate: str | None
    sample_rate: int


OUTPUT_PROFILES = {
    # Dolby Digital Plus is the playback-oriented default for the target setup.
    "compatible": OutputProfile(codec="eac3", bitrate="640k", sample_rate=48_000),
    # FLAC preserves the processed PCM. Its HDMI/eARC multichannel support varies.
    "archival": OutputProfile(codec="flac", bitrate=None, sample_rate=48_000),
}
DEFAULT_PROFILE = "compatible"
