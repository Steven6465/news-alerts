"""
News-only Telegram alerts for a group.

Standalone service: it shares NO code, state or credentials with the trading
bridge, panel, bots or alerts, and it has no access to anything about trades.
It reads the same public ForexFactory calendar feed the bridge uses and sends:
  - a morning summary (08:00-09:00 Israel time, Mon-Fri, once a day)
  - a heads-up 30 minutes and 7 minutes before each relevant USD event
Message text is generic (time, event, importance, whether to be flat). A
last-line safety filter refuses to send any text containing a forbidden word
(bot / trade / profit / loss / balance ...), so nothing about a system or its
results can ever reach the group.

Modes (env NEWS_MODE): dry (default, prints only) | me (sends to NEWS_TEST_CHAT_ID)
| group (sends to NEWS_GROUP_CHAT_ID). Token: NEWS_BOT_TOKEN (a separate bot).
Never put the token in code or files; set it as an environment variable.

Usage:
  py news_alerts.py --preview     print today's summary + sample heads-ups, send nothing
  py news_alerts.py               run the loop (mode from NEWS_MODE)
  py news_alerts.py --once        one check then exit (used by the GitHub Actions schedule)
"""
import datetime
import json
import os
import re
import sys
import threading
from zoneinfo import ZoneInfo

import requests

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NY = ZoneInfo("America/New_York")
IL = ZoneInfo("Asia/Jerusalem")
REFRESH = datetime.timedelta(hours=3)
HEADS_UP_MINUTES = (30, 7)
DIGEST_HOUR_IL = 8
DIGEST_CATCHUP_HOURS = 1
FLAT_MINUTES_BEFORE = 5
EXTRA_KEYWORDS = ("crude oil inventories", "unemployment claims", "philly fed")
TIER1_KEYWORDS = ("fomc", "federal funds rate", "non-farm", "cpi")
HE_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Anything matching one of these is never sent (case-insensitive substring).
FORBIDDEN = ("בוט", "bot", "עסק", "trade", "רווח", "הפסד", "profit", "loss", "pnl", "מאזן", "balance",
             "חסימ", "חסום", "אוטומט", "סימולצ", "traderspost", "tradovate", "bridge", "גשר", "webhook")


def is_safe(text: str) -> bool:
    low = text.lower()
    return not any(w in low for w in FORBIDDEN)


# ---------------------------------------------------------------- calendar
_cache = {"at": None, "events": []}   # events: (utc_time, title, kind) kind in tier1|high|medium


def _kind(e) -> str | None:
    if e.get("country") != "USD":
        return None
    title = (e.get("title") or "").lower()
    impact = e.get("impact")
    if impact == "High":
        return "tier1" if any(k in title for k in TIER1_KEYWORDS) else "high"
    if impact == "Medium" or any(k in title for k in EXTRA_KEYWORDS):
        return "medium"
    return None


def load_events(force=False) -> bool:
    now = datetime.datetime.now(datetime.timezone.utc)
    if not force and _cache["at"] and now - _cache["at"] < REFRESH:
        return True
    try:
        r = requests.get(FEED_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        out = []
        for e in r.json():
            k = _kind(e)
            if not k or not e.get("date"):
                continue
            try:
                t = datetime.datetime.fromisoformat(e["date"])
            except ValueError:
                continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=NY)
            out.append((t.astimezone(datetime.timezone.utc), e.get("title", ""), k))
        out.sort(key=lambda x: x[0])
        _cache.update(at=now, events=out)
        return True
    except Exception as exc:
        print("calendar refresh failed:", exc)
        return _cache["at"] is not None


def events_between(start, end):
    s, e = start.astimezone(datetime.timezone.utc), end.astimezone(datetime.timezone.utc)
    return [x for x in _cache["events"] if s <= x[0] < e]


# ---------------------------------------------------------------- messages
# Hebrew names for the common US releases (first match wins, so specific names come first).
HE_NAMES = (
    ("cb consumer confidence", "מדד אמון הצרכנים (CB)"),
    ("consumer sentiment", "סנטימנט הצרכנים (מישיגן)"),
    ("unemployment claims", "בקשות לדמי אבטלה"),
    ("federal funds rate", "החלטת הריבית של הפד"),
    ("fomc statement", "הודעת ה-FOMC"),
    ("fomc press conference", "מסיבת העיתונאים של ה-FOMC"),
    ("fomc meeting minutes", "פרוטוקול ה-FOMC"),
    ("fomc", "FOMC"),
    ("core cpi", "מדד המחירים לצרכן הליבה (CPI)"),
    ("cpi", "מדד המחירים לצרכן (CPI)"),
    ("core ppi", "מדד מחירי היצרן הליבה (PPI)"),
    ("ppi", "מדד מחירי היצרן (PPI)"),
    ("core pce", "מדד PCE הליבה"),
    ("pce price index", "מדד מחירי PCE"),
    ("gdp price index", "מדד מחירי התוצר"),
    ("gdp", "תוצר מקומי גולמי (GDP)"),
    ("non-farm employment change", "דוח התעסוקה (NFP)"),
    ("adp non-farm", "תעסוקה במגזר הפרטי (ADP)"),
    ("unemployment rate", "שיעור האבטלה"),
    ("average hourly earnings", "שכר שעתי ממוצע"),
    ("jolts", "משרות פנויות (JOLTS)"),
    ("ism manufacturing", "מדד ה-PMI התעשייתי (ISM)"),
    ("ism services", "מדד ה-PMI של השירותים (ISM)"),
    ("flash manufacturing", "PMI תעשייה ראשוני"),
    ("flash services", "PMI שירותים ראשוני"),
    ("retail sales", "מכירות קמעונאיות"),
    ("crude oil inventories", "מלאי נפט גולמי"),
    ("philly fed", "מדד הפד של פילדלפיה"),
    ("empire state", "מדד התעשייה של ניו יורק"),
    ("durable goods", "הזמנות מוצרים בני קיימא"),
    ("building permits", "היתרי בנייה"),
    ("housing starts", "התחלות בנייה"),
    ("existing home sales", "מכירות בתים קיימים"),
    ("new home sales", "מכירות בתים חדשים"),
    ("trade balance", "יתרת הסחר"),
    ("speaks", "נאום"),
)


def he_title(title: str) -> str:
    """'<Hebrew> · <English>' for known releases, the English title otherwise."""
    low = title.lower()
    for key, he in HE_NAMES:
        if key in low:
            both = f"{he} · {title}"
            return both if is_safe(both) else he
    return title


def _hm(t) -> str:
    return t.astimezone(IL).strftime("%H:%M")


def _group_by_time(items):
    by = {}
    for t, title, kind in items:
        by.setdefault(t, []).append((title, kind))
    return by


def digest_text(now: datetime.datetime, ok: bool = True) -> str:
    head = f"📰 חדשות היום (יום {HE_DAYS[now.weekday()]} {now.strftime('%d/%m')}, שעון ישראל)"
    if not ok:
        return head + "\n⚠️ לוח החדשות לא נטען. בדקו ידנית לפני שסוחרים."
    items = events_between(now, now + datetime.timedelta(hours=24))
    t1 = [x for x in items if x[2] == "tier1"]
    other = [x for x in items if x[2] != "tier1"]
    lines = [head]
    if t1:
        lines.append(f"🔴 חדשות Tier-1 (חייבים להיות בלי פוזיציה פתוחה {FLAT_MINUTES_BEFORE} דקות לפני):")
        for t, titles in sorted(_group_by_time(t1).items()):
            lines.append(f"‏• {_hm(t)} - " + ", ".join(he_title(x[0]) for x in titles))
    else:
        lines.append("✅ אין חדשות Tier-1 ב-24 השעות הקרובות.")
    if other:
        lines.append("🟡 חדשות חזקות אחרות (אין חובה לסגור, כדאי להיזהר):")
        for t, titles in sorted(_group_by_time(other).items()):
            lines.append(f"‏• {_hm(t)} - " + ", ".join(he_title(x[0]) for x in titles))
    return "\n".join(lines)


def headsup_text(event_time, items, minutes: int, last: bool) -> str:
    at = _hm(event_time)
    titles = ", ".join(he_title(t) for t, _k in items)
    kinds = {k for _t, k in items}
    if "tier1" in kinds:
        t1 = ", ".join(he_title(t) for t, k in items if k == "tier1")
        if last:
            return f"‏🔴 בשעה {at}: {t1}\nחדשת Tier-1: אל תחזיקו פוזיציה פתוחה ואל תפתחו חדשה."
        return f"‏🟠 בשעה {at}: {t1}\nחדשת Tier-1: לסגור פוזיציה {FLAT_MINUTES_BEFORE} דקות לפני ולא לפתוח חדשה סביב ההודעה."
    if "high" in kinds:
        return f"‏🟡 בשעה {at}: {titles}\nחדשה חזקה, לא Tier-1: אין חובה לסגור, כדאי להיזהר בפוזיציה פתוחה."
    return f"‏🟡 בשעה {at}: {titles}\nחדשה בינונית: אין חובה לסגור, שימו לב."


def due_headsups(now_utc):
    """(key, text) for every heads-up due now; same rules as the bridge (30 and 5 minutes, the 30 is
    skipped when the event is already inside the 5-minute window)."""
    out = []
    for horizon in HEADS_UP_MINUTES:
        last = horizon == HEADS_UP_MINUTES[-1]
        window = events_between(now_utc, now_utc + datetime.timedelta(minutes=horizon))
        for t, items in sorted(_group_by_time(window).items()):
            if not last and (t - now_utc).total_seconds() <= HEADS_UP_MINUTES[-1] * 60:
                continue
            mins = max(1, round((t - now_utc).total_seconds() / 60))
            out.append((f"{t.isoformat()}|{horizon}", headsup_text(t, items, mins, last)))
    return out


# ---------------------------------------------------------------- sending
def _state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sent": []}


def _remember(key: str):
    st = _state()
    st["sent"] = (st.get("sent", []) + [key])[-300:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f)


def send(text: str) -> bool:
    mode = os.environ.get("NEWS_MODE", "dry")
    if not is_safe(text):
        print("BLOCKED by safety filter, not sent:", text[:80])
        return False
    if mode == "dry":
        print("[dry]", text, "\n")
        return True
    chat = os.environ.get("NEWS_GROUP_CHAT_ID" if mode == "group" else "NEWS_TEST_CHAT_ID")
    token = os.environ.get("NEWS_BOT_TOKEN")
    if not (chat and token):
        print("missing token or chat id for mode", mode)
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=10)
        return r.ok
    except Exception as exc:
        print("send failed:", type(exc).__name__)
        return False


def run_once(now_il: datetime.datetime):
    ok = load_events()
    st = set(_state().get("sent", []))
    in_window = DIGEST_HOUR_IL <= now_il.hour < DIGEST_HOUR_IL + DIGEST_CATCHUP_HOURS
    key = "digest|" + now_il.date().isoformat()
    if in_window and now_il.weekday() < 5 and key not in st:
        if send(digest_text(now_il, ok)):
            _remember(key)
    if ok:
        for k, text in due_headsups(now_il.astimezone(datetime.timezone.utc)):
            if k not in st and send(text):
                _remember(k)


def loop():
    stop = threading.Event()
    while not stop.is_set():
        try:
            run_once(datetime.datetime.now(IL))
        except Exception as exc:
            print("loop error:", type(exc).__name__, exc)
        stop.wait(30)


def preview():
    ok = load_events(force=True)
    now = datetime.datetime.now(IL)
    print(digest_text(now, ok), "\n")
    upcoming = events_between(now, now + datetime.timedelta(days=7))
    seen = set()
    for t, items in sorted(_group_by_time(upcoming).items()):
        kinds = tuple(sorted({k for _t, k in items}))
        if kinds in seen:
            continue
        seen.add(kinds)
        print(headsup_text(t, items, 30, False), "\n")
        print(headsup_text(t, items, 5, True), "\n")
    print("safety filter:", all(is_safe(digest_text(now, ok)) for _ in [0]))


def test_send():
    """Sends today's summary once to the chosen mode (use NEWS_MODE=me), to check delivery."""
    ok = load_events(force=True)
    print("sent:", send(digest_text(datetime.datetime.now(IL), ok)))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--preview" in sys.argv:
        preview()
    elif "--test-send" in sys.argv:
        test_send()
    elif "--once" in sys.argv:
        run_once(datetime.datetime.now(IL))   # for scheduled runners: check, send what is due, exit
    else:
        loop()
