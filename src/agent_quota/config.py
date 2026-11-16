"""Every starting value of the protector, in one place: protector/DESIGN.md §2.

Names are exactly DESIGN §2's. A value marked [assumed] there is waiting for Jean's review.
The last block holds values that are not parameters (facts of Claude's meters) or that
only the reading/forecast code owns.
"""

# --- protector/DESIGN.md §2 ---------------------------------------------------------
RESERVE_WINDOW_PCT = 5            # % of a window kept for Jean's small urgent work (Jean, 2026-11-16)
RESERVE_WEEK_PCT = 5              # % of the week, idem
LOCKOUT_VS_DELAY = 10             # an hour of lockout weighs 10 hours of delay to a big job (Jean, 2026-11-16)
READING_MAX_AGE_S = 600           # a quota reading older than this is stale (maximizer/DESIGN.md §9)
RECENT_MIN = 30                   # burn rate: look-back of the recent slope, minutes (legacy lab)
RATE_FACTOR = 1.5                 # burn rate: safety factor on max(slope, average) (legacy lab, measured best)
ACTIVE_MIN = 30                   # "Jean active" = an interactive session used in the last 30 min
P_NEED_ACTIVE = 0.52              # chance Jean uses > 25 % of a window within 5 h, if active [measured on Pro]
P_NEED_IDLE = 0.13                # idem, if not active
BIG_JOB_PCT_PER_HOUR = 10         # a session using this much of a window per hour alone is a big job [assumed]
DECISION_MAX_AGE_S = 60           # the hook recomputes decisions.json when older [assumed]
HOLD_POLL_S = 30                  # a frozen hook re-reads decisions.json this often
HOOK_TIMEOUT_S = 21600            # the hook's `timeout` (6 h covers any window) [verified 5 h 05, 2026-11-11]
RESUME_STAGGER_MIN = 5            # one frozen session released every 5 min (R44) [assumed]
WINDOW_SHARE_OF_WEEK_PCT = 13.2   # one full window in % of the week = B / B_week = $194 / $1,469 [Max 5x, 2026-10-12]

# --- facts of the meters, and the reading/forecast code's own values ---------------
WINDOW_S = 5 * 3600               # a window lasts 5 h from its first request: opened = resets_at - WINDOW_S
WEEK_S = 7 * 86400                # the week lasts 7 days: opened = resets_at - WEEK_S
MIN_RATE_DENOMINATOR_MIN = 10     # forecast: floor on an average's divisor, so a 2-min-old window does not read
                                  # 0.5 %/min off its first whole percent (legacy lab's MIN_RATE_DENOMINATOR_MINUTES)
RESET_FALL_PCT = 5                # forecast: a fall of more than 5 points between readings = a reset
RESET_TOLERANCE_S = 120           # the same reset reads ±1 s across sources (verified 2026-11-16): same window
                                  # when two resets_at differ by at most this
