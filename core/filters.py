from . import config

DOWNMIX_TO_5_1 = {
    "5.1": "pan=5.1|FL=FL|FR=FR|FC=1.3*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR",
    "5.1(side)": "pan=5.1|FL=FL|FR=FR|FC=1.3*FC|LFE=LFE|BL=0.85*SL|BR=0.85*SR",
    "7.1": "pan=5.1|FL=FL|FR=FR|FC=1.3*FC|LFE=LFE|BL=0.6*BL+0.475*SL|BR=0.6*BR+0.475*SR",
    "7.1(wide)": "pan=5.1|FL=0.85*FL+0.35*FLC|FR=0.85*FR+0.35*FRC|FC=1.3*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR",
}
CENTER_BOOST = "pan=5.1|FL=FL|FR=FR|FC=1.3*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR"

# Dialogue mode has its own remix policy.  In particular, it must not inherit
# boost mode's 1.3x static FC lift: the modest makeup gain happens only after
# FC compression.  A native 5.1 source remains a full, position-for-position
# 5.1 bed.
DIALOGUE_REMIX_TO_5_1 = {
    "5.1": "pan=5.1|FL=FL|FR=FR|FC=FC|LFE=LFE|BL=BL|BR=BR",
    "5.1(side)": "pan=5.1|FL=FL|FR=FR|FC=FC|LFE=LFE|BL=SL|BR=SR",
    "7.1": "pan=5.1|FL=FL|FR=FR|FC=FC|LFE=LFE|BL=0.6*BL+0.475*SL|BR=0.6*BR+0.475*SR",
    "7.1(wide)": "pan=5.1|FL=0.85*FL+0.35*FLC|FR=0.85*FR+0.35*FRC|FC=FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR",
}


def get_downmix_filter(channel_layout: str) -> str:
    """Returns a `pan`-based filter that folds the given source layout down to
    a discrete 5.1 bed, with the dialogue boost baked in. Falls back to a
    generic remix + boost for layouts we don't have an explicit mapping for."""
    return DOWNMIX_TO_5_1.get(
        channel_layout, f"aformat=channel_layouts=5.1,{CENTER_BOOST}"
    )


def get_dialogue_remix_filter(channel_layout: str) -> str:
    """Return the non-isolating 5.1 remix used before center compression."""
    return DIALOGUE_REMIX_TO_5_1.get(channel_layout, "aformat=channel_layouts=5.1")


def get_boost_filter(channel_layout: str, *, true_peak: float) -> str:
    """Build the one-pass boost chain for a source layout.

    ``alimiter`` takes a linear amplitude limit, while the CLI expresses the
    ceiling in dBTP. Disable its auto-level behavior: the limiter's job here
    is only to catch peaks created by the center lift, not to apply makeup
    gain to the whole mix.
    """
    if not -24.0 <= true_peak <= 0.0:
        raise ValueError("true_peak must be between -24 and 0 dBTP")
    limit = 10 ** (true_peak / 20)
    return (
        f"{get_downmix_filter(channel_layout)},alimiter=limit={limit:.6f}:level=false"
    )


def dialogue_settings() -> str:
    """Return the user-visible, conservative center-channel preset."""
    return (
        f"threshold={config.DIALOGUE_CENTER_THRESHOLD:g}dB, "
        f"ratio={config.DIALOGUE_CENTER_RATIO:g}:1, "
        f"attack={config.DIALOGUE_CENTER_ATTACK:g}ms, "
        f"release={config.DIALOGUE_CENTER_RELEASE:g}ms, "
        f"makeup={config.DIALOGUE_CENTER_MAKEUP:g}x"
    )


def link_dialogue_filter_graph(graph, source, *, true_peak: float):
    """Build the dialogue graph and return its final limiter context.

    The source has already been remixed to 5.1.  ``channelsplit`` exposes
    each bed channel independently; only FC traverses ``acompressor`` and a
    small makeup gain.  The other five channels are wired directly into
    ``join``.  This deliberately preserves score, ambience, and effects --
    it is not a speech-extraction graph.
    """
    if not -24.0 <= true_peak <= 0.0:
        raise ValueError("true_peak must be between -24 and 0 dBTP")

    split = graph.add("channelsplit", "channel_layout=5.1")
    source.link_to(split)
    compressor = graph.add(
        "acompressor",
        "threshold="
        f"{config.DIALOGUE_CENTER_THRESHOLD}dB:"
        f"ratio={config.DIALOGUE_CENTER_RATIO}:"
        f"attack={config.DIALOGUE_CENTER_ATTACK}:"
        f"release={config.DIALOGUE_CENTER_RELEASE}:"
        "detection=rms:link=average",
    )
    makeup = graph.add("volume", f"volume={config.DIALOGUE_CENTER_MAKEUP}")
    split.link_to(compressor, 2, 0)  # FC is the third standard 5.1 channel.
    compressor.link_to(makeup)

    join = graph.add("join", "inputs=6:channel_layout=5.1")
    for output_index, input_index in ((0, 0), (1, 1), (3, 3), (4, 4), (5, 5)):
        split.link_to(join, output_index, input_index)
    makeup.link_to(join, 0, 2)

    limit = 10 ** (true_peak / 20)
    limiter = graph.add("alimiter", f"limit={limit:.6f}:level=false")
    join.link_to(limiter)
    return limiter


def link_filter_chain(graph, chain: str, source):
    """Adds each comma-separated `name=args` filter in `chain` (the fallback
    branch of get_downmix_filter is two filters, `aformat` then `pan`) to
    `graph`, linking them in sequence after `source`. Returns the last
    filter context, ready to link into whatever comes next."""
    current = source
    for spec in chain.split(","):
        name, _, args = spec.partition("=")
        ctx = graph.add(name, args)
        current.link_to(ctx)
        current = ctx
    return current
