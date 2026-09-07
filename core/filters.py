# pan-based downmix filters, keyed by source channel_layout. Each folds the
# source down to a discrete 5.1 bed with the same center-channel boost baked
# in (1.25*FC) so a listener hears dialogue over a soundbar. Edit the boost
# multiplier here to change how aggressive the dialogue lift is.
DOWNMIX_TO_5_1 = {
    "5.1": "pan=5.1|FL=FL|FR=FR|FC=1.25*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR",
    "5.1(side)": "pan=5.1|FL=FL|FR=FR|FC=1.25*FC|LFE=LFE|BL=0.85*SL|BR=0.85*SR",
    "7.1": "pan=5.1|FL=FL|FR=FR|FC=1.25*FC|LFE=LFE|BL=0.6*BL+0.425*SL|BR=0.6*BR+0.425*SR",
    "7.1(wide)": "pan=5.1|FL=0.85*FL+0.3*FLC|FR=0.85*FR+0.3*FRC|FC=1.25*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR",
}
CENTER_BOOST = "pan=5.1|FL=FL|FR=FR|FC=1.25*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR"


def get_downmix_filter(channel_layout: str) -> str:
    """Returns a `pan`-based filter that folds the given source layout down to
    a discrete 5.1 bed, with the dialogue boost baked in. Falls back to a
    generic remix + boost for layouts we don't have an explicit mapping for."""
    return DOWNMIX_TO_5_1.get(
        channel_layout, f"aformat=channel_layouts=5.1,{CENTER_BOOST}"
    )


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
