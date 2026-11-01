"""AI images made on this Mac (images.py needs the ml environment; this file only holds what the core needs too)."""


def seeds(p):
    """the versions made of each drawn image: one for a channel episode (owner's decision 2a of 19 Oct 2026: the pick
    still checks it), two for the classic tests (their results stay the same); options.ai_seeds overrides"""
    return p.opt("ai_seeds", [11] if p.profile else [11, 23])
