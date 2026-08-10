"""
Telegram Notifier — alert-only delivery for the order-flow agent.
No auto-trading. Sends a message when a signal crosses the score threshold.
"""

import os
import urllib.request
import urllib.parse
import json

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram_message(text, bot_token=None, chat_id=None):
    token = bot_token or BOT_TOKEN
    chat = chat_id or CHAT_ID
    if not token or not chat:
        return {"ok": False, "error": "Missing bot token or chat id"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML"
    }).encode()

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def format_signal_alert(symbol, result):
    signal = result.get("signal", "NONE")
    score = result.get("score", 0)
    maxs = result.get("max_possible_today", 6)
    sl = result.get("sl_points")
    tgt = result.get("target_points")
    reasons = "\n".join(f"• {r}" for r in result.get("reasons", []))
    return (
        f"<b>Order-Flow Agent Signal</b>\n"
        f"Symbol: {symbol}\n"
        f"Signal: <b>{signal}</b>\n"
        f"Score: {score}/{maxs}\n"
        f"SL: {sl} pts | Target: {tgt} pts\n\n"
        f"{reasons}\n\n"
        f"⚠️ Alert-only. Manual confirmation required before entry."
    )


if __name__ == "__main__":
    # Quick connectivity test
    test_result = send_telegram_message("✅ Order-Flow Agent connected successfully. Alerts will appear here.")
    print(json.dumps(test_result, indent=2))
