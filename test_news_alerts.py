import datetime
import news_alerts as n

UTC = datetime.timezone.utc


def _set(events):
    n._cache.update(at=datetime.datetime.now(UTC), events=events)


def test_safety_filter():
    assert n.is_safe("🔴 בעוד 5 דקות (15:30): CPI m/m")
    for bad in ("הבוט פתח עסקה", "רווח של 500", "הפסד", "מאזן", "bot", "Trade"):
        assert not n.is_safe(bad), bad


def test_all_generated_text_is_safe():
    t = datetime.datetime(2026, 10, 27, 12, 30, tzinfo=UTC)
    _set([(t, "CPI m/m", "tier1"), (t, "Core CPI m/m", "tier1"),
          (t + datetime.timedelta(hours=1), "ISM Services PMI", "high"),
          (t + datetime.timedelta(hours=2), "Unemployment Claims", "medium")])
    now = datetime.datetime(2026, 10, 27, 8, 0, tzinfo=n.IL)
    assert n.is_safe(n.digest_text(now))
    for k in ("tier1", "high", "medium"):
        for last in (False, True):
            assert n.is_safe(n.headsup_text(t, [("X", k)], 5, last))


def test_digest_tier1_first_and_empty_case():
    t = datetime.datetime(2026, 10, 27, 12, 30, tzinfo=UTC)
    _set([(t, "CPI m/m", "tier1"), (t, "ISM", "high")])
    now = datetime.datetime(2026, 10, 27, 8, 0, tzinfo=n.IL)
    s = n.digest_text(now)
    assert s.index("Tier-1") < s.index("חזקות אחרות") and "CPI m/m" in s
    _set([])
    assert "אין חדשות Tier-1" in n.digest_text(now)


def test_headsups_30_then_7_once_each():
    t = datetime.datetime(2026, 10, 27, 12, 30, tzinfo=UTC)
    _set([(t, "CPI m/m", "tier1")])
    a = n.due_headsups(t - datetime.timedelta(minutes=29))
    assert len(a) == 1 and "30" in a[0][0]
    b = n.due_headsups(t - datetime.timedelta(minutes=6))
    assert len(b) == 1 and b[0][0].endswith("|7")   # the 30 is skipped inside the last window
    assert n.due_headsups(t - datetime.timedelta(minutes=60)) == []
