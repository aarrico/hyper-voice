# Executables
FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

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
NEW_TRACK_CODEC = "eac3"
NEW_TRACK_BITRATE = "448k"
NEW_TRACK_TITLE = "Dialogue Boost (Hisense)"
