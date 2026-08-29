import os
import requests
import json

discovered_chat_id = None
last_update_id = 0

def get_persisted_chat_id() -> str:
    """
    Load discovered Telegram chat ID from global variable or from the
    telegram_chat_id column in the database.
    Never reads the phone column — phone numbers and Telegram chat IDs are separate concepts.
    """
    global discovered_chat_id
    if discovered_chat_id:
        return discovered_chat_id
        
    try:
        from app.services.database import load_workers_from_db
        workers = load_workers_from_db()
        for w in workers:
            if w["id"] == "W001" and w.get("telegram_chat_id"):
                chat_id = str(w["telegram_chat_id"]).strip()
                # A Telegram chat ID is all digits (or negative for group chats)
                if chat_id.lstrip("-").isdigit():
                    discovered_chat_id = chat_id
                    return discovered_chat_id
    except Exception as e:
        print(f"[TELEGRAM] Could not load persisted chat ID: {e}")
    return None

def get_telegram_updates() -> list:
    """
    Fetch updates from Telegram Bot API.
    Identifies the chat_id that sent /start and stores/persists it.
    Uses offset to confirm processed updates so the server doesn't get flooded,
    but keeps the discovered chat ID in memory and database config.
    """
    global discovered_chat_id, last_update_id
    raw_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not raw_token:
        return []
    token = raw_token.strip()
    
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {}
    if last_update_id > 0:
        params["offset"] = last_update_id + 1
        
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    if demo_mode:
        params["timeout"] = 1
        http_timeout = 3
    else:
        http_timeout = 10

    try:
        print(f"[TELEGRAM] Calling getUpdates on URL: https://api.telegram.org/bot<HIDDEN>/getUpdates with params={params}")
        response = requests.get(url, params=params, timeout=http_timeout)
        if response.status_code != 200:
            print(f"[TELEGRAM ERROR] getUpdates returned status {response.status_code}: {response.text[:200]}")
            return []
            
        try:
            data = response.json()
        except Exception as json_err:
            print(f"[TELEGRAM ERROR] Failed to parse JSON: {json_err}. Raw response: {response.text[:200]}")
            return []
            
        result = data.get("result", [])
        for update in result:
            update_id = update.get("update_id")
            if update_id and update_id > last_update_id:
                last_update_id = update_id
            
            # Check message, edited_message, and channel_post for /start
            for msg_key in ("message", "edited_message", "channel_post"):
                msg = update.get(msg_key)
                if not msg or not isinstance(msg, dict):
                    continue
                chat = msg.get("chat")
                if not chat or not isinstance(chat, dict):
                    continue
                chat_id = chat.get("id")
                text = msg.get("text")
                if text and isinstance(text, str) and text.strip().startswith("/start") and chat_id is not None:
                    discovered_chat_id = str(chat_id)
                    print(f"[TELEGRAM] Discovered chat ID {discovered_chat_id} from /start!")
                    
                    # Persist to telegram_chat_id column (NOT phone) if DEMO_MODE is true
                    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
                    if demo_mode:
                        from app.services.database import update_worker_telegram_chat_id
                        update_worker_telegram_chat_id("W001", str(chat_id))
                        
                        # Also update active in-memory state (telegram_chat_id, not phone)
                        import app.services.monitor as monitor_module
                        if monitor_module.monitoring_state and "workers" in monitor_module.monitoring_state:
                            for w in monitor_module.monitoring_state["workers"]:
                                if w["id"] == "W001":
                                    w["telegram_chat_id"] = str(chat_id)
        return result
    except Exception as e:
        print(f"[TELEGRAM ERROR] Failed to fetch updates: {e}")
        return []

def send_telegram_message(chat_id: str, message: str) -> dict:
    """
    Send a message to a Telegram chat.

    Routing:
    - If chat_id starts with '+': it is a phone number / simulated demo actor.
      Skip the Telegram API and log as [DEMO TELEGRAM].
    - If chat_id is a pure numeric Telegram chat ID: call the real Telegram API.
    - If no bot token is configured: always simulate.
    """
    raw_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_str = str(chat_id).strip()

    # Simulated actors: phone numbers or missing token
    if not raw_token or chat_str.startswith("+"):
        print(f"[DEMO TELEGRAM] To: {chat_id} | Message: {message}")
        return {
            "success": True,
            "demo": True,
            "message": f"Demo Telegram delivered to {chat_id}",
            "body": message
        }
    token = raw_token.strip()
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in (200, 201):
            return {
                "success": True,
                "demo": False,
                "sid": response.json().get("result", {}).get("message_id"),
                "body": message
            }
        else:
            print(f"[TELEGRAM ERROR] Telegram API failed: {response.text}")
            return {
                "success": False,
                "demo": False,
                "error": response.text,
                "body": message
            }
    except Exception as e:
        print(f"[TELEGRAM EXCEPTION] Failed: {e}")
        return {
            "success": False,
            "demo": False,
            "error": str(e),
            "body": message
        }

def process_telegram_replies() -> list:
    """
    Scan updates for safety check-in replies (SAFE, OK, NOT SAFE)
    and route them to handle_sms_response.
    """
    from app.services.monitor import handle_sms_response
    updates = get_telegram_updates()
    processed = []
    for update in updates:
        message = update.get("message", {})
        chat = message.get("chat", {})
        text = message.get("text", "")
        chat_id = str(chat.get("id", ""))
        
        if not chat_id or not text:
            continue
            
        normalized_text = text.strip().upper()
        if normalized_text.startswith("/start"):
            continue
            
        if normalized_text in ("SAFE", "OK", "NOT SAFE"):
            res = handle_sms_response(chat_id, normalized_text)
            processed.append({
                "chat_id": chat_id,
                "text": normalized_text,
                "result": res
            })
    return processed

def get_telegram_status() -> dict:
    return {
        "token_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "discovered_chat_id": get_persisted_chat_id()
    }
