"""
Default settings for case generation. Same philosophy as rules/config.py -
single source of truth for now, tenant-configurable later.
"""

DEFAULT_CASE_CONFIG = {
    # Flags on the same subject more than this many days apart are treated
    # as separate, unrelated incidents rather than one case. Chosen to be
    # wide enough to link a plausible attack chain (e.g. a dormant-account
    # reactivation followed weeks later by a large withdrawal on the same
    # member) without merging genuinely unrelated events a year apart into
    # one unmanageable case file.
    "time_window_days": 45,
}
