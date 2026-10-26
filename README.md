# News_Alerts (standalone, news only)

Sends USD economic-news alerts to a Telegram group: morning summary (08:00 Israel time, Mon-Fri), then 30 and 7 minutes before each event, with whether it is Tier-1 (be flat) or not.
Independent of the trading bridge, panel, bots and alerts: no shared code, state or credentials, and it knows nothing about positions or results. A safety filter refuses to send any text containing words like bot / trade / profit / loss / balance.

Modes (`NEWS_MODE`): `dry` (default, prints only) -> `me` (to `NEWS_TEST_CHAT_ID`, Steven only) -> `group` (to `NEWS_GROUP_CHAT_ID`).
Token: `NEWS_BOT_TOKEN`, a separate bot made in BotFather with a neutral name. Set it as an environment variable, never in a file.

Preview without sending: `py news_alerts.py --preview`
Tests: `py -m pytest test_news_alerts.py`
