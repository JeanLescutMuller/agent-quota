"""protector.decide with plain values: the scenarios S1–S9 of protector/CONSIDERATIONS.md §3, release order and
stagger, overrides, labels (protector/DESIGN.md §4–§5). Run: python3 -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from agent_quota import config as C  # noqa: E402
from agent_quota import protector  # noqa: E402
from agent_quota.forecast import project  # noqa: E402
from agent_quota.reading import WEEK, WINDOW, Meter, Meters  # noqa: E402

NOW = 1_800_000_000
MIN = 60


def world(window=(50, 120, 0.0), week=(30, 3 * 24 * 60, 0.0), age_s=30):
    """Meters and projections from (pct, minutes to the reset, burn rate in % per minute) per meter."""
    def one(name, spec):
        pct, reset_min, rate = spec
        m = Meter(name, pct, NOW + reset_min * MIN, NOW - age_s, age_s > C.READING_MAX_AGE_S)
        return m, project(m, rate, NOW)
    (mw, pw), (mk, pk) = one(WINDOW, window), one(WEEK, week)
    return Meters(mw, mk), {'window': pw, 'week': pk}


def session(label='', interactive=False, idle_min=1):
    return {'label': label, 'interactive': interactive, 'last_ts': NOW - idle_min * MIN, 'first_ts': NOW - 3600}


def run(meters_proj, d_sessions, usd, overrides=None, previous=None, now=NOW, sub=None):
    """sub: {session_id: the part of its $ its subagents spent}."""
    meters, projections = meters_proj
    trace = {}
    d = protector.decide(now, meters, projections, d_sessions, usd, overrides or {}, C, previous=previous, trace=trace,
                         subagent_usd=sub)
    return d, trace


class Scenarios(unittest.TestCase):
    """CONSIDERATIONS §3. Times in minutes; a rate in % of the meter per minute."""

    def test_s1_small_question_at_95_always_goes_through(self):
        # window at 95 %, Jean asks a small question in an interactive session: never frozen (R32)
        d, _ = run(world(window=(95, 60, 0.1)), {'jean': session(interactive=True)}, {'jean': 1.0})
        self.assertEqual(d['jean'].action, 'allow')
        self.assertIn('interactive', d['jean'].reason)

    def test_s2_big_job_needing_1_pct_at_98(self):
        # unknown need = large (open point 1): frozen; labelled big:1, it fits in the 2 % left: let it finish (R36)
        w = world(window=(98, 120, 1.3))
        d, _ = run(w, {'job': session()}, {'job': 20.0})
        self.assertEqual(d['job'].action, 'freeze')
        d, _ = run(w, {'job': session(label='big:1')}, {'job': 20.0})
        self.assertEqual(d['job'].action, 'allow')
        self.assertIn('fits', d['job'].reason)

    def test_s3_worked_example_paused_before_the_reserve(self):
        # 13:00 at 60 %, 1.3 %/min, reset 16:00: at 13:00 nothing yet (reserve far); at 13:22 (88.6 %) frozen
        d, _ = run(world(window=(60, 180, 1.3)), {'job': session()}, {'job': 30.0})
        self.assertEqual(d['job'].action, 'allow')
        self.assertIn('reserve is not touched', d['job'].reason)
        d, trace = run(world(window=(88.6, 158, 1.3)), {'job': session()}, {'job': 30.0})
        self.assertEqual(d['job'].action, 'freeze')
        self.assertEqual(d['job'].cause, 'window')
        self.assertEqual(d['job'].cause_resets_at, NOW + 158 * MIN)
        tw = trace['meters']['window']
        self.assertAlmostEqual(tw['lockout_min'], 158 - 11.4 / 1.3, delta=0.1)   # ≈ 2 h 29
        self.assertGreater(tw['harm'], tw['cost'])

    def test_s4_short_lockout_the_design_formula_decides(self):
        # reset at 13:40 (18 min after 13:22): lockout ≈ 9 min. DESIGN §4 as written: harm = 9.2 × 0.13 × 10 = 12 >
        # cost 8.8 min → frozen, though CONSIDERATIONS said "probably let it run". With 6 min of lockout it runs.
        d, trace = run(world(window=(88.6, 18, 1.3)), {'job': session()}, {'job': 30.0})
        self.assertEqual(d['job'].action, 'freeze')
        self.assertAlmostEqual(trace['meters']['window']['harm'], 12.0, delta=0.3)
        d, trace = run(world(window=(88.6, 15, 1.3)), {'job': session()}, {'job': 30.0})
        self.assertEqual(d['job'].action, 'allow')
        self.assertIn('not worth a pause', d['job'].reason)

    def test_s5_the_week_friday_afternoon(self):
        # week at 90 %, reset in 76 h, the job burns 3 % of the week per hour (0.05 %/min); window has no lockout
        d, _ = run(world(window=(30, 120, 0.3), week=(90, 76 * 60, 0.05)), {'job': session()}, {'job': 10.0})
        self.assertEqual(d['job'].action, 'allow')          # the week's reserve is not touched yet
        d, trace = run(world(window=(30, 120, 0.3), week=(94.8, 76 * 60 - 96, 0.05)), {'job': session()}, {'job': 10.0})
        self.assertEqual(d['job'].action, 'freeze')
        self.assertEqual(d['job'].cause, 'week')
        self.assertGreater(trace['meters']['week']['lockout_min'], 70 * 60)

    def test_s6_three_medium_jobs_pause_the_biggest_until_enough(self):
        # together 1.5 %/min; window 90 %, reset in 20 min; shares 0.6 / 0.25 / 0.15 (each > 10 % of a window/h)
        usd = {'a': 6.0, 'b': 2.5, 'c': 1.5}
        d, trace = run(world(window=(90, 20, 1.5)), {k: session() for k in usd}, usd)
        self.assertEqual([d[k].action for k in 'abc'], ['freeze', 'freeze', 'allow'])
        self.assertEqual(trace['meters']['window']['frozen'], ['a', 'b'])
        self.assertIn('enough', d['c'].reason)

    def test_s7_use_outside_claude_code_is_counted_never_paused(self):
        # the meter climbs at 1.5 %/min, most of it from claude.ai: the local big job is frozen, nothing else exists
        w = world(window=(90, 60, 1.5))
        d, trace = run(w, {'job': session(label='big')}, {'job': 0.5})
        self.assertEqual(d['job'].action, 'freeze')
        # only Jean's interactive session here: lockout ahead, nothing to freeze (v1 warns only)
        d, trace = run(w, {'jean': session(interactive=True)}, {'jean': 0.5})
        self.assertEqual(d['jean'].action, 'allow')
        self.assertTrue(trace['meters']['window']['act'])
        self.assertEqual(trace['meters']['window']['frozen'], [])

    def test_s8_the_maximizers_work_goes_first(self):
        usd = {'maxi': 3.0, 'jeans_job': 4.0}
        d_s = {'maxi': session(label='maximizer'), 'jeans_job': session(label='big')}
        d, trace = run(world(window=(93, 60, 1.0)), d_s, usd)
        self.assertEqual(trace['meters']['window']['frozen'][0], 'maxi')   # before the bigger $ of Jean's job
        self.assertIn('maximizer', d['maxi'].reason)

    def test_s9_big_job_alone_at_night(self):
        # reset at 03:00, 100 % at ≈ 01:00, nobody active: p_need = P_NEED_IDLE; v1 has no hours model (R48) → frozen
        d, trace = run(world(window=(93, 125, 1.2)), {'job': session()}, {'job': 15.0})
        self.assertEqual(trace['p_need'], C.P_NEED_IDLE)
        self.assertEqual(d['job'].action, 'freeze')


class Candidates(unittest.TestCase):
    def setUp(self):
        self.w = world(window=(92, 60, 1.5))   # lockout ahead, act now

    def test_urgent_never_frozen(self):
        d, _ = run(self.w, {'u': session(label='urgent')}, {'u': 10.0})
        self.assertEqual(d['u'].action, 'allow')
        self.assertIn('urgent', d['u'].reason)

    def test_interactive_main_thread_alone_never_frozen(self):
        # Jean's own thread burns fast, no subagent: nothing a freeze of its subagents would remove (R32)
        d, _ = run(self.w, {'i': session(interactive=True)}, {'i': 10.0})
        self.assertEqual((d['i'].action, d['i'].scope, d['i'].window_pct_per_hour), ('allow', 'subagents', 0.0))
        self.assertIn("Jean's own thread is never paused", d['i'].reason)

    def test_interactive_burning_via_subagents_frozen_in_its_subagents(self):
        # v1.1: $10 in 30 min, $8 of it by its subagents: frozen with scope subagents; it takes off the subagents'
        # share of the rate only (0.8 × 1.5 = 1.2 %/min), the main thread's 0.3 %/min stays in the meter
        d, trace = run(self.w, {'i': session(interactive=True)}, {'i': 10.0}, sub={'i': 8.0})
        self.assertEqual((d['i'].action, d['i'].scope), ('freeze', 'subagents'))
        self.assertAlmostEqual(d['i'].rate_at_freeze, 1.2)
        self.assertAlmostEqual(trace['meters']['window']['remaining_rate'], 0.3)
        self.assertIn('subagents only', d['i'].reason)
        self.assertEqual(protector.Decision.from_dict(d['i'].to_dict()).scope, 'subagents')

    def test_scripts_frozen_before_interactive_subagents(self):
        # R39: Jean's own work goes last, even when its subagents burn more than the script
        d_s = {'script': session(), 'jean': session(interactive=True)}
        d, trace = run(self.w, d_s, {'script': 3.0, 'jean': 10.0}, sub={'jean': 7.0})
        self.assertEqual(trace['meters']['window']['frozen'], ['script', 'jean'])
        self.assertEqual((d['script'].scope, d['jean'].scope), ('all', 'subagents'))

    def test_interactive_urgent_never_frozen_even_via_subagents(self):
        d, _ = run(self.w, {'i': session(label='urgent', interactive=True)}, {'i': 10.0}, sub={'i': 9.0})
        self.assertEqual(d['i'].action, 'allow')
        self.assertIn('urgent', d['i'].reason)

    def test_interactive_small_subagents_not_a_candidate(self):
        # subagents' share 0.05 × 1.5 × 60 = 4.5 % of a window per hour < 10
        d, _ = run(self.w, {'i': session(interactive=True), 'job': session()}, {'i': 10.0, 'job': 10.0}, sub={'i': 1.0})
        self.assertEqual(d['i'].action, 'allow')
        self.assertIn('its subagents burn 4.5 %', d['i'].reason)

    def test_interactive_labelled_big_can_be_frozen(self):
        d, _ = run(self.w, {'i': session(label='big', interactive=True)}, {'i': 10.0})
        self.assertEqual((d['i'].action, d['i'].scope), ('freeze', 'all'))   # Jean labelled it: the whole session

    def test_small_work_not_a_candidate(self):
        # share 0.05 × 1.5 %/min × 60 = 4.5 % of a window per hour < 10
        d, _ = run(self.w, {'big': session(), 'small': session()}, {'big': 19.0, 'small': 1.0})
        self.assertEqual(d['small'].action, 'allow')
        self.assertIn('small work', d['small'].reason)
        self.assertEqual(d['big'].action, 'freeze')

    def test_not_seen_for_10_min_not_a_candidate(self):
        d, _ = run(self.w, {'old': session(idle_min=11)}, {'old': 10.0})
        self.assertEqual(d['old'].action, 'allow')

    def test_go_on_override_never_frozen(self):
        ov = {'job': {'kind': 'go_on', 'until': NOW + 3600}}
        d, _ = run(self.w, {'job': session()}, {'job': 10.0}, overrides=ov)
        self.assertEqual(d['job'].action, 'allow')
        self.assertIn('go on', d['job'].reason)
        ov = {'job': {'kind': 'go_on', 'until': NOW - 1}}     # expired
        d, _ = run(self.w, {'job': session()}, {'job': 10.0}, overrides=ov)
        self.assertEqual(d['job'].action, 'freeze')

    def test_stale_reading_freezes_nothing(self):
        meters, proj = world(window=(92, 60, 1.5), age_s=C.READING_MAX_AGE_S + 60)
        d, trace = run((meters, proj), {'job': session()}, {'job': 10.0})
        self.assertEqual(d['job'].action, 'allow')
        self.assertIn('too old', d['job'].reason)

    def test_no_reading_at_all(self):
        meters = Meters(Meter(WINDOW, None, None, None, True), Meter(WEEK, None, None, None, True))
        d, _ = run((meters, {}), {'job': session()}, {'job': 10.0})
        self.assertEqual(d['job'].action, 'allow')

    def test_every_decision_has_a_reason(self):
        usd = {'a': 6.0, 'b': 2.5, 'c': 1.5, 'i': 1.0}
        d_s = {k: session() for k in 'abc'} | {'i': session(interactive=True)}
        d, _ = run(world(window=(90, 20, 1.5)), d_s, usd)
        for dec in d.values():
            self.assertIn(dec.action, ('allow', 'freeze'))
            self.assertTrue(dec.reason)


def frozen(sid, cause='window', since=NOW - 3600, resets=NOW - 60, label='', rate=0.5):
    return protector.Decision(sid, 'freeze', 'paused', cause=cause, label=label, frozen_since=since,
                              cause_resets_at=resets, rate_at_freeze=rate)


class Release(unittest.TestCase):
    """R43, R44: release after the reset, one every RESUME_STAGGER_MIN, urgent first, then the oldest freeze."""

    def test_release_order_and_stagger(self):
        prev = {'old': frozen('old', since=NOW - 7200), 'new': frozen('new', since=NOW - 3600),
                'urg': frozen('urg', since=NOW - 600, label='urgent')}
        w = world(window=(0, 300, 0.0))   # the window has reset
        d_s = {k: session(idle_min=60) for k in prev}
        d, _ = run(w, d_s, {}, previous=prev)
        self.assertEqual({k: v.action for k, v in d.items()}, {'urg': 'allow', 'old': 'freeze', 'new': 'freeze'})
        self.assertIn('waiting its turn', d['old'].reason)
        # 1 minute later: still one per 5 min
        d2, _ = run(w, d_s, {}, previous=d, now=NOW + 60)
        self.assertEqual(d2['old'].action, 'freeze')
        # 5 minutes later: the oldest freeze next
        d3, _ = run(w, d_s, {}, previous=d2, now=NOW + C.RESUME_STAGGER_MIN * 60)
        self.assertEqual((d3['old'].action, d3['new'].action), ('allow', 'freeze'))
        d4, _ = run(w, d_s, {}, previous=d3, now=NOW + 2 * C.RESUME_STAGGER_MIN * 60)
        self.assertEqual(d4['new'].action, 'allow')

    def test_not_released_into_a_full_week(self):
        prev = {'job': frozen('job')}
        d, _ = run(world(window=(0, 300, 0.0), week=(96, 600, 0.001)), {'job': session(idle_min=60)}, {}, previous=prev)
        self.assertEqual(d['job'].action, 'freeze')
        self.assertIn('week', d['job'].reason)

    def test_kept_while_the_lockout_is_still_ahead(self):
        prev = {'job': frozen('job', resets=NOW + 3600)}
        d, _ = run(world(window=(93, 60, 0.5)), {'job': session(idle_min=30)}, {}, previous=prev)
        self.assertEqual(d['job'].action, 'freeze')

    def test_released_before_the_reset_when_safe_even_with_its_burn_back(self):
        # window at 50 %, 60 min left, others burn 0.1 %/min, the job burned 0.2: 50 + 0.3 × 60 = 68 < 95
        prev = {'job': frozen('job', resets=NOW + 3600, rate=0.2)}
        d, _ = run(world(window=(50, 60, 0.1)), {'job': session(idle_min=30)}, {}, previous=prev)
        self.assertEqual(d['job'].action, 'allow')
        # with a big burn back (1.0 %/min: 50 + 1.1 × 60 > 95) it waits
        prev = {'job': frozen('job', resets=NOW + 3600, rate=1.0)}
        d, _ = run(world(window=(50, 60, 0.1)), {'job': session(idle_min=30)}, {}, previous=prev)
        self.assertEqual(d['job'].action, 'freeze')

    def test_stale_reading_keeps_the_freeze(self):
        prev = {'job': frozen('job', resets=NOW + 3600)}
        d, _ = run(world(window=(50, 60, 0.1), age_s=C.READING_MAX_AGE_S + 60), {}, {}, previous=prev)
        self.assertEqual(d['job'].action, 'freeze')
        # but a passed reset is known without a reading
        prev = {'job': frozen('job', resets=NOW - 60)}
        d, _ = run(world(window=(50, 60, 0.1), age_s=C.READING_MAX_AGE_S + 60), {}, {}, previous=prev)
        self.assertEqual(d['job'].action, 'allow')

    def test_resume_now_releases_at_once_ignoring_the_stagger(self):
        prev = {'a': frozen('a', resets=NOW + 3600), 'b': frozen('b', resets=NOW + 3600)}
        prev['c'] = protector.Decision('c', 'allow', 'resumed', released_at=NOW - 30)   # a release 30 s ago
        ov = {'a': {'kind': 'resume_now', 'until': NOW + 3600}, 'b': {'kind': 'go_on', 'until': NOW + 3600}}
        d, _ = run(world(window=(93, 60, 0.5)), {}, {}, overrides=ov, previous=prev)
        self.assertEqual((d['a'].action, d['b'].action), ('allow', 'allow'))
        self.assertIn('resume now', d['a'].reason)

    def test_previously_frozen_not_frozen_twice(self):
        # a frozen session kept frozen keeps its first frozen_since and cause
        prev = {'job': frozen('job', since=NOW - 900, resets=NOW + 3600)}
        d, _ = run(world(window=(93, 60, 1.0)), {'job': session()}, {'job': 10.0}, previous=prev)
        self.assertEqual((d['job'].action, d['job'].frozen_since), ('freeze', NOW - 900))


class Labels(unittest.TestCase):
    def test_parse_label(self):
        self.assertEqual(protector.parse_label('big:3'), ('big', 3.0))
        self.assertEqual(protector.parse_label('BIG'), ('big', None))
        self.assertEqual(protector.parse_label('big:x'), ('big', None))
        self.assertEqual(protector.parse_label(None), ('', None))

    def test_big_pct_that_does_not_fit(self):
        d, _ = run(world(window=(93, 60, 1.0)), {'job': session(label='big:10')}, {'job': 5.0})
        self.assertEqual(d['job'].action, 'freeze')

    def test_decision_round_trip(self):
        dec = frozen('x')
        self.assertEqual(protector.Decision.from_dict(dict(dec.to_dict(), unknown_field=1)), dec)


if __name__ == '__main__':
    unittest.main()
