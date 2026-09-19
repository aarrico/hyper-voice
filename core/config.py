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

# ``boost`` is a faster, one-pass center lift followed by a final limiter.
# ``dialogue`` additionally manages the dynamic range of the center channel
# only. ``precise`` retains the original two-pass loudness-normalized path.
PROCESSING_MODES = ("boost", "dialogue", "precise")
DEFAULT_PROCESSING_MODE = "dialogue"

# A deliberately restrained starting point for the dialogue mode.  This is
# not voice isolation: all of the other 5.1 channels are rejoined untouched
# after the layout remix.  The compressor merely lets quiet center dialogue
# come up without relying on a large fixed center boost.
DIALOGUE_CENTER_THRESHOLD = -18.0  # dBFS
DIALOGUE_CENTER_RATIO = 2.0
DIALOGUE_CENTER_ATTACK = 20.0  # milliseconds
DIALOGUE_CENTER_RELEASE = 250.0  # milliseconds
DIALOGUE_CENTER_MAKEUP = 1.15


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
