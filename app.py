import os
import json
import time
import threading
import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
DB_FILE = 'users.json'

JSONBIN_BIN_ID = os.environ.get('JSONBIN_BIN_ID', '').strip()
JSONBIN_API_KEY = os.environ.get('JSONBIN_API_KEY', '').strip()

RED_BADGE_USER_IDS = {'1795503825490', '1795501800750'}
BLUE_BADGE_USER_IDS = {'1795447002081'}

ALLOWED_AVATARS = ['🦜', '🍐', '🐗', '👑', '⚡']
DEFAULT_AVATAR = '🦜'
GROUP_ICONS = ['🦜', '🍐', '🐗', '👑', '⚡']
DEFAULT_GROUP_ICON = '🦜'
ALLOWED_REACTIONS = ['👍', '👎', '😃', '💩', '🐗']
ALLOWED_DM_POLICIES = ['all', 'nobody']

WEEK_MS = 7 * 24 * 60 * 60 * 1000
_DB_LOCK = threading.RLock()
_DB_CACHE = {'data': None, 'ts': 0.0}
_CACHE_TTL_SEC = 0.15


def is_image_avatar(val: str) -> bool:
    if not isinstance(val, str):
        return False
    s = val.strip()
    return s.startswith('data:image/') and len(s) <= 350000


def normalize_avatar(val: str, fallback: str = DEFAULT_AVATAR) -> str:
    if is_image_avatar(val):
        return val.strip()
    if isinstance(val, str) and val.strip() in ALLOWED_AVATARS:
        return val.strip()
    if is_image_avatar(fallback):
        return fallback.strip()
    return fallback if fallback in ALLOWED_AVATARS else DEFAULT_AVATAR


def normalize_group_icon(val: str, fallback: str = DEFAULT_GROUP_ICON) -> str:
    if is_image_avatar(val):
        return val.strip()
    if isinstance(val, str) and val.strip() in GROUP_ICONS:
        return val.strip()
    return fallback if fallback in GROUP_ICONS else DEFAULT_GROUP_ICON


def normalize_dm_policy(val: str) -> str:
    return val if val in ALLOWED_DM_POLICIES else 'all'


def use_cloud_db() -> bool:
    return bool(JSONBIN_BIN_ID and JSONBIN_API_KEY)


def _clone_db(db_obj):
    return {
        'users': list(db_obj.get('users') or []),
        'messages': list(db_obj.get('messages') or []),
        'groups': list(db_obj.get('groups') or [])
    }


def load_db(force_refresh: bool = False):
    with _DB_LOCK:
        now = time.monotonic()
        if not force_refresh and _DB_CACHE['data'] is not None and (now - _DB_CACHE['ts']) < _CACHE_TTL_SEC:
            return _clone_db(_DB_CACHE['data'])

        default_db = {'users': [], 'messages': [], 'groups': []}

        if use_cloud_db():
            url = f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest'
            headers = {'X-Master-Key': JSONBIN_API_KEY}
            try:
                resp = requests.get(url, headers=headers, timeout=4)
                resp.raise_for_status()
                record = resp.json().get('record', {})

                if isinstance(record, list):
                    parsed = {'users': record, 'messages': [], 'groups': []}
                elif isinstance(record, dict):
                    parsed = {
                        'users': record.get('users') if isinstance(record.get('users'), list) else [],
                        'messages': record.get('messages') if isinstance(record.get('messages'), list) else [],
                        'groups': record.get('groups') if isinstance(record.get('groups'), list) else []
                    }
                else:
                    parsed = default_db
                _DB_CACHE['data'] = _clone_db(parsed)
                _DB_CACHE['ts'] = time.monotonic()
                return _clone_db(parsed)
            except Exception as e:
                print(f'Ошибка загрузки из JSONBin: {e}')
                if _DB_CACHE['data'] is not None:
                    return _clone_db(_DB_CACHE['data'])
                return default_db

        if not os.path.exists(DB_FILE):
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_db, f, ensure_ascii=False, indent=2)
            _DB_CACHE['data'] = _clone_db(default_db)
            _DB_CACHE['ts'] = time.monotonic()
            return _clone_db(default_db)
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    parsed = {'users': data, 'messages': [], 'groups': []}
                elif isinstance(data, dict):
                    parsed = {
                        'users': data.get('users', []),
                        'messages': data.get('messages', []),
                        'groups': data.get('groups', [])
                    }
                else:
                    parsed = default_db
                _DB_CACHE['data'] = _clone_db(parsed)
                _DB_CACHE['ts'] = time.monotonic()
                return _clone_db(parsed)
        except Exception:
            return default_db


def _write_payload_to_storage(payload):
    if use_cloud_db():
        url = f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}'
        headers = {
            'Content-Type': 'application/json',
            'X-Master-Key': JSONBIN_API_KEY
        }
        try:
            resp = requests.put(url, json=payload, headers=headers, timeout=5)
            resp.raise_for_status()
            return
        except Exception as e:
            print(f'Ошибка сохранения в JSONBin: {e}')

    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def save_db(db_data, async_cloud: bool = False):
    payload = _clone_db(db_data)
    with _DB_LOCK:
        _DB_CACHE['data'] = _clone_db(payload)
        _DB_CACHE['ts'] = time.monotonic()

    if async_cloud and use_cloud_db():
        threading.Thread(target=_write_payload_to_storage, args=(payload,), daemon=True).start()
    else:
        _write_payload_to_storage(payload)


def get_badge_color_for_user_id(user_id: str):
    uid = str(user_id or '').strip()
    if uid in RED_BADGE_USER_IDS:
        return 'red'
    if uid in BLUE_BADGE_USER_IDS:
        return 'blue'
    return None


def has_any_checkmark(user_id: str) -> bool:
    return get_badge_color_for_user_id(user_id) is not None


def enrich_user_badge(user: dict) -> dict:
    uid = str((user or {}).get('id') or '').strip()
    badge_color = get_badge_color_for_user_id(uid)
    out = dict(user)
    out['avatar'] = normalize_avatar(out.get('avatar'), DEFAULT_AVATAR)
    out['dm_policy'] = normalize_dm_policy(out.get('dm_policy'))
    out['badge_color'] = badge_color
    out['verified'] = badge_color is not None
    return out


def safe_user(user: dict) -> dict:
    enriched = enrich_user_badge(user)
    return {k: v for k, v in enriched.items() if k != 'password'}


def make_system_group_message(db: dict, group_id: str, text: str, ts_ms: int = None):
    now_ms = ts_ms if ts_ms is not None else int(time.time() * 1000)
    db['messages'].append({
        'id': f'sys_{now_ms}_{len(db["messages"]) + 1}',
        'sender_id': 'system',
        'sender_nick': 'Система',
        'receiver_id': '',
        'group_id': group_id,
        'type': 'system',
        'text': text,
        'timestamp': now_ms,
        'reply_to': None,
        'reactions': {}
    })


def serialize_group(grp: dict, users_by_id: dict) -> dict:
    members = list(grp.get('members') or [])
    owner_id = grp.get('owner_id', '')
    if owner_id and owner_id not in members:
        members.insert(0, owner_id)
    muted_members = [m for m in (grp.get('muted_members') or []) if m in members and m != owner_id]
    member_details = []
    for mid in members:
        u = users_by_id.get(mid)
        member_details.append({
            'id': mid,
            'nickname': u.get('nickname', 'Пользователь') if u else 'Пользователь',
            'avatar': normalize_avatar(u.get('avatar') if u else DEFAULT_AVATAR, DEFAULT_AVATAR),
            'muted': mid in muted_members,
            'isOwner': mid == owner_id
        })
    return {
        'id': grp.get('id', ''),
        'name': grp.get('name', 'Группа'),
        'icon': normalize_group_icon(grp.get('icon'), DEFAULT_GROUP_ICON),
        'owner_id': owner_id,
        'members': members,
        'muted_members': muted_members,
        'member_details': member_details,
        'created_at': grp.get('created_at', 0)
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Голубиная почта</title>
  <style>
    :root {
      --bg-main: #0f172a;
      --bg-surface: #1e293b;
      --bg-elevated: #334155;
      --border-subtle: #334155;
      --accent: #38bdf8;
      --accent-text: #0f172a;
      --bubble-mine: #0284c7;
      --bubble-mine-text: #ffffff;
      --chip-active-bg: #1e3a5f;
      --chip-active-users: #bae6fd;
    }

    body[data-theme="blue"] {
      --bg-main: #0f172a;
      --bg-surface: #1e293b;
      --bg-elevated: #334155;
      --border-subtle: #334155;
      --accent: #38bdf8;
      --accent-text: #0f172a;
      --bubble-mine: #0284c7;
      --bubble-mine-text: #ffffff;
      --chip-active-bg: #1e3a5f;
      --chip-active-users: #bae6fd;
    }

    body[data-theme="green"] {
      --bg-main: #071912;
      --bg-surface: #0f2c20;
      --bg-elevated: #184231;
      --border-subtle: #1e4d39;
      --accent: #34d399;
      --accent-text: #052e16;
      --bubble-mine: #059669;
      --bubble-mine-text: #ffffff;
      --chip-active-bg: #064e3b;
      --chip-active-users: #a7f3d0;
    }

    body[data-theme="red"] {
      --bg-main: #1b090c;
      --bg-surface: #2e1116;
      --bg-elevated: #471921;
      --border-subtle: #571f29;
      --accent: #fb7185;
      --accent-text: #2b060c;
      --bubble-mine: #e11d48;
      --bubble-mine-text: #ffffff;
      --chip-active-bg: #4c0519;
      --chip-active-users: #fecdd3;
    }

    body[data-theme="yellow"] {
      --bg-main: #191405;
      --bg-surface: #2b2209;
      --bg-elevated: #42340e;
      --border-subtle: #524112;
      --accent: #facc15;
      --accent-text: #1c1402;
      --bubble-mine: #ca8a04;
      --bubble-mine-text: #ffffff;
      --chip-active-bg: #422006;
      --chip-active-users: #fef08a;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      -webkit-tap-highlight-color: transparent;
    }

    html, body {
      background: var(--bg-main);
      color: #f8fafc;
      height: 100%;
      width: 100%;
      overflow: hidden;
    }

    #splash-screen {
      position: fixed;
      inset: 0;
      background: linear-gradient(135deg, var(--bg-surface) 0%, var(--bg-main) 100%);
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      z-index: 100;
      transition: opacity 0.6s ease, visibility 0.6s ease;
    }

    #splash-screen.hidden {
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
    }

    .pigeon-container {
      width: 140px;
      height: 140px;
      display: flex;
      justify-content: center;
      align-items: center;
      animation: floatPigeon 2s ease-in-out infinite;
    }

    @keyframes floatPigeon {
      0%, 100% { transform: translateY(0px); }
      50% { transform: translateY(-10px); }
    }

    .wing-back {
      transform-origin: 58px 58px;
      animation: flapBack 0.45s ease-in-out infinite alternate;
    }

    .wing-front {
      transform-origin: 55px 62px;
      animation: flapFront 0.45s ease-in-out infinite alternate;
    }

    @keyframes flapFront {
      0% { transform: rotate(-18deg) scaleY(1); }
      100% { transform: rotate(28deg) scaleY(0.85); }
    }

    @keyframes flapBack {
      0% { transform: rotate(15deg) scaleY(0.9); }
      100% { transform: rotate(-25deg) scaleY(1); }
    }

    .splash-title {
      margin-top: 20px;
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0.5px;
      color: #ffffff;
      text-shadow: 0 4px 15px rgba(56, 189, 248, 0.25);
    }

    #auth-screen {
      width: calc(100% - 32px);
      max-width: 380px;
      padding: 24px;
      display: none;
      flex-direction: column;
      gap: 16px;
      background: var(--bg-surface);
      border-radius: 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.4);
      margin: 16px auto;
      position: relative;
      top: 50%;
      transform: translateY(-50%);
    }

    #auth-screen.active { display: flex; }

    .auth-header { text-align: center; margin-bottom: 4px; }
    .auth-header h2 { font-size: 22px; margin-bottom: 6px; }
    .auth-header p { font-size: 13px; color: #94a3b8; }

    .tabs {
      display: flex;
      background: var(--bg-main);
      border-radius: 12px;
      padding: 4px;
    }

    .tab-btn {
      flex: 1;
      padding: 10px;
      border: none;
      background: transparent;
      color: #94a3b8;
      font-weight: 600;
      border-radius: 9px;
      cursor: pointer;
    }

    .tab-btn.active {
      background: var(--accent);
      color: var(--accent-text);
    }

    .input-group { display: flex; flex-direction: column; gap: 6px; }
    .input-group label { font-size: 13px; color: #cbd5e1; }

    input {
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--border-subtle);
      background: var(--bg-main);
      color: #fff;
      font-size: 16px;
      outline: none;
    }

    input:focus { border-color: var(--accent); }

    .primary-btn {
      width: 100%;
      padding: 13px;
      border: none;
      border-radius: 12px;
      background: var(--accent);
      color: var(--accent-text);
      font-size: 16px;
      font-weight: 700;
      cursor: pointer;
      margin-top: 4px;
    }

    .primary-btn:active { transform: scale(0.98); }

    .error-msg { color: #f87171; font-size: 13px; text-align: center; min-height: 18px; }
    .ok-msg { color: #4ade80; font-size: 13px; text-align: center; min-height: 18px; }

    #main-screen {
      display: none;
      width: 100%;
      height: 100%;
      flex-direction: column;
      background: var(--bg-main);
      position: relative;
    }

    #main-screen.active { display: flex; }
    #main-top-bar.hidden { display: none; }

    .top-bar {
      height: 60px;
      padding: 0 16px;
      background: var(--bg-surface);
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border-subtle);
      flex-shrink: 0;
    }

    .user-badge { display: flex; align-items: center; gap: 10px; min-width: 0; }

    .avatar-circle {
      width: 38px;
      height: 38px;
      border-radius: 50%;
      background: var(--bg-elevated);
      display: flex;
      justify-content: center;
      align-items: center;
      font-size: 21px;
      flex-shrink: 0;
      overflow: hidden;
    }

    .avatar-circle img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }

    .nickname-row { display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 16px; }
    .peer-avatar-clickable { cursor: pointer; }
    .peer-title-clickable { cursor: pointer; }
    .peer-sub { font-size: 11px; color: #94a3b8; font-weight: 500; }

    .verified-circle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .top-actions { display: flex; align-items: center; gap: 8px; }

    .icon-btn {
      width: 40px;
      height: 40px;
      border-radius: 12px;
      border: none;
      background: var(--bg-elevated);
      color: #f8fafc;
      font-size: 19px;
      display: flex;
      justify-content: center;
      align-items: center;
      cursor: pointer;
    }

    .icon-btn:active { background: var(--accent); color: var(--accent-text); }

    #chats-view {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      padding: 12px 16px 88px;
      gap: 8px;
    }

    #chats-view.hidden { display: none; }
    #chats-list { display: flex; flex-direction: column; gap: 8px; }

    .chat-list-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      background: var(--bg-surface);
      border-radius: 14px;
      border: 1px solid var(--border-subtle);
      cursor: pointer;
    }

    .chat-list-item:active { filter: brightness(1.08); }
    .chat-meta { flex: 1; min-width: 0; }

    .chat-last-msg {
      font-size: 13px;
      color: #94a3b8;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-top: 2px;
    }

    .unread-badge {
      min-width: 24px;
      height: 24px;
      padding: 0 7px;
      border-radius: 999px;
      background: #cbd5e1;
      color: #0f172a;
      font-size: 12px;
      font-weight: 700;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .fab-create-group {
      position: fixed;
      right: 20px;
      bottom: 22px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      border: none;
      background: #22c55e;
      color: #ffffff;
      font-size: 24px;
      display: none;
      align-items: center;
      justify-content: center;
      box-shadow: 0 8px 24px rgba(34, 197, 94, 0.35);
      cursor: pointer;
      z-index: 25;
    }

    .fab-create-group.visible { display: flex; }
    .fab-create-group:active { transform: scale(0.95); background: #16a34a; }

    .empty-workspace {
      flex: 1;
      display: none;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      color: #64748b;
      text-align: center;
      padding: 20px;
    }

    .empty-workspace span { font-size: 48px; margin-bottom: 12px; opacity: 0.7; }

    #search-view {
      position: fixed;
      inset: 0;
      background: var(--bg-main);
      display: none;
      flex-direction: column;
      gap: 12px;
      padding: 14px 16px;
      z-index: 35;
      overflow-y: auto;
    }

    #search-view.active { display: flex; }

    .search-top-row { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }

    .back-btn {
      padding: 10px 14px;
      border-radius: 12px;
      border: none;
      background: var(--bg-elevated);
      color: #f8fafc;
      font-weight: 600;
      cursor: pointer;
      flex-shrink: 0;
    }

    .search-results { display: flex; flex-direction: column; gap: 8px; }

    .search-user-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px;
      background: var(--bg-surface);
      border-radius: 14px;
      border: 1px solid var(--border-subtle);
      cursor: pointer;
    }

    .search-user-item:active { filter: brightness(1.08); }
    .search-user-left { display: flex; align-items: center; gap: 10px; }
    .open-chat-tag { font-size: 12px; color: var(--accent); font-weight: 600; }
    .search-empty { font-size: 13px; color: #94a3b8; padding: 8px 2px; }

    #chat-room-view {
      position: fixed;
      inset: 0;
      width: 100%;
      height: 100%;
      background: var(--bg-main);
      display: none;
      flex-direction: column;
      z-index: 40;
    }

    #chat-room-view.active { display: flex; }

    .chat-messages {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      user-select: none;
      -webkit-user-select: none;
      background: var(--bg-main);
    }

    .day-divider {
      align-self: center;
      margin: 6px 0;
      padding: 4px 12px;
      border-radius: 999px;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      color: #cbd5e1;
      font-size: 12px;
      font-weight: 600;
      flex-shrink: 0;
    }

    .system-msg-center {
      align-self: center;
      margin: 4px 0;
      padding: 5px 14px;
      border-radius: 999px;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      color: #cbd5e1;
      font-size: 12px;
      font-weight: 600;
      text-align: center;
      flex-shrink: 0;
    }

    .msg-wrapper { display: flex; flex-direction: column; max-width: 82%; flex-shrink: 0; }
    .msg-wrapper.mine { align-self: flex-end; align-items: flex-end; }
    .msg-wrapper.theirs { align-self: flex-start; align-items: flex-start; }

    .msg-sender-name {
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 3px;
      padding-left: 4px;
    }

    .msg-bubble {
      width: fit-content;
      max-width: 100%;
      padding: 10px 14px;
      border-radius: 16px;
      line-height: 1.35;
      word-break: break-word;
      cursor: pointer;
      display: flex;
      flex-direction: column;
    }

    .msg-content-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; }
    .msg-text { flex: 1; }

    .msg-time {
      font-size: 11px;
      line-height: 1;
      opacity: 0.75;
      white-space: nowrap;
      align-self: flex-end;
      margin-top: 2px;
    }

    .msg-size-small { font-size: 13px; }
    .msg-size-medium { font-size: 15px; }
    .msg-size-large { font-size: 18px; }

    .msg-mine { background: var(--bubble-mine); color: var(--bubble-mine-text); border-bottom-right-radius: 4px; }
    .msg-theirs { background: var(--bg-surface); color: #f8fafc; border: 1px solid var(--border-subtle); border-bottom-left-radius: 4px; }

    .msg-reply-quote {
      font-size: 12px;
      padding: 6px 8px;
      margin-bottom: 6px;
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.25);
      border-left: 3px solid var(--accent);
      color: #f8fafc;
    }

    .msg-reactions-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }

    .reaction-chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 8px;
      border-radius: 999px;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      color: #e2e8f0;
      font-size: 12px;
      cursor: pointer;
      line-height: 1.2;
      max-width: 100%;
    }

    .reaction-chip.active-mine { background: var(--chip-active-bg); border-color: var(--accent); color: #ffffff; }
    .reaction-chip-emoji { font-size: 13px; }
    .reaction-chip-count { font-weight: 700; font-size: 11px; }

    .reaction-chip-users {
      color: #94a3b8;
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 160px;
    }

    .reaction-chip.active-mine .reaction-chip-users { color: var(--chip-active-users); }

    .reply-banner {
      display: none;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 14px;
      background: var(--bg-surface);
      border-top: 1px solid var(--border-subtle);
      font-size: 13px;
      color: #cbd5e1;
      flex-shrink: 0;
    }

    .reply-banner.active { display: flex; }
    .reply-banner-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .reply-cancel-btn { background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 0 4px; }

    .chat-input-bar {
      padding: 10px 12px;
      background: var(--bg-surface);
      border-top: 1px solid var(--border-subtle);
      display: flex;
      gap: 8px;
      align-items: center;
      flex-shrink: 0;
    }

    .muted-chat-notice {
      padding: 13px 16px;
      background: var(--bg-surface);
      border-top: 1px solid var(--border-subtle);
      text-align: center;
      font-size: 13px;
      color: #fca5a5;
      font-weight: 600;
      flex-shrink: 0;
    }

    .send-btn {
      padding: 12px 16px;
      border-radius: 12px;
      border: none;
      background: var(--accent);
      color: var(--accent-text);
      font-weight: 700;
      cursor: pointer;
      flex-shrink: 0;
    }

    .copy-toast {
      position: fixed;
      bottom: 80px;
      left: 50%;
      transform: translateX(-50%);
      background: var(--bg-surface);
      color: #f8fafc;
      border: 1px solid var(--accent);
      padding: 8px 16px;
      border-radius: 12px;
      font-size: 13px;
      z-index: 90;
      display: none;
    }

    .copy-toast.active { display: block; }

    .full-scene {
      position: fixed;
      inset: 0;
      background: var(--bg-main);
      display: none;
      flex-direction: column;
      z-index: 48;
      overflow-y: auto;
    }

    .full-scene.active { display: flex; }

    .scene-body {
      flex: 1;
      padding: 18px 16px 32px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      max-width: 480px;
      width: 100%;
      margin: 0 auto;
    }

    .scene-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: 18px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .action-sheet-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.65);
      display: none;
      justify-content: center;
      align-items: flex-end;
      padding: 16px;
      z-index: 70;
    }

    .action-sheet-overlay.active { display: flex; }

    .action-sheet {
      width: 100%;
      max-width: 440px;
      max-height: 85vh;
      overflow-y: auto;
      background: var(--bg-surface);
      border-radius: 20px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      border: 1px solid var(--border-subtle);
    }

    .action-sheet-title { font-size: 14px; font-weight: 700; color: #f8fafc; text-align: center; padding-bottom: 2px; }

    .group-info-card {
      background: var(--bg-main);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
      color: #cbd5e1;
    }

    .emoji-picker-row {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 8px;
      background: var(--bg-main);
      padding: 10px;
      border-radius: 14px;
      border: 1px solid var(--border-subtle);
    }

    .group-icon-grid {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 8px;
      background: var(--bg-main);
      padding: 10px;
      border-radius: 14px;
      border: 1px solid var(--border-subtle);
    }

    .emoji-pick-btn {
      height: 44px;
      border-radius: 10px;
      border: 2px solid transparent;
      background: var(--bg-surface);
      font-size: 21px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }

    .emoji-pick-btn.selected { border-color: #22c55e; background: #14532d; }

    .photo-picker-row {
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--bg-main);
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--border-subtle);
    }

    .photo-upload-btn {
      padding: 9px 12px;
      border-radius: 10px;
      border: 1px solid var(--accent);
      background: var(--chip-active-bg);
      color: #ffffff;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }

    .photo-status-text {
      font-size: 12px;
      color: #cbd5e1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .member-select-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 190px;
      overflow-y: auto;
      background: var(--bg-main);
      padding: 8px;
      border-radius: 12px;
      border: 1px solid var(--border-subtle);
    }

    .member-check-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 10px;
      border-radius: 10px;
      background: var(--bg-surface);
    }

    .member-check-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .member-check-item input[type="checkbox"] { width: 18px; height: 18px; accent-color: #22c55e; }

    .member-row-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

    .mini-action-btn {
      padding: 6px 9px;
      border-radius: 8px;
      border: none;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      background: var(--bg-elevated);
      color: #f8fafc;
    }

    .mini-action-btn.muted-on { background: #92400e; color: #fde68a; }
    .mini-action-btn.kick { background: #7f1d1d; color: #fecaca; }

    .sheet-reactions-summary {
      background: var(--bg-main);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 5px;
      font-size: 12px;
      color: #cbd5e1;
      max-height: 130px;
      overflow-y: auto;
    }

    .sheet-reactions-summary:empty { display: none; }
    .sheet-reaction-line { display: flex; align-items: center; gap: 8px; line-height: 1.3; }

    .sheet-btn {
      width: 100%;
      padding: 12px;
      border-radius: 12px;
      border: none;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      background: var(--bg-elevated);
      color: #f8fafc;
    }

    .sheet-btn.green { background: #22c55e; color: #0f172a; font-weight: 700; }
    .sheet-btn.reply { background: var(--bubble-mine); color: #ffffff; }
    .sheet-btn.copy { background: var(--chip-active-bg); color: var(--chip-active-users); }
    .sheet-btn.warn { background: #78350f; color: #fde68a; }
    .sheet-btn.delete { background: #7f1d1d; color: #fecaca; }
    .sheet-btn.cancel { background: var(--bg-main); color: #94a3b8; }

    #settings-screen {
      position: fixed;
      inset: 0;
      background: var(--bg-main);
      display: none;
      flex-direction: column;
      z-index: 45;
      overflow-y: auto;
    }

    #settings-screen.active { display: flex; }

    .settings-tabs-bar {
      display: flex;
      background: var(--bg-surface);
      padding: 8px 12px;
      gap: 6px;
      border-bottom: 1px solid var(--border-subtle);
      flex-shrink: 0;
    }

    .settings-tab-btn {
      flex: 1;
      padding: 10px 6px;
      border-radius: 12px;
      border: none;
      background: var(--bg-main);
      color: #94a3b8;
      font-weight: 700;
      font-size: 12px;
      cursor: pointer;
      white-space: nowrap;
    }

    .settings-tab-btn.active { background: var(--accent); color: var(--accent-text); }

    .settings-content {
      flex: 1;
      padding: 18px 16px 28px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      max-width: 480px;
      width: 100%;
      margin: 0 auto;
    }

    .settings-section {
      display: none;
      flex-direction: column;
      gap: 16px;
      background: var(--bg-surface);
      padding: 18px;
      border-radius: 18px;
      border: 1px solid var(--border-subtle);
    }

    .settings-section.active { display: flex; }

    .id-box {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: var(--bg-main);
      border: 1px solid var(--border-subtle);
      cursor: pointer;
    }

    .id-box-value {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      color: #e2e8f0;
      user-select: all;
      word-break: break-all;
    }

    .id-copy-tag {
      font-size: 12px;
      font-weight: 700;
      color: var(--accent);
      flex-shrink: 0;
    }

    .avatar-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 6px; }

    .avatar-option {
      height: 46px;
      border-radius: 12px;
      background: var(--bg-main);
      border: 2px solid transparent;
      font-size: 23px;
      display: flex;
      justify-content: center;
      align-items: center;
      cursor: pointer;
    }

    .avatar-option.selected { border-color: var(--accent); background: var(--chip-active-bg); }
    .size-selector { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }

    .size-btn {
      padding: 11px 8px;
      border-radius: 12px;
      border: 2px solid var(--border-subtle);
      background: var(--bg-main);
      color: #e2e8f0;
      font-weight: 600;
      cursor: pointer;
    }

    .size-btn.selected { border-color: var(--accent); background: var(--chip-active-bg); color: #ffffff; }

    .privacy-selector {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      margin-top: 4px;
    }

    .privacy-btn {
      padding: 12px 10px;
      border-radius: 12px;
      border: 2px solid var(--border-subtle);
      background: var(--bg-main);
      color: #e2e8f0;
      font-weight: 700;
      font-size: 14px;
      cursor: pointer;
      text-align: center;
    }

    .privacy-btn.selected {
      border-color: var(--accent);
      background: var(--chip-active-bg);
      color: #ffffff;
    }

    .theme-selector {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      margin-top: 4px;
    }

    .theme-btn {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px;
      border-radius: 12px;
      border: 2px solid var(--border-subtle);
      background: var(--bg-main);
      color: #f8fafc;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      text-align: left;
    }

    .theme-btn.selected {
      border-color: var(--accent);
      background: var(--chip-active-bg);
    }

    .theme-swatch {
      width: 16px;
      height: 16px;
      border-radius: 50%;
      flex-shrink: 0;
      border: 1px solid rgba(255,255,255,0.25);
    }

    .preview-box {
      padding: 14px;
      border-radius: 14px;
      background: var(--bg-main);
      border: 1px dashed var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .preview-label { font-size: 12px; color: #94a3b8; }
    .hint-text { font-size: 12px; color: #94a3b8; }

    .logout-btn {
      background: var(--bg-elevated);
      color: #f87171;
      border: none;
      padding: 12px;
      border-radius: 12px;
      font-weight: 600;
      cursor: pointer;
      margin-top: 4px;
    }
  </style>
</head>
<body data-theme="blue">
  <div id="splash-screen">
    <div class="pigeon-container">
      <svg viewBox="0 0 120 120" width="130" height="130">
        <path class="wing-back" d="M58 58 C42 25, 18 28, 25 52 C32 62, 48 62, 58 58 Z" fill="#cbd5e1" />
        <path d="M26 74 L8 86 L16 68 Z" fill="#e2e8f0" />
        <path d="M24 72 C36 88, 74 88, 84 66 C90 54, 88 38, 78 34 C70 31, 64 38, 62 46 C52 52, 34 58, 24 72 Z" fill="#ffffff" />
        <path d="M86 40 L97 44 L86 47 Z" fill="#f59e0b" />
        <circle cx="79" cy="40" r="2.5" fill="#0f172a" />
        <path class="wing-front" d="M55 62 C36 22, 10 32, 22 58 C30 70, 46 68, 55 62 Z" fill="#ffffff" stroke="#e2e8f0" stroke-width="1.5" />
      </svg>
    </div>
    <div class="splash-title">Голубиная почта</div>
  </div>

  <div id="auth-screen">
    <div class="auth-header">
      <h2>🕊️ Голубиная почта</h2>
      <p>Создай аккаунт или войди в свой профиль</p>
    </div>

    <div class="tabs">
      <button class="tab-btn active" id="tab-register" onclick="switchMode('register')">Регистрация</button>
      <button class="tab-btn" id="tab-login" onclick="switchMode('login')">Вход</button>
    </div>

    <div class="input-group">
      <label>Никнейм</label>
      <input type="text" id="auth-nick" placeholder="Придумай никнейм..." maxlength="20" />
    </div>

    <div class="input-group">
      <label>Пароль</label>
      <input type="password" id="auth-pass" placeholder="Введи пароль..." />
    </div>

    <div class="error-msg" id="auth-error"></div>
    <button class="primary-btn" id="auth-submit-btn" onclick="submitAuth()">Зарегистрироваться</button>
  </div>

  <div id="main-screen">
    <header class="top-bar" id="main-top-bar">
      <div class="user-badge">
        <div class="avatar-circle" id="header-avatar">🦜</div>
        <div class="nickname-row">
          <span id="header-nick">Пользователь</span>
          <span id="header-verified"></span>
        </div>
      </div>

      <div class="top-actions">
        <button class="icon-btn" id="search-toggle-btn" onclick="openSearchScreen()" title="Поиск пользователей">🔍</button>
        <button class="icon-btn" onclick="openSettingsScreen()" title="Настройки">⚙️</button>
      </div>
    </header>

    <section id="chats-view">
      <div id="chats-list"></div>
      <div class="empty-workspace" id="empty-chats-placeholder">
        <span>🕊️</span>
        <p>Пока чатов нет.<br>Нажми на лупу сверху или на зелёный карандаш справа внизу.</p>
      </div>
    </section>

    <button type="button" class="fab-create-group" id="fab-create-group" onclick="openCreateGroupScene()" title="Создать группу">✏️</button>
  </div>

  <section id="search-view">
    <div class="search-top-row">
      <button class="back-btn" onclick="closeSearchScreen()">← Назад</button>
      <input type="text" id="search-input" placeholder="Поиск пользователей..." oninput="runSearch()" />
    </div>
    <div class="search-results" id="search-results">
      <div class="search-empty">Начни вводить имя пользователя</div>
    </div>
  </section>

  <section id="settings-screen">
    <header class="top-bar">
      <div class="user-badge">
        <button class="back-btn" onclick="closeSettingsScreen()">← Назад</button>
        <div class="nickname-row"><span>Настройки</span></div>
      </div>
    </header>

    <div class="settings-tabs-bar">
      <button class="settings-tab-btn active" id="stab-main" onclick="switchSettingsTab('main')">Основная</button>
      <button class="settings-tab-btn" id="stab-custom" onclick="switchSettingsTab('custom')">Кастомизация</button>
      <button class="settings-tab-btn" id="stab-privacy" onclick="switchSettingsTab('privacy')">Конфиденциальность</button>
    </div>

    <div class="settings-content">
      <div class="settings-section active" id="ssec-main">
        <div class="input-group">
          <label>Ваш ID</label>
          <div class="id-box" onclick="copyCurrentUserId()" title="Нажми, чтобы скопировать ID">
            <span class="id-box-value" id="settings-user-id">—</span>
            <span class="id-copy-tag">Копировать</span>
          </div>
        </div>

        <div class="input-group">
          <label>Аватарка: фотография или 1 из 5 эмодзи</label>
          <div class="photo-picker-row">
            <input type="file" id="user-avatar-file" accept="image/*" style="display:none;" onchange="handleUserAvatarFile(event)" />
            <button type="button" class="photo-upload-btn" onclick="document.getElementById('user-avatar-file').click()">📷 Фото</button>
            <span class="photo-status-text" id="user-avatar-photo-status">Эмодзи не выбрано фото</span>
          </div>
          <div class="avatar-grid" id="avatar-grid"></div>
        </div>

        <div class="input-group">
          <label>Никнейм</label>
          <input type="text" id="settings-nick" maxlength="20" />
          <span class="hint-text" id="nick-timer-hint">Никнейм можно менять 1 раз в неделю.</span>
        </div>

        <div class="error-msg" id="settings-error"></div>
        <div class="ok-msg" id="settings-ok"></div>

        <button class="primary-btn" onclick="saveMainSettings()">Сохранить профиль</button>
        <button class="logout-btn" onclick="logout()">Выйти из аккаунта</button>
      </div>

      <div class="settings-section" id="ssec-custom">
        <div class="input-group">
          <label>Тема приложения</label>
          <div class="theme-selector">
            <button type="button" class="theme-btn" data-theme="blue" onclick="selectAppTheme('blue')">
              <span class="theme-swatch" style="background:#38bdf8;"></span>
              <span>Синий (обычный)</span>
            </button>
            <button type="button" class="theme-btn" data-theme="green" onclick="selectAppTheme('green')">
              <span class="theme-swatch" style="background:#34d399;"></span>
              <span>Зелёный</span>
            </button>
            <button type="button" class="theme-btn" data-theme="red" onclick="selectAppTheme('red')">
              <span class="theme-swatch" style="background:#fb7185;"></span>
              <span>Красный</span>
            </button>
            <button type="button" class="theme-btn" data-theme="yellow" onclick="selectAppTheme('yellow')">
              <span class="theme-swatch" style="background:#facc15;"></span>
              <span>Жёлтый</span>
            </button>
          </div>
        </div>

        <div class="input-group">
          <label>Размер сообщений</label>
          <div class="size-selector">
            <button type="button" class="size-btn" data-size="small" onclick="selectMsgSize('small')">Маленький</button>
            <button type="button" class="size-btn" data-size="medium" onclick="selectMsgSize('medium')">Средний</button>
            <button type="button" class="size-btn" data-size="large" onclick="selectMsgSize('large')">Большой</button>
          </div>
        </div>

        <div class="preview-box">
          <div class="preview-label">Предпросмотр сообщения:</div>
          <div class="msg-bubble msg-mine" id="custom-preview-bubble" style="max-width: 100%; cursor: default;">
            <div class="msg-content-row">
              <span class="msg-text">Привет! Голубиная почта летит быстро</span>
              <span class="msg-time">12:00</span>
            </div>
          </div>
        </div>

        <div class="ok-msg" id="custom-saved-msg"></div>
        <button class="primary-btn" onclick="saveCustomization()">Применить кастомизацию</button>
      </div>

      <div class="settings-section" id="ssec-privacy">
        <div class="input-group">
          <label>Кто может писать вам</label>
          <div class="privacy-selector">
            <button type="button" class="privacy-btn" id="privacy-all-btn" onclick="selectDmPolicy('all')">Все</button>
            <button type="button" class="privacy-btn" id="privacy-nobody-btn" onclick="selectDmPolicy('nobody')">Никто</button>
          </div>
          <span class="hint-text">Если выбрано «Никто», другие пользователи не смогут написать вам в личку. Вы сами сможете писать другим, если у них не выбрано «Никто».</span>
        </div>

        <div class="error-msg" id="privacy-error"></div>
        <div class="ok-msg" id="privacy-ok"></div>
        <button class="primary-btn" onclick="savePrivacySettings()">Сохранить конфиденциальность</button>
      </div>
    </div>
  </section>

  <!-- Отдельная сцена создания группы -->
  <section id="create-group-scene" class="full-scene">
    <header class="top-bar">
      <div class="user-badge">
        <button class="back-btn" onclick="closeCreateGroupScene()">← Назад</button>
        <div class="nickname-row"><span>Создать группу</span></div>
      </div>
    </header>

    <div class="scene-body">
      <div class="scene-card">
        <div class="input-group">
          <label>Название группы</label>
          <input type="text" id="new-group-name" placeholder="Например: Сквад" maxlength="32" />
        </div>
        <div class="input-group">
          <label>Иконка группы: фотография или 1 из 5 эмодзи</label>
          <div class="photo-picker-row">
            <input type="file" id="new-group-photo-file" accept="image/*" style="display:none;" onchange="handleGroupPhotoFile(event, 'create')" />
            <button type="button" class="photo-upload-btn" onclick="document.getElementById('new-group-photo-file').click()">📷 Фото</button>
            <span class="photo-status-text" id="new-group-photo-status">Выбран эмодзи</span>
          </div>
          <div class="group-icon-grid" id="create-group-icon-grid"></div>
        </div>
        <div class="input-group">
          <label>Участники (с кем уже переписывались)</label>
          <div class="member-select-list" id="create-group-members"></div>
        </div>
        <div class="error-msg" id="create-group-error"></div>
        <button type="button" class="sheet-btn green" onclick="submitCreateGroup()">Создать группу</button>
      </div>
    </div>
  </section>

  <!-- Отдельная сцена настроек чата (группа или 1 на 1) -->
  <section id="chat-settings-scene" class="full-scene">
    <header class="top-bar">
      <div class="user-badge">
        <button class="back-btn" onclick="closeChatSettingsScene()">← Назад</button>
        <div class="nickname-row"><span id="chat-scene-title">Настройки чата</span></div>
      </div>
    </header>

    <div class="scene-body">
      <div id="direct-chat-settings-card" style="display:none; flex-direction:column; gap:12px;">
        <button type="button" class="sheet-btn delete" onclick="deleteDirectChat()">🗑️ Удалить чат</button>
      </div>

      <div class="scene-card" id="group-chat-settings-card" style="display:none;">
        <div class="group-info-card" id="group-readonly-info" style="display:none;"></div>

        <div id="group-owner-controls" style="display:flex; flex-direction:column; gap:12px;">
          <div class="input-group">
            <label>Название группы</label>
            <input type="text" id="edit-group-name" maxlength="32" />
          </div>

          <div class="input-group">
            <label>Иконка группы: фотография или 1 из 5 эмодзи</label>
            <div class="photo-picker-row">
              <input type="file" id="edit-group-photo-file" accept="image/*" style="display:none;" onchange="handleGroupPhotoFile(event, 'edit')" />
              <button type="button" class="photo-upload-btn" onclick="document.getElementById('edit-group-photo-file').click()">📷 Фото</button>
              <span class="photo-status-text" id="edit-group-photo-status">Выбран эмодзи</span>
            </div>
            <div class="group-icon-grid" id="edit-group-icon-grid"></div>
          </div>

          <button type="button" class="sheet-btn green" onclick="saveGroupDetails()">Сохранить название и иконку</button>

          <div class="input-group">
            <label>Участники группы (мут / удаление)</label>
            <div class="member-select-list" id="current-group-members-list"></div>
          </div>

          <div class="input-group">
            <label>Добавить участников</label>
            <div class="member-select-list" id="add-group-members-list"></div>
          </div>
          <button type="button" class="sheet-btn reply" onclick="addSelectedMembersToGroup()">Добавить выбранных</button>

          <button type="button" class="sheet-btn delete" onclick="deleteCurrentGroup()">Удалить группу</button>
        </div>

        <button type="button" class="sheet-btn warn" onclick="leaveCurrentGroup()">🚪 Выйти из группы</button>
      </div>
    </div>
  </section>

  <div id="chat-room-view">
    <header class="top-bar">
      <div class="user-badge">
        <button class="back-btn" onclick="closeChatRoom()">←</button>
        <div class="avatar-circle peer-avatar-clickable" id="peer-avatar" onclick="handlePeerHeaderClick()">🦜</div>
        <div id="peer-header-info" class="peer-title-clickable" onclick="handlePeerHeaderClick()">
          <div class="nickname-row">
            <span id="peer-nick">Пользователь</span>
            <span id="peer-verified"></span>
          </div>
          <div class="peer-sub" id="peer-sub" style="display:none;"></div>
        </div>
      </div>
    </header>

    <div class="chat-messages" id="chat-messages"></div>

    <div class="reply-banner" id="reply-banner">
      <div class="reply-banner-text" id="reply-banner-text">Ответ на сообщение</div>
      <button type="button" class="reply-cancel-btn" onclick="cancelReply()">&times;</button>
    </div>

    <div class="muted-chat-notice" id="muted-chat-notice" style="display:none;">
      🔇 Вам запрещено писать сообщения в этой группе
    </div>

    <form class="chat-input-bar" id="chat-form" onsubmit="sendChatMessage(event)">
      <input
        type="text"
        id="chat-message-input"
        placeholder="Написать сообщение..."
        maxlength="1000"
        autocomplete="off"
        onfocus="handleComposerFocus()"
      />
      <button type="submit" class="send-btn" onpointerdown="handleSendPointerDown(event)">➤</button>
    </form>
  </div>

  <div class="action-sheet-overlay" id="msg-action-sheet" onclick="closeMessageMenu(event)">
    <div class="action-sheet" onclick="event.stopPropagation()">
      <div class="action-sheet-title" id="action-sheet-preview">Что сделать с сообщением?</div>

      <div class="emoji-picker-row" id="emoji-picker-row">
        <button type="button" class="emoji-pick-btn" data-emoji="👍" onclick="toggleReactionOnSelected('👍')">👍</button>
        <button type="button" class="emoji-pick-btn" data-emoji="👎" onclick="toggleReactionOnSelected('👎')">👎</button>
        <button type="button" class="emoji-pick-btn" data-emoji="😃" onclick="toggleReactionOnSelected('😃')">😃</button>
        <button type="button" class="emoji-pick-btn" data-emoji="💩" onclick="toggleReactionOnSelected('💩')">💩</button>
        <button type="button" class="emoji-pick-btn" data-emoji="🐗" onclick="toggleReactionOnSelected('🐗')">🐗</button>
      </div>

      <div class="sheet-reactions-summary" id="sheet-reactions-summary"></div>

      <button type="button" class="sheet-btn reply" onclick="triggerReplyMessage()">↩️ Ответить</button>
      <button type="button" class="sheet-btn copy" onclick="triggerCopyMessage()">📋 Копировать сообщение</button>
      <button type="button" class="sheet-btn delete" id="sheet-delete-msg-btn" onclick="triggerDeleteMessage()">🗑️ Удалить</button>
      <button type="button" class="sheet-btn cancel" onclick="closeMessageMenu()">Отмена</button>
    </div>
  </div>

  <div class="copy-toast" id="copy-toast">Сообщение скопировано</div>

  <script>
    let authMode = 'register';
    let currentUser = null;
    let activePeer = null;
    let chatPollTimer = null;
    let chatsListPollTimer = null;
    let isFetchingMessages = false;
    let isFetchingChatsList = false;
    let currentMessagesCache = [];
    let selectedMessage = null;
    let replyingToMessage = null;
    let selectedAvatar = '🦜';
    let selectedDmPolicy = 'all';
    let customization = { msgSize: 'medium', theme: 'blue' };
    let selectedNewGroupIcon = '🦜';
    let editingGroupState = null;
    let selectedEditGroupIcon = '🦜';

    const RED_BADGE_IDS = new Set(['1795503825490', '1795501800750']);
    const BLUE_BADGE_IDS = new Set(['1795447002081']);

    const REACTION_EMOJIS = ['👍', '👎', '😃', '💩', '🐗'];
    const GROUP_ICONS = ['🦜', '🍐', '🐗', '👑', '⚡'];
    const ALLOWED_THEMES = ['blue', 'green', 'red', 'yellow'];
    const ALLOWED_AVATARS = ['🦜', '🍐', '🐗', '👑', '⚡'];
    const DEFAULT_AVATAR = '🦜';
    const MONTHS_RU = [
      'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
      'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
    ];

    function isImageAvatar(val) {
      return typeof val === 'string' && val.trim().startsWith('data:image/');
    }

    function normalizeAvatar(val, fallback = DEFAULT_AVATAR) {
      if (isImageAvatar(val)) return val.trim();
      if (typeof val === 'string' && ALLOWED_AVATARS.includes(val.trim())) return val.trim();
      if (isImageAvatar(fallback)) return fallback.trim();
      return ALLOWED_AVATARS.includes(fallback) ? fallback : DEFAULT_AVATAR;
    }

    function renderAvatarContent(val, fallback = DEFAULT_AVATAR) {
      const norm = normalizeAvatar(val, fallback);
      if (isImageAvatar(norm)) {
        return `<img src="${escapeHtml(norm)}" alt="avatar" />`;
      }
      return escapeHtml(norm);
    }

    function isAnyOverlaySceneOpen() {
      return Boolean(
        document.getElementById('create-group-scene').classList.contains('active') ||
        document.getElementById('chat-settings-scene').classList.contains('active') ||
        document.getElementById('settings-screen').classList.contains('active') ||
        document.getElementById('search-view').classList.contains('active')
      );
    }

    function isGroupOwner(groupObj) {
      if (!groupObj || !currentUser || !currentUser.id) return false;
      return String(groupObj.ownerId || groupObj.owner_id || '') === String(currentUser.id);
    }

    function isUserMutedInGroup(groupObj, userId) {
      if (!groupObj || !groupObj.isGroup) return false;
      if (String(groupObj.ownerId || groupObj.owner_id || '') === String(userId)) return false;
      const mutedList = Array.isArray(groupObj.mutedMembers || groupObj.muted_members)
        ? (groupObj.mutedMembers || groupObj.muted_members)
        : [];
      return mutedList.includes(userId);
    }

    function canDeleteSelectedMessage() {
      if (!selectedMessage || !currentUser || !activePeer) return false;
      if (selectedMessage.type === 'system' || selectedMessage.sender_id === 'system') return false;
      if (activePeer.isGroup) {
        return isGroupOwner(activePeer);
      }
      return true;
    }

    function makeCheckmarkBadge(bgColor) {
      return `
        <span class="verified-circle" style="background:${bgColor};" title="Подтверждённый аккаунт">
          <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3.5 8.5 6.5 11.5 12.5 4.5" />
          </svg>
        </span>
      `;
    }

    function getBadgeHtmlForUser(user) {
      if (!user || user.isGroup) return '';
      const uid = String(user.id || '').trim();
      if (RED_BADGE_IDS.has(uid) || user.badge_color === 'red') {
        return makeCheckmarkBadge('#ef4444');
      }
      if (BLUE_BADGE_IDS.has(uid) || user.badge_color === 'blue') {
        return makeCheckmarkBadge('#38bdf8');
      }
      return '';
    }

    function formatMsgTime(ts) {
      const d = new Date(Number(ts) || Date.now());
      if (Number.isNaN(d.getTime())) return '00:00';
      return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    function getDayKey(ts) {
      const d = new Date(Number(ts) || Date.now());
      if (Number.isNaN(d.getTime())) return '';
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    }

    function formatDayLabel(ts) {
      const d = new Date(Number(ts) || Date.now());
      if (Number.isNaN(d.getTime())) return '';
      return `${d.getDate()} ${MONTHS_RU[d.getMonth()]}`;
    }

    function getLastReadKey(uid, pid) { return `pigeon_last_read_${uid}_${pid}`; }
    function getLastReadTime(uid, pid) {
      const raw = localStorage.getItem(getLastReadKey(uid, pid));
      return raw ? Number(raw) || 0 : 0;
    }

    function markChatAsRead(uid, pid, latestTs = Date.now()) {
      if (!uid || !pid) return;
      const nextVal = Math.max(getLastReadTime(uid, pid), Number(latestTs) || Date.now());
      localStorage.setItem(getLastReadKey(uid, pid), String(nextVal));
    }

    function getChatsCacheKey(uid) { return `pigeon_chats_cache_${uid}`; }
    function readChatsCache(uid) {
      try {
        const parsed = JSON.parse(localStorage.getItem(getChatsCacheKey(uid)) || '[]');
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) { return []; }
    }
    function writeChatsCache(uid, chats) {
      try { localStorage.setItem(getChatsCacheKey(uid), JSON.stringify(chats)); } catch (e) {}
    }

    function resolveAvatar(userId, fallbackAvatar) {
      if (currentUser && userId && currentUser.id === userId && currentUser.avatar) {
        return normalizeAvatar(currentUser.avatar, DEFAULT_AVATAR);
      }
      if (fallbackAvatar) {
        const norm = normalizeAvatar(fallbackAvatar, DEFAULT_AVATAR);
        if (userId) localStorage.setItem(`pigeon_avatar_${userId}`, norm);
        return norm;
      }
      if (userId) {
        const localAv = localStorage.getItem(`pigeon_avatar_${userId}`);
        if (localAv) return normalizeAvatar(localAv, DEFAULT_AVATAR);
      }
      return DEFAULT_AVATAR;
    }

    function compressImageToDataUrl(file, maxSize = 220, quality = 0.78) {
      return new Promise((resolve, reject) => {
        if (!file || !file.type.startsWith('image/')) {
          reject(new Error('Выберите файл изображения'));
          return;
        }
        const reader = new FileReader();
        reader.onload = () => {
          const img = new Image();
          img.onload = () => {
            const canvas = document.createElement('canvas');
            let w = img.width || maxSize;
            let h = img.height || maxSize;
            if (w > h) {
              if (w > maxSize) {
                h = Math.round((h * maxSize) / w);
                w = maxSize;
              }
            } else if (h > maxSize) {
              w = Math.round((w * maxSize) / h);
              h = maxSize;
            }
            canvas.width = Math.max(1, w);
            canvas.height = Math.max(1, h);
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            const out = canvas.toDataURL('image/jpeg', quality);
            resolve(out);
          };
          img.onerror = () => reject(new Error('Не удалось загрузить картинку'));
          img.src = reader.result;
        };
        reader.onerror = () => reject(new Error('Ошибка чтения файла'));
        reader.readAsDataURL(file);
      });
    }

    async function handleUserAvatarFile(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = '';
      if (!file || !currentUser) return;
      try {
        const dataUrl = await compressImageToDataUrl(file);
        selectedAvatar = dataUrl;
        currentUser.avatar = dataUrl;
        localStorage.setItem(`pigeon_avatar_${currentUser.id}`, dataUrl);
        document.querySelectorAll('#avatar-grid .avatar-option').forEach(el => el.classList.remove('selected'));
        document.getElementById('user-avatar-photo-status').textContent = 'Фото выбрано';
        updateHeaderUI();
        fetch('/api/update-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({ id: currentUser.id, newNickname: currentUser.nickname, newAvatar: dataUrl })
        }).then(() => loadChatsList()).catch(() => {});
      } catch (e) {
        document.getElementById('settings-error').textContent = e.message || 'Ошибка загрузки фото';
      }
    }

    async function handleGroupPhotoFile(event, mode) {
      const file = event.target.files && event.target.files[0];
      event.target.value = '';
      if (!file) return;
      try {
        const dataUrl = await compressImageToDataUrl(file);
        if (mode === 'create') {
          selectedNewGroupIcon = dataUrl;
          document.querySelectorAll('#create-group-icon-grid .emoji-pick-btn').forEach(b => b.classList.remove('selected'));
          document.getElementById('new-group-photo-status').textContent = 'Фото выбрано';
        } else {
          selectedEditGroupIcon = dataUrl;
          document.querySelectorAll('#edit-group-icon-grid .emoji-pick-btn').forEach(b => b.classList.remove('selected'));
          document.getElementById('edit-group-photo-status').textContent = 'Фото выбрано';
        }
      } catch (e) {
        showCopyToast(e.message || 'Ошибка загрузки фото');
      }
    }

    function updateFabVisibility() {
      const fab = document.getElementById('fab-create-group');
      if (!fab) return;
      const show = Boolean(currentUser && !activePeer && !isAnyOverlaySceneOpen());
      fab.classList.toggle('visible', show);
    }

    function scrollChatToBottom(force = false) {
      const box = document.getElementById('chat-messages');
      if (!box) return;
      const distanceFromBottom = box.scrollHeight - box.scrollTop - box.clientHeight;
      if (force || distanceFromBottom < 140) {
        box.scrollTop = box.scrollHeight;
        requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
      }
    }

    function handleComposerFocus() {
      const input = document.getElementById('chat-message-input');
      setTimeout(() => {
        if (input && input.scrollIntoView) input.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        scrollChatToBottom(true);
      }, 100);
      setTimeout(() => scrollChatToBottom(true), 240);
    }

    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', () => { if (activePeer) scrollChatToBottom(true); });
    }
    window.addEventListener('resize', () => { if (activePeer) scrollChatToBottom(true); });

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && currentUser) {
        if (activePeer) fetchMessages();
        loadChatsList();
      }
    });
    window.addEventListener('focus', () => {
      if (currentUser) {
        if (activePeer) fetchMessages();
        loadChatsList();
      }
    });

    function loadCustomization() {
      try {
        const raw = localStorage.getItem('pigeon_customization');
        if (raw) {
          const parsed = JSON.parse(raw);
          if (['small', 'medium', 'large'].includes(parsed.msgSize)) customization.msgSize = parsed.msgSize;
          if (ALLOWED_THEMES.includes(parsed.theme)) customization.theme = parsed.theme;
        }
      } catch (e) {}
    }

    function applyCustomizationToUI() {
      const activeTheme = ALLOWED_THEMES.includes(customization.theme) ? customization.theme : 'blue';
      document.body.setAttribute('data-theme', activeTheme);

      document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.theme === activeTheme);
      });

      const bubble = document.getElementById('custom-preview-bubble');
      if (bubble) {
        bubble.classList.remove('msg-size-small', 'msg-size-medium', 'msg-size-large');
        bubble.classList.add(`msg-size-${customization.msgSize}`);
      }
      document.querySelectorAll('.size-btn').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.size === customization.msgSize);
      });
    }

    function getLocalDialogKey(uid, pid) { return `pigeon_dialog_${uid}_${pid}`; }
    function readLocalDialog(uid, pid) {
      try {
        const parsed = JSON.parse(localStorage.getItem(getLocalDialogKey(uid, pid)) || '[]');
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) { return []; }
    }
    function writeLocalDialog(uid, pid, msgs) {
      if (!Array.isArray(msgs)) return;
      try { localStorage.setItem(getLocalDialogKey(uid, pid), JSON.stringify(msgs)); } catch (e) {}
    }

    function normalizeReactions(rawReactions) {
      const map = new Map();
      function addEntry(emoji, userId, nickname) {
        if (!REACTION_EMOJIS.includes(emoji)) return;
        const uid = String(userId || nickname || 'user');
        let nick = String(nickname || '').trim();
        if (!nick) {
          if (currentUser && uid === currentUser.id) nick = currentUser.nickname;
          else if (activePeer && uid === activePeer.id) nick = activePeer.nickname;
          else nick = 'Пользователь';
        }
        if (!map.has(emoji)) map.set(emoji, []);
        const list = map.get(emoji);
        const idx = list.findIndex(item => item.user_id === uid);
        if (idx >= 0) list[idx] = { user_id: uid, nickname: nick };
        else list.push({ user_id: uid, nickname: nick });
      }

      if (rawReactions && typeof rawReactions === 'object') {
        Object.entries(rawReactions).forEach(([emoji, val]) => {
          if (Array.isArray(val)) {
            val.forEach(u => {
              if (typeof u === 'string') addEntry(emoji, u, u);
              else if (u && typeof u === 'object') addEntry(emoji, u.user_id || u.id, u.nickname || u.name);
            });
          }
        });
      }

      const result = {};
      REACTION_EMOJIS.forEach(em => {
        if (map.has(em) && map.get(em).length > 0) result[em] = map.get(em);
      });
      return result;
    }

    function applyReactionToggleToMessage(msg, emoji, user) {
      const currentMap = normalizeReactions(msg.reactions);
      const nextMap = {};
      let hadThisEmojiByMe = false;

      REACTION_EMOJIS.forEach(em => {
        const list = currentMap[em] || [];
        if (list.some(item => item.user_id === user.id) && em === emoji) hadThisEmojiByMe = true;
        const filtered = list.filter(item => item.user_id !== user.id);
        if (filtered.length > 0) nextMap[em] = filtered;
      });

      if (!hadThisEmojiByMe) {
        if (!nextMap[emoji]) nextMap[emoji] = [];
        nextMap[emoji].push({ user_id: user.id, nickname: user.nickname });
      }
      return { ...msg, reactions: nextMap };
    }

    window.addEventListener('DOMContentLoaded', () => {
      loadCustomization();
      applyCustomizationToUI();

      setTimeout(async () => {
        document.getElementById('splash-screen').classList.add('hidden');
        const savedId = localStorage.getItem('pigeon_user_id');
        if (savedId) {
          try {
            const res = await fetch('/api/me', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              cache: 'no-store',
              body: JSON.stringify({ id: savedId })
            });
            const data = await res.json();
            if (res.ok && data.user) {
              const localAv = localStorage.getItem(`pigeon_avatar_${data.user.id}`);
              if (localAv && !data.user.avatar) data.user.avatar = localAv;
              enterApp(data.user);
              return;
            }
          } catch (e) {}
        }
        document.getElementById('auth-screen').classList.add('active');
      }, 4000);
    });

    function switchMode(mode) {
      authMode = mode;
      document.getElementById('auth-error').textContent = '';
      document.getElementById('tab-register').classList.toggle('active', mode === 'register');
      document.getElementById('tab-login').classList.toggle('active', mode === 'login');
      document.getElementById('auth-submit-btn').textContent = mode === 'register' ? 'Зарегистрироваться' : 'Войти';
    }

    async function submitAuth() {
      const nickname = document.getElementById('auth-nick').value;
      const password = document.getElementById('auth-pass').value;
      const errorEl = document.getElementById('auth-error');
      errorEl.textContent = '';
      const endpoint = authMode === 'register' ? '/api/register' : '/api/login';

      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({ nickname, password })
        });
        const data = await res.json();
        if (!res.ok) {
          errorEl.textContent = data.error || 'Ошибка';
          return;
        }
        localStorage.setItem('pigeon_user_id', data.user.id);
        const localAv = localStorage.getItem(`pigeon_avatar_${data.user.id}`);
        if (localAv && !data.user.avatar) data.user.avatar = localAv;
        enterApp(data.user);
      } catch (err) {
        errorEl.textContent = 'Нет связи с сервером';
      }
    }

    function enterApp(user) {
      currentUser = {
        ...user,
        avatar: resolveAvatar(user.id, user.avatar),
        dm_policy: user.dm_policy === 'nobody' ? 'nobody' : 'all'
      };
      selectedAvatar = currentUser.avatar;
      selectedDmPolicy = currentUser.dm_policy;
      localStorage.setItem(`pigeon_avatar_${currentUser.id}`, selectedAvatar);

      document.getElementById('auth-screen').classList.remove('active');
      document.getElementById('main-screen').classList.add('active');

      updateHeaderUI();
      closeSearchScreen();
      closeSettingsScreen();
      closeCreateGroupScene();
      closeChatSettingsScene();
      updateFabVisibility();

      const cachedChats = readChatsCache(currentUser.id);
      if (cachedChats.length > 0) renderChatsListItems(cachedChats);
      loadChatsList();

      if (chatsListPollTimer) clearInterval(chatsListPollTimer);
      chatsListPollTimer = setInterval(() => {
        if (currentUser && !activePeer && !isAnyOverlaySceneOpen()) {
          loadChatsList();
        }
      }, 700);
    }

    function updateHeaderUI() {
      if (!currentUser) return;
      const av = resolveAvatar(currentUser.id, currentUser.avatar);
      document.getElementById('header-avatar').innerHTML = renderAvatarContent(av, DEFAULT_AVATAR);
      document.getElementById('header-nick').textContent = currentUser.nickname;
      document.getElementById('header-verified').innerHTML = getBadgeHtmlForUser(currentUser);
    }

    function copyCurrentUserId() {
      if (!currentUser || !currentUser.id) return;
      const idText = String(currentUser.id);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(idText).then(() => showCopyToast('ID скопирован')).catch(() => fallbackCopy(idText));
      } else {
        fallbackCopy(idText);
      }
    }

    function openSearchScreen() {
      document.getElementById('main-top-bar').classList.add('hidden');
      document.getElementById('chats-view').classList.add('hidden');
      document.getElementById('search-view').classList.add('active');
      updateFabVisibility();
      const input = document.getElementById('search-input');
      input.value = '';
      document.getElementById('search-results').innerHTML = '<div class="search-empty">Начни вводить имя пользователя</div>';
      input.focus();
    }

    function closeSearchScreen() {
      document.getElementById('search-view').classList.remove('active');
      document.getElementById('main-top-bar').classList.remove('hidden');
      document.getElementById('chats-view').classList.remove('hidden');
      updateFabVisibility();
      if (currentUser) loadChatsList();
    }

    async function runSearch() {
      const q = document.getElementById('search-input').value.trim();
      const resultsEl = document.getElementById('search-results');
      if (!q) {
        resultsEl.innerHTML = '<div class="search-empty">Начни вводить имя пользователя</div>';
        return;
      }
      try {
        const excludeParam = currentUser && currentUser.id ? `&exclude_id=${encodeURIComponent(currentUser.id)}` : '';
        const res = await fetch(`/api/users/search?q=${encodeURIComponent(q)}${excludeParam}`, { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!Array.isArray(data.users)) return;
        const users = data.users.filter(u => !currentUser || u.id !== currentUser.id);
        if (users.length === 0) {
          resultsEl.innerHTML = '<div class="search-empty">Пользователи не найдены</div>';
          return;
        }
        resultsEl.innerHTML = users.map(u => {
          const av = resolveAvatar(u.id, u.avatar);
          const safeObj = escapeHtml(JSON.stringify({ ...u, avatar: av, isGroup: false }));
          return `
            <div class="search-user-item" onclick='openChatWithUser(${safeObj})'>
              <div class="search-user-left">
                <div class="avatar-circle">${renderAvatarContent(av, DEFAULT_AVATAR)}</div>
                <div class="nickname-row">
                  <span>${escapeHtml(u.nickname)}</span>
                  ${getBadgeHtmlForUser(u)}
                </div>
              </div>
              <span class="open-chat-tag">Чат →</span>
            </div>
          `;
        }).join('');
      } catch (e) {}
    }

    function computeUnreadCount(peerId, messages) {
      if (!currentUser || !Array.isArray(messages) || messages.length === 0) return 0;
      const lastRead = getLastReadTime(currentUser.id, peerId);
      return messages.filter(m => m.sender_id !== currentUser.id && m.sender_id !== 'system' && (Number(m.timestamp) || 0) > lastRead).length;
    }

    function getDirectPartnersForGroup() {
      const cached = readChatsCache(currentUser?.id || '');
      return cached.filter(c => !c.isGroup && c.id !== currentUser?.id);
    }

    function renderChatsListItems(chats) {
      const listEl = document.getElementById('chats-list');
      const emptyEl = document.getElementById('empty-chats-placeholder');
      if (!listEl || !emptyEl) return;

      if (!Array.isArray(chats) || chats.length === 0) {
        listEl.innerHTML = '';
        emptyEl.style.display = 'flex';
        return;
      }

      emptyEl.style.display = 'none';
      listEl.innerHTML = chats.map(c => {
        const isGroup = Boolean(c.isGroup);
        const av = normalizeAvatar(
          isGroup ? (c.avatar || DEFAULT_GROUP_ICON) : (c.avatar || resolveAvatar(c.id, null)),
          DEFAULT_AVATAR
        );
        const safeObj = escapeHtml(JSON.stringify({
          id: c.id,
          nickname: c.nickname,
          avatar: av,
          verified: c.verified,
          badge_color: c.badge_color || null,
          dm_policy: c.dm_policy || 'all',
          isGroup,
          ownerId: c.ownerId || '',
          members: Array.isArray(c.members) ? c.members : [],
          mutedMembers: Array.isArray(c.mutedMembers) ? c.mutedMembers : [],
          memberDetails: Array.isArray(c.memberDetails) ? c.memberDetails : []
        }));
        const unreadVal = Number(c.unreadCount) || 0;
        const badgeHtml = unreadVal > 0 ? `<span class="unread-badge">${unreadVal}</span>` : '';
        const prefix = isGroup && c.lastSenderName && c.lastMessage && c.lastSenderId !== 'system' ? `${c.lastSenderName}: ` : '';
        return `
          <div class="chat-list-item" onclick='openChatWithUser(${safeObj})'>
            <div class="avatar-circle">${renderAvatarContent(av, DEFAULT_AVATAR)}</div>
            <div class="chat-meta">
              <div class="nickname-row">
                <span>${escapeHtml(c.nickname)}</span>
                ${getBadgeHtmlForUser(c)}
              </div>
              <div class="chat-last-msg">${escapeHtml(prefix + (c.lastMessage || (isGroup ? 'Группа создана' : 'Нет сообщений')))}</div>
            </div>
            ${badgeHtml}
          </div>
        `;
      }).join('');
    }

    async function loadChatsList() {
      if (!currentUser || isFetchingChatsList) return;
      isFetchingChatsList = true;
      try {
        const res = await fetch(`/api/chats?user_id=${encodeURIComponent(currentUser.id)}`, { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!Array.isArray(data.chats)) return;

        const prevCached = readChatsCache(currentUser.id);
        if (data.chats.length === 0 && prevCached.length > 0) {
          if (prevCached.length === 1 && prevCached[0].isGroup) {
            writeChatsCache(currentUser.id, []);
            renderChatsListItems([]);
            return;
          }
          renderChatsListItems(prevCached);
          return;
        }
        const prevMap = new Map(prevCached.map(item => [item.id, item]));

        const normalized = data.chats.map(c => {
          const isGroup = Boolean(c.isGroup);
          const av = normalizeAvatar(
            isGroup ? (c.avatar || DEFAULT_GROUP_ICON) : (c.avatar || resolveAvatar(c.id, null)),
            DEFAULT_AVATAR
          );
          if (!isGroup && c.id && av) localStorage.setItem(`pigeon_avatar_${c.id}`, av);

          const prevItem = prevMap.get(c.id);
          const localMsgs = readLocalDialog(currentUser.id, c.id);
          const localUnread = computeUnreadCount(c.id, localMsgs);
          const prevUnread = prevItem && typeof prevItem.unreadCount === 'number' ? prevItem.unreadCount : 0;

          let unreadCount = Math.max(typeof c.unreadCount === 'number' ? c.unreadCount : 0, localUnread);
          const nextLastMsg = c.lastMessage || (localMsgs.length > 0 ? localMsgs[localMsgs.length - 1].text : (isGroup ? 'Группа создана' : 'Нет сообщений'));
          const prevLastMsg = prevItem ? prevItem.lastMessage : null;
          const sentByMeRecently = c.lastSenderId === currentUser.id || (localMsgs.length > 0 && localMsgs[localMsgs.length - 1].sender_id === currentUser.id);

          if (sentByMeRecently) {
            markChatAsRead(currentUser.id, c.id, Number(c.lastTimestamp) || Date.now());
            unreadCount = 0;
          } else if (prevItem && prevLastMsg && nextLastMsg !== prevLastMsg && unreadCount === 0 && (!activePeer || activePeer.id !== c.id)) {
            unreadCount = Math.max(prevUnread + 1, 1);
          } else if (prevItem && nextLastMsg === prevLastMsg && unreadCount === 0 && prevUnread > 0 && (!activePeer || activePeer.id !== c.id)) {
            unreadCount = prevUnread;
          }
          if (activePeer && activePeer.id === c.id) {
            unreadCount = 0;
            activePeer.avatar = av;
            activePeer.nickname = c.nickname;
            activePeer.badge_color = c.badge_color || null;
            activePeer.dm_policy = c.dm_policy || activePeer.dm_policy || 'all';
            activePeer.ownerId = c.ownerId || activePeer.ownerId || '';
            activePeer.members = Array.isArray(c.members) ? c.members : (activePeer.members || []);
            activePeer.mutedMembers = Array.isArray(c.mutedMembers) ? c.mutedMembers : [];
            activePeer.memberDetails = Array.isArray(c.memberDetails) ? c.memberDetails : [];
            document.getElementById('peer-avatar').innerHTML = renderAvatarContent(av, DEFAULT_AVATAR);
            document.getElementById('peer-nick').textContent = c.nickname;
            document.getElementById('peer-verified').innerHTML = getBadgeHtmlForUser(activePeer);
            applyGroupRoomState();
          }
          return { ...c, avatar: av, lastMessage: nextLastMsg, unreadCount };
        });

        writeChatsCache(currentUser.id, normalized);
        renderChatsListItems(normalized);
      } catch (e) {}
      finally { isFetchingChatsList = false; }
    }

    function applyGroupRoomState() {
      const isGroup = Boolean(activePeer && activePeer.isGroup);
      const subEl = document.getElementById('peer-sub');
      const noticeEl = document.getElementById('muted-chat-notice');
      const formEl = document.getElementById('chat-form');

      if (!isGroup) {
        subEl.style.display = 'none';
        noticeEl.style.display = 'none';
        formEl.style.display = 'flex';
        return;
      }

      const memberCount = Array.isArray(activePeer.members) ? activePeer.members.length : 0;
      subEl.textContent = `Участников: ${memberCount}`;
      subEl.style.display = 'block';

      const isMutedForMe = isUserMutedInGroup(activePeer, currentUser?.id);
      noticeEl.style.display = isMutedForMe ? 'block' : 'none';
      formEl.style.display = isMutedForMe ? 'none' : 'flex';
    }

    function handlePeerHeaderClick() {
      if (!activePeer) return;
      openChatSettingsScene(activePeer);
    }

    function openCreateGroupScene() {
      if (!currentUser) return;
      selectedNewGroupIcon = DEFAULT_GROUP_ICON;
      document.getElementById('new-group-name').value = '';
      document.getElementById('create-group-error').textContent = '';
      document.getElementById('new-group-photo-status').textContent = 'Выбран эмодзи';

      const iconGrid = document.getElementById('create-group-icon-grid');
      iconGrid.innerHTML = GROUP_ICONS.map(ic => `
        <button type="button" class="emoji-pick-btn ${ic === selectedNewGroupIcon ? 'selected' : ''}" onclick="pickNewGroupIcon('${ic}', this)">${ic}</button>
      `).join('');

      const partners = getDirectPartnersForGroup();
      const membersBox = document.getElementById('create-group-members');
      if (partners.length === 0) {
        membersBox.innerHTML = '<div class="search-empty">Сначала начни переписку хотя бы с одним пользователем</div>';
      } else {
        membersBox.innerHTML = partners.map(p => `
          <label class="member-check-item">
            <div class="member-check-left">
              <div class="avatar-circle" style="width:30px;height:30px;font-size:16px;">${renderAvatarContent(p.avatar, DEFAULT_AVATAR)}</div>
              <span>${escapeHtml(p.nickname)}</span>
            </div>
            <input type="checkbox" class="new-group-member-cb" value="${escapeHtml(p.id)}" />
          </label>
        `).join('');
      }

      document.getElementById('create-group-scene').classList.add('active');
      updateFabVisibility();
    }

    function pickNewGroupIcon(ic, btnEl) {
      selectedNewGroupIcon = ic;
      document.querySelectorAll('#create-group-icon-grid .emoji-pick-btn').forEach(b => b.classList.remove('selected'));
      if (btnEl) btnEl.classList.add('selected');
      document.getElementById('new-group-photo-status').textContent = `Выбран эмодзи ${ic}`;
    }

    function closeCreateGroupScene() {
      document.getElementById('create-group-scene').classList.remove('active');
      updateFabVisibility();
      if (currentUser && !activePeer) loadChatsList();
    }

    async function submitCreateGroup() {
      if (!currentUser) return;
      const name = document.getElementById('new-group-name').value.trim();
      const errEl = document.getElementById('create-group-error');
      errEl.textContent = '';

      if (name.length < 2) {
        errEl.textContent = 'Введи название группы (от 2 символов)';
        return;
      }

      const memberIds = Array.from(document.querySelectorAll('.new-group-member-cb:checked')).map(cb => cb.value);

      try {
        const res = await fetch('/api/groups/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({
            creator_id: currentUser.id,
            name,
            icon: selectedNewGroupIcon,
            member_ids: memberIds
          })
        });
        const data = await res.json();
        if (!res.ok) {
          errEl.textContent = data.error || 'Не удалось создать группу';
          return;
        }
        document.getElementById('create-group-scene').classList.remove('active');
        await loadChatsList();
        if (data.group) {
          openChatWithUser({
            id: data.group.id,
            nickname: data.group.name,
            avatar: data.group.icon,
            isGroup: true,
            ownerId: data.group.owner_id,
            members: data.group.members || [],
            mutedMembers: data.group.muted_members || [],
            memberDetails: data.group.member_details || []
          });
        }
      } catch (e) {
        errEl.textContent = 'Нет связи с сервером';
      }
    }

    function syncGroupDataFromServer(serverGroup) {
      if (!serverGroup) return;
      const cleanIcon = normalizeAvatar(serverGroup.icon, DEFAULT_GROUP_ICON);
      if (editingGroupState && editingGroupState.id === serverGroup.id) {
        editingGroupState.nickname = serverGroup.name;
        editingGroupState.avatar = cleanIcon;
        editingGroupState.ownerId = serverGroup.owner_id;
        editingGroupState.members = serverGroup.members || [];
        editingGroupState.mutedMembers = serverGroup.muted_members || [];
        editingGroupState.memberDetails = serverGroup.member_details || [];
      }
      if (activePeer && activePeer.id === serverGroup.id) {
        activePeer.nickname = serverGroup.name;
        activePeer.avatar = cleanIcon;
        activePeer.ownerId = serverGroup.owner_id;
        activePeer.members = serverGroup.members || [];
        activePeer.mutedMembers = serverGroup.muted_members || [];
        activePeer.memberDetails = serverGroup.member_details || [];
        document.getElementById('peer-nick').textContent = activePeer.nickname;
        document.getElementById('peer-avatar').innerHTML = renderAvatarContent(cleanIcon, DEFAULT_GROUP_ICON);
        applyGroupRoomState();
      }
    }

    function openChatSettingsScene(peerObj) {
      const directCard = document.getElementById('direct-chat-settings-card');
      const groupCard = document.getElementById('group-chat-settings-card');

      if (!peerObj.isGroup) {
        editingGroupState = null;
        directCard.style.display = 'flex';
        groupCard.style.display = 'none';
        document.getElementById('chat-scene-title').textContent = `Чат: ${peerObj.nickname}`;
        document.getElementById('chat-settings-scene').classList.add('active');
        updateFabVisibility();
        return;
      }

      directCard.style.display = 'none';
      groupCard.style.display = 'flex';
      editingGroupState = { ...peerObj, avatar: normalizeAvatar(peerObj.avatar, DEFAULT_GROUP_ICON) };
      selectedEditGroupIcon = editingGroupState.avatar;
      const canEdit = isGroupOwner(peerObj);

      const readonlyEl = document.getElementById('group-readonly-info');
      const ownerControlsEl = document.getElementById('group-owner-controls');

      if (!canEdit) {
        document.getElementById('chat-scene-title').textContent = `${peerObj.nickname}`;
        const memberCount = Array.isArray(peerObj.members) ? peerObj.members.length : 0;
        const mutedForMe = isUserMutedInGroup(peerObj, currentUser?.id);
        readonlyEl.innerHTML = `
          <div><strong>Название:</strong> ${escapeHtml(peerObj.nickname)}</div>
          <div><strong>Участников:</strong> ${memberCount}</div>
          <div><strong>Статус:</strong> ${mutedForMe ? 'Вам запрещено писать сообщения' : 'Вы можете отправлять сообщения'}</div>
        `;
        readonlyEl.style.display = 'flex';
        ownerControlsEl.style.display = 'none';
        document.getElementById('chat-settings-scene').classList.add('active');
        updateFabVisibility();
        return;
      }

      readonlyEl.style.display = 'none';
      ownerControlsEl.style.display = 'flex';
      document.getElementById('chat-scene-title').textContent = `Настройки группы`;
      document.getElementById('edit-group-name').value = peerObj.nickname;
      document.getElementById('edit-group-photo-status').textContent = isImageAvatar(selectedEditGroupIcon)
        ? 'Выбрано фото'
        : `Выбран эмодзи ${selectedEditGroupIcon}`;

      const iconGrid = document.getElementById('edit-group-icon-grid');
      iconGrid.innerHTML = GROUP_ICONS.map(ic => `
        <button type="button" class="emoji-pick-btn ${ic === selectedEditGroupIcon ? 'selected' : ''}" onclick="pickEditGroupIcon('${ic}', this)">${ic}</button>
      `).join('');

      const currentMembersBox = document.getElementById('current-group-members-list');
      const details = Array.isArray(peerObj.memberDetails) && peerObj.memberDetails.length > 0
        ? peerObj.memberDetails
        : (Array.isArray(peerObj.members) ? peerObj.members.map(mid => ({
            id: mid,
            nickname: mid === currentUser.id ? currentUser.nickname : mid,
            avatar: mid === currentUser.id ? currentUser.avatar : resolveAvatar(mid, null),
            muted: (peerObj.mutedMembers || []).includes(mid),
            isOwner: mid === (peerObj.ownerId || peerObj.owner_id)
          })) : []);

      currentMembersBox.innerHTML = details.map(m => {
        if (m.isOwner || m.id === currentUser.id) {
          return `
            <div class="member-check-item">
              <div class="member-check-left">
                <div class="avatar-circle" style="width:30px;height:30px;font-size:16px;">${renderAvatarContent(m.avatar, DEFAULT_AVATAR)}</div>
                <span>${escapeHtml(m.nickname)} <strong style="color:var(--accent);">(Владелец)</strong></span>
              </div>
            </div>
          `;
        }
        const isMuted = Boolean(m.muted);
        return `
          <div class="member-check-item">
            <div class="member-check-left">
              <div class="avatar-circle" style="width:30px;height:30px;font-size:16px;">${renderAvatarContent(m.avatar, DEFAULT_AVATAR)}</div>
              <span>${escapeHtml(m.nickname)}</span>
            </div>
            <div class="member-row-actions">
              <button
                type="button"
                class="mini-action-btn ${isMuted ? 'muted-on' : ''}"
                title="${isMuted ? 'Разрешить писать' : 'Запретить писать'}"
                onclick="toggleSingleMemberMute('${escapeHtml(m.id)}', ${isMuted ? 'false' : 'true'})"
              >${isMuted ? '🔇 Мут' : '🔊'}</button>
              <button
                type="button"
                class="mini-action-btn kick"
                title="Удалить участника из группы"
                onclick="kickSingleMember('${escapeHtml(m.id)}')"
              >✖</button>
            </div>
          </div>
        `;
      }).join('');

      const currentMembers = Array.isArray(peerObj.members) ? peerObj.members : [];
      const candidates = getDirectPartnersForGroup().filter(p => !currentMembers.includes(p.id));
      const addListEl = document.getElementById('add-group-members-list');
      if (candidates.length === 0) {
        addListEl.innerHTML = '<div class="search-empty">Все собеседники уже в группе</div>';
      } else {
        addListEl.innerHTML = candidates.map(p => `
          <label class="member-check-item">
            <div class="member-check-left">
              <div class="avatar-circle" style="width:30px;height:30px;font-size:16px;">${renderAvatarContent(p.avatar, DEFAULT_AVATAR)}</div>
              <span>${escapeHtml(p.nickname)}</span>
            </div>
            <input type="checkbox" class="add-group-member-cb" value="${escapeHtml(p.id)}" />
          </label>
        `).join('');
      }

      document.getElementById('chat-settings-scene').classList.add('active');
      updateFabVisibility();
    }

    function pickEditGroupIcon(ic, btnEl) {
      selectedEditGroupIcon = ic;
      document.querySelectorAll('#edit-group-icon-grid .emoji-pick-btn').forEach(b => b.classList.remove('selected'));
      if (btnEl) btnEl.classList.add('selected');
      document.getElementById('edit-group-photo-status').textContent = `Выбран эмодзи ${ic}`;
    }

    function closeChatSettingsScene() {
      document.getElementById('chat-settings-scene').classList.remove('active');
      updateFabVisibility();
      if (activePeer) fetchMessages();
      else if (currentUser) loadChatsList();
    }

    async function deleteDirectChat() {
      if (!activePeer || activePeer.isGroup || !currentUser) return;
      const targetPeerId = activePeer.id;

      document.getElementById('chat-settings-scene').classList.remove('active');
      activePeer = null;
      cancelReply();
      document.getElementById('chat-room-view').classList.remove('active');
      if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }

      try { localStorage.removeItem(getLocalDialogKey(currentUser.id, targetPeerId)); } catch (e) {}
      writeChatsCache(currentUser.id, readChatsCache(currentUser.id).filter(c => c.id !== targetPeerId));
      renderChatsListItems(readChatsCache(currentUser.id));
      updateFabVisibility();

      try {
        await fetch('/api/chats/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({ user_id: currentUser.id, peer_id: targetPeerId })
        });
        showCopyToast('Чат удалён');
        loadChatsList();
      } catch (e) {}
    }

    async function toggleSingleMemberMute(targetUserId, nextMuted) {
      if (!editingGroupState || !currentUser || !isGroupOwner(editingGroupState)) return;
      try {
        const res = await fetch('/api/groups/member-action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({
            group_id: editingGroupState.id,
            user_id: currentUser.id,
            target_user_id: targetUserId,
            action: nextMuted ? 'mute' : 'unmute'
          })
        });
        const data = await res.json();
        if (res.ok && data.group) {
          syncGroupDataFromServer(data.group);
          openChatSettingsScene(editingGroupState);
          showCopyToast(nextMuted ? 'Участнику запрещено писать' : 'Участнику разрешено писать');
          loadChatsList();
        } else if (data.error) {
          showCopyToast(data.error);
        }
      } catch (e) {}
    }

    async function kickSingleMember(targetUserId) {
      if (!editingGroupState || !currentUser || !isGroupOwner(editingGroupState)) return;
      try {
        const res = await fetch('/api/groups/member-action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({
            group_id: editingGroupState.id,
            user_id: currentUser.id,
            target_user_id: targetUserId,
            action: 'remove'
          })
        });
        const data = await res.json();
        if (res.ok && data.group) {
          syncGroupDataFromServer(data.group);
          openChatSettingsScene(editingGroupState);
          showCopyToast('Участник удалён из группы');
          loadChatsList();
          if (activePeer && activePeer.id === editingGroupState.id) fetchMessages();
        } else if (data.error) {
          showCopyToast(data.error);
        }
      } catch (e) {}
    }

    async function saveGroupDetails() {
      if (!editingGroupState || !currentUser || !isGroupOwner(editingGroupState)) return;
      const newName = document.getElementById('edit-group-name').value.trim();
      if (newName.length < 2) {
        showCopyToast('Название слишком короткое');
        return;
      }
      try {
        const res = await fetch('/api/groups/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({
            group_id: editingGroupState.id,
            user_id: currentUser.id,
            name: newName,
            icon: selectedEditGroupIcon
          })
        });
        const data = await res.json();
        if (res.ok && data.group) {
          syncGroupDataFromServer(data.group);
          showCopyToast('Группа обновлена');
          loadChatsList();
        } else if (data.error) {
          showCopyToast(data.error);
        }
      } catch (e) {}
    }

    async function addSelectedMembersToGroup() {
      if (!editingGroupState || !currentUser || !isGroupOwner(editingGroupState)) return;
      const ids = Array.from(document.querySelectorAll('.add-group-member-cb:checked')).map(cb => cb.value);
      if (ids.length === 0) {
        showCopyToast('Выбери участников');
        return;
      }
      try {
        const res = await fetch('/api/groups/add-members', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({
            group_id: editingGroupState.id,
            user_id: currentUser.id,
            member_ids: ids
          })
        });
        const data = await res.json();
        if (res.ok && data.group) {
          syncGroupDataFromServer(data.group);
          openChatSettingsScene(editingGroupState);
          showCopyToast('Участники добавлены');
          loadChatsList();
          if (activePeer && activePeer.id === editingGroupState.id) fetchMessages();
        } else if (data.error) {
          showCopyToast(data.error);
        }
      } catch (e) {}
    }

    async function leaveCurrentGroup() {
      if (!editingGroupState || !currentUser) return;
      const gid = editingGroupState.id;
      const wasActiveRoom = Boolean(activePeer && activePeer.id === gid);

      try {
        const res = await fetch('/api/groups/leave', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({ group_id: gid, user_id: currentUser.id })
        });
        const data = await res.json();

        if (!wasActiveRoom && !data.deleted && data.group) {
          syncGroupDataFromServer(data.group);
          openChatSettingsScene(editingGroupState);
          showCopyToast('Список участников обновлён');
          loadChatsList();
          return;
        }
      } catch (e) {}

      document.getElementById('chat-settings-scene').classList.remove('active');
      writeChatsCache(currentUser.id, readChatsCache(currentUser.id).filter(c => c.id !== gid));
      renderChatsListItems(readChatsCache(currentUser.id));
      if (wasActiveRoom) {
        activePeer = null;
        document.getElementById('chat-room-view').classList.remove('active');
        if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }
      }
      updateFabVisibility();
      showCopyToast('Вы вышли из группы');
      loadChatsList();
    }

    async function deleteCurrentGroup() {
      if (!editingGroupState || !currentUser || !isGroupOwner(editingGroupState)) return;
      const gid = editingGroupState.id;
      document.getElementById('chat-settings-scene').classList.remove('active');
      writeChatsCache(currentUser.id, readChatsCache(currentUser.id).filter(c => c.id !== gid));
      renderChatsListItems(readChatsCache(currentUser.id));
      if (activePeer && activePeer.id === gid) {
        activePeer = null;
        document.getElementById('chat-room-view').classList.remove('active');
        if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }
      }
      updateFabVisibility();
      try {
        await fetch('/api/groups/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({ group_id: gid, user_id: currentUser.id })
        });
        showCopyToast('Группа удалена');
        loadChatsList();
      } catch (e) {}
    }

    function openChatWithUser(peer) {
      activePeer = {
        ...peer,
        isGroup: Boolean(peer.isGroup),
        avatar: normalizeAvatar(
          peer.avatar || (peer.isGroup ? DEFAULT_GROUP_ICON : resolveAvatar(peer.id, null)),
          DEFAULT_AVATAR
        )
      };
      cancelReply();
      applyCustomizationToUI();
      applyGroupRoomState();
      updateFabVisibility();

      document.getElementById('peer-avatar').innerHTML = renderAvatarContent(activePeer.avatar, DEFAULT_AVATAR);
      document.getElementById('peer-nick').textContent = activePeer.nickname;
      document.getElementById('peer-verified').innerHTML = getBadgeHtmlForUser(activePeer);
      document.getElementById('chat-room-view').classList.add('active');

      currentMessagesCache = readLocalDialog(currentUser.id, activePeer.id).map(m => ({
        ...m,
        reactions: normalizeReactions(m.reactions)
      }));
      const latestLocalTs = currentMessagesCache.reduce((acc, m) => Math.max(acc, Number(m.timestamp) || 0), Date.now());
      markChatAsRead(currentUser.id, activePeer.id, latestLocalTs);
      writeChatsCache(currentUser.id, readChatsCache(currentUser.id).map(c => c.id === activePeer.id ? { ...c, unreadCount: 0 } : c));

      renderMessages(currentMessagesCache, true);
      fetchMessages();
      if (chatPollTimer) clearInterval(chatPollTimer);
      chatPollTimer = setInterval(fetchMessages, 250);
    }

    function closeChatRoom() {
      if (currentUser && activePeer) {
        const latestTs = currentMessagesCache.reduce((acc, m) => Math.max(acc, Number(m.timestamp) || 0), Date.now());
        markChatAsRead(currentUser.id, activePeer.id, latestTs);
        writeChatsCache(currentUser.id, readChatsCache(currentUser.id).map(c => c.id === activePeer.id ? { ...c, unreadCount: 0 } : c));
      }
      activePeer = null;
      cancelReply();
      document.getElementById('chat-room-view').classList.remove('active');
      updateFabVisibility();
      if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }
      if (!document.getElementById('search-view').classList.contains('active')) {
        const cachedChats = readChatsCache(currentUser?.id);
        if (cachedChats.length > 0) renderChatsListItems(cachedChats);
        loadChatsList();
      }
    }

    function renderReactionsChipsHtml(msg) {
      const reactionsMap = normalizeReactions(msg.reactions);
      const entries = Object.entries(reactionsMap);
      if (entries.length === 0) return '';

      const chips = entries.map(([emoji, users]) => {
        const isMine = currentUser && users.some(u => u.user_id === currentUser.id);
        const namesText = users.map(u => u.nickname).join(', ');
        return `
          <button type="button" class="reaction-chip ${isMine ? 'active-mine' : ''}" data-react-msg-id="${escapeHtml(msg.id)}" data-react-emoji="${escapeHtml(emoji)}">
            <span class="reaction-chip-emoji">${escapeHtml(emoji)}</span>
            <span class="reaction-chip-count">${users.length}</span>
            <span class="reaction-chip-users">${escapeHtml(namesText)}</span>
          </button>
        `;
      }).join('');
      return `<div class="msg-reactions-list">${chips}</div>`;
    }

    function renderMessages(messages, forceScroll = false) {
      const box = document.getElementById('chat-messages');
      if (!box) return;
      const prevScrollTop = box.scrollTop;
      const wasNearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 140;

      if (!messages || messages.length === 0) {
        if (!box.innerHTML.trim()) box.innerHTML = '<div class="search-empty" style="text-align:center;margin-top:24px;">Напиши первое сообщение!</div>';
        return;
      }

      const uniqueDayKeys = new Set(messages.map(m => getDayKey(m.timestamp)).filter(Boolean));
      const hasMultipleDays = uniqueDayKeys.size > 1;
      let lastRenderedDayKey = messages.length > 0 ? getDayKey(messages[0].timestamp) : '';
      const sizeClass = `msg-size-${customization.msgSize}`;
      const isGroupChat = Boolean(activePeer && activePeer.isGroup);
      const htmlParts = [];

      messages.forEach(m => {
        const msgDayKey = getDayKey(m.timestamp);
        if (hasMultipleDays && msgDayKey && msgDayKey !== lastRenderedDayKey) {
          htmlParts.push(`<div class="day-divider">${escapeHtml(formatDayLabel(m.timestamp))}</div>`);
          lastRenderedDayKey = msgDayKey;
        }

        if (m.type === 'system' || m.sender_id === 'system') {
          htmlParts.push(`<div class="system-msg-center">${escapeHtml(m.text)}</div>`);
          return;
        }

        const isMine = m.sender_id === currentUser.id;
        const senderLabel = isGroupChat && !isMine && m.sender_nick
          ? `<div class="msg-sender-name">${escapeHtml(m.sender_nick)}</div>`
          : '';
        const replyHtml = m.reply_to && m.reply_to.text
          ? `<div class="msg-reply-quote">↩️ ${escapeHtml(m.reply_to.sender_nick || 'Сообщение')}: ${escapeHtml(m.reply_to.text)}</div>`
          : '';
        htmlParts.push(`
          <div class="msg-wrapper ${isMine ? 'mine' : 'theirs'}">
            ${senderLabel}
            <div class="msg-bubble ${sizeClass} ${isMine ? 'msg-mine' : 'msg-theirs'}" data-msg-id="${escapeHtml(m.id)}">
              ${replyHtml}
              <div class="msg-content-row">
                <span class="msg-text">${escapeHtml(m.text)}</span>
                <span class="msg-time">${escapeHtml(formatMsgTime(m.timestamp))}</span>
              </div>
            </div>
            ${renderReactionsChipsHtml(m)}
          </div>
        `);
      });

      box.innerHTML = htmlParts.join('');

      box.querySelectorAll('.reaction-chip').forEach(chipEl => {
        const msgObj = messages.find(x => x.id === chipEl.getAttribute('data-react-msg-id'));
        const emoji = chipEl.getAttribute('data-react-emoji');
        if (msgObj && emoji) chipEl.addEventListener('click', e => { e.stopPropagation(); toggleReactionOnMessage(msgObj, emoji, false); });
      });

      box.querySelectorAll('.msg-bubble').forEach(el => {
        const msgObj = messages.find(x => x.id === el.getAttribute('data-msg-id'));
        if (!msgObj) return;
        let pressTimer = null;
        let longPressed = false;
        const startPress = () => {
          longPressed = false;
          pressTimer = setTimeout(() => { longPressed = true; openMessageMenu(msgObj); }, 380);
        };
        const cancelPress = () => { if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; } };
        el.addEventListener('pointerdown', startPress);
        el.addEventListener('pointerup', cancelPress);
        el.addEventListener('pointerleave', cancelPress);
        el.addEventListener('pointercancel', cancelPress);
        el.addEventListener('click', e => { e.stopPropagation(); cancelPress(); if (!longPressed) openMessageMenu(msgObj); });
        el.addEventListener('contextmenu', e => { e.preventDefault(); cancelPress(); openMessageMenu(msgObj); });
      });

      if (forceScroll || wasNearBottom) scrollChatToBottom(true);
      else box.scrollTop = prevScrollTop;
    }

    async function fetchMessages() {
      if (!currentUser || !activePeer || isFetchingMessages) return;
      isFetchingMessages = true;
      const peerSnapshot = { ...activePeer };

      try {
        const query = peerSnapshot.isGroup
          ? `/api/messages?user_id=${encodeURIComponent(currentUser.id)}&group_id=${encodeURIComponent(peerSnapshot.id)}`
          : `/api/messages?user_id=${encodeURIComponent(currentUser.id)}&peer_id=${encodeURIComponent(peerSnapshot.id)}`;
        const res = await fetch(query, { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!activePeer || activePeer.id !== peerSnapshot.id || !Array.isArray(data.messages)) return;

        if (peerSnapshot.isGroup) {
          if (!data.group || !(data.group.members || []).includes(currentUser.id)) {
            showCopyToast('Вы больше не состоите в этой группе');
            closeChatRoom();
            loadChatsList();
            return;
          }
          syncGroupDataFromServer(data.group);
        }

        const serverMsgs = data.messages.map(srv => ({ ...srv, reactions: normalizeReactions(srv.reactions) }));
        if (serverMsgs.length === 0 && currentMessagesCache.length > 0 && !peerSnapshot.isGroup) return;

        const localOnlyPending = currentMessagesCache.filter(localMsg => {
          if (!String(localMsg.id).startsWith('msg_')) return false;
          const matched = serverMsgs.some(srv => srv.sender_id === localMsg.sender_id && srv.text === localMsg.text && Math.abs((srv.timestamp || 0) - (localMsg.timestamp || 0)) < 60000);
          return !matched && (Date.now() - (localMsg.timestamp || 0)) < 120000;
        });

        const merged = [...serverMsgs, ...localOnlyPending];
        const prevSig = currentMessagesCache.map(x => `${x.id}:${x.text}:${x.timestamp || 0}:${JSON.stringify(normalizeReactions(x.reactions))}`).join('|');
        const nextSig = merged.map(x => `${x.id}:${x.text}:${x.timestamp || 0}:${JSON.stringify(normalizeReactions(x.reactions))}`).join('|');

        currentMessagesCache = merged;
        if (selectedMessage) {
          const found = currentMessagesCache.find(m => m.id === selectedMessage.id);
          if (found) {
            selectedMessage = found;
            if (document.getElementById('msg-action-sheet').classList.contains('active')) renderSheetReactionsUI(selectedMessage);
          }
        }

        writeLocalDialog(currentUser.id, peerSnapshot.id, currentMessagesCache);
        const latestTs = currentMessagesCache.reduce((acc, m) => Math.max(acc, Number(m.timestamp) || 0), Date.now());
        markChatAsRead(currentUser.id, peerSnapshot.id, latestTs);

        if (prevSig !== nextSig) renderMessages(currentMessagesCache, false);
      } catch (e) {}
      finally { isFetchingMessages = false; }
    }

    function handleSendPointerDown(event) { event.preventDefault(); submitInstantMessage(); }
    function sendChatMessage(event) { event.preventDefault(); submitInstantMessage(); }

    function submitInstantMessage() {
      if (!currentUser || !activePeer) return;
      if (activePeer.isGroup && isUserMutedInGroup(activePeer, currentUser.id)) {
        showCopyToast('Вам запрещено писать в этой группе');
        return;
      }

      const input = document.getElementById('chat-message-input');
      const text = input.value.trim();
      if (!text) return;

      const peerId = activePeer.id;
      const peerNick = activePeer.nickname;
      const peerAv = normalizeAvatar(activePeer.avatar || (activePeer.isGroup ? DEFAULT_GROUP_ICON : DEFAULT_AVATAR), DEFAULT_AVATAR);
      const isGroup = Boolean(activePeer.isGroup);
      const replySnapshot = replyingToMessage ? { ...replyingToMessage } : null;
      const nowTs = Date.now();
      const tempId = `msg_${nowTs}_${Math.random().toString(36).slice(2, 7)}`;

      const newMsg = {
        id: tempId,
        sender_id: currentUser.id,
        sender_nick: currentUser.nickname,
        receiver_id: isGroup ? '' : peerId,
        group_id: isGroup ? peerId : '',
        text,
        timestamp: nowTs,
        reply_to: replySnapshot,
        reactions: {}
      };
      input.value = '';
      cancelReply();

      currentMessagesCache = [...currentMessagesCache, newMsg];
      writeLocalDialog(currentUser.id, peerId, currentMessagesCache);
      markChatAsRead(currentUser.id, peerId, nowTs + 1000);

      const prevChats = readChatsCache(currentUser.id);
      const existingIdx = prevChats.findIndex(c => c.id === peerId);
      const baseItem = existingIdx >= 0 ? prevChats[existingIdx] : {};
      const updatedChatItem = {
        ...baseItem,
        id: peerId,
        nickname: peerNick,
        avatar: peerAv,
        isGroup,
        lastMessage: text,
        lastSenderId: currentUser.id,
        lastSenderName: currentUser.nickname,
        lastTimestamp: nowTs,
        unreadCount: 0
      };
      const nextChats = existingIdx >= 0
        ? [updatedChatItem, ...prevChats.filter((_, i) => i !== existingIdx)]
        : [updatedChatItem, ...prevChats];
      writeChatsCache(currentUser.id, nextChats);

      renderMessages(currentMessagesCache, true);

      const payload = {
        sender_id: currentUser.id,
        receiver_id: isGroup ? '' : peerId,
        group_id: isGroup ? peerId : '',
        text,
        timestamp: nowTs,
        reply_to: replySnapshot
      };

      fetch('/api/messages/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        keepalive: true,
        body: JSON.stringify(payload)
      })
        .then(r => r.json())
        .then(data => {
          if (data.error) {
            currentMessagesCache = currentMessagesCache.filter(m => m.id !== tempId);
            writeLocalDialog(currentUser.id, peerId, currentMessagesCache);
            renderMessages(currentMessagesCache, false);
            showCopyToast(data.error);
            return;
          }
          if (data.message && data.message.id) {
            const srvTs = Number(data.message.timestamp) || nowTs;
            markChatAsRead(currentUser.id, peerId, srvTs + 1000);
            currentMessagesCache = currentMessagesCache.map(m => m.id === tempId ? { ...data.message, reactions: normalizeReactions(data.message.reactions) } : m);
            writeLocalDialog(currentUser.id, peerId, currentMessagesCache);
          }
        })
        .catch(() => {});
    }

    function renderSheetReactionsUI(msg) {
      const reactionsMap = normalizeReactions(msg.reactions);
      document.querySelectorAll('#emoji-picker-row .emoji-pick-btn').forEach(btn => {
        const em = btn.getAttribute('data-emoji');
        const mineHere = currentUser && (reactionsMap[em] || []).some(u => u.user_id === currentUser.id);
        btn.classList.toggle('selected', Boolean(mineHere));
      });
      const summaryEl = document.getElementById('sheet-reactions-summary');
      const entries = Object.entries(reactionsMap);
      summaryEl.innerHTML = entries.map(([emoji, users]) =>
        `<div class="sheet-reaction-line"><span>${escapeHtml(emoji)}</span><span><strong>${users.length}</strong> — ${users.map(u => escapeHtml(u.nickname)).join(', ')}</span></div>`
      ).join('');
    }

    function openMessageMenu(msg) {
      selectedMessage = msg;
      const shortText = msg.text.length > 40 ? msg.text.slice(0, 40) + '...' : msg.text;
      document.getElementById('action-sheet-preview').textContent = `«${shortText}»`;
      renderSheetReactionsUI(msg);

      const delBtn = document.getElementById('sheet-delete-msg-btn');
      if (delBtn) delBtn.style.display = canDeleteSelectedMessage() ? 'block' : 'none';

      document.getElementById('msg-action-sheet').classList.add('active');
    }

    function closeMessageMenu(event) {
      if (event && event.target !== event.currentTarget) return;
      document.getElementById('msg-action-sheet').classList.remove('active');
    }

    function toggleReactionOnSelected(emoji) {
      if (selectedMessage) toggleReactionOnMessage(selectedMessage, emoji, true);
    }

    function toggleReactionOnMessage(msg, emoji, keepSheetOpen = false) {
      if (!currentUser || !activePeer || !msg || !REACTION_EMOJIS.includes(emoji)) return;
      const peerId = activePeer.id;
      const updatedMsg = applyReactionToggleToMessage(msg, emoji, currentUser);

      currentMessagesCache = currentMessagesCache.map(m => m.id === msg.id ? updatedMsg : m);
      if (selectedMessage && selectedMessage.id === msg.id) selectedMessage = updatedMsg;

      writeLocalDialog(currentUser.id, peerId, currentMessagesCache);
      renderMessages(currentMessagesCache, false);
      if (keepSheetOpen) renderSheetReactionsUI(updatedMsg);

      fetch('/api/messages/reaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        keepalive: true,
        body: JSON.stringify({ message_id: msg.id, user_id: currentUser.id, nickname: currentUser.nickname, emoji })
      }).catch(() => {});
    }

    function showCopyToast(text) {
      const toast = document.getElementById('copy-toast');
      toast.textContent = text;
      toast.classList.add('active');
      setTimeout(() => toast.classList.remove('active'), 1600);
    }

    function triggerCopyMessage() {
      if (!selectedMessage) return;
      const textToCopy = selectedMessage.text || '';
      document.getElementById('msg-action-sheet').classList.remove('active');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textToCopy).then(() => showCopyToast('Сообщение скопировано')).catch(() => fallbackCopy(textToCopy));
      } else fallbackCopy(textToCopy);
      selectedMessage = null;
    }

    function fallbackCopy(text) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showCopyToast('Скопировано');
      } catch (e) { showCopyToast('Не удалось скопировать'); }
    }

    function triggerReplyMessage() {
      if (!selectedMessage) return;
      const senderNick = selectedMessage.sender_id === currentUser.id
        ? currentUser.nickname
        : (selectedMessage.sender_nick || activePeer.nickname);
      replyingToMessage = { id: selectedMessage.id, sender_nick: senderNick, text: selectedMessage.text };
      document.getElementById('reply-banner-text').textContent = `Ответ для ${senderNick}: ${selectedMessage.text}`;
      document.getElementById('reply-banner').classList.add('active');
      document.getElementById('msg-action-sheet').classList.remove('active');
      document.getElementById('chat-message-input').focus();
      handleComposerFocus();
    }

    function cancelReply() {
      replyingToMessage = null;
      document.getElementById('reply-banner').classList.remove('active');
    }

    function triggerDeleteMessage() {
      if (!selectedMessage || !activePeer) return;
      if (!canDeleteSelectedMessage()) {
        showCopyToast('Удалять сообщения в группе может только владелец');
        document.getElementById('msg-action-sheet').classList.remove('active');
        return;
      }

      const targetId = selectedMessage.id;
      const peerId = activePeer.id;
      document.getElementById('msg-action-sheet').classList.remove('active');

      currentMessagesCache = currentMessagesCache.filter(m => m.id !== targetId);
      writeLocalDialog(currentUser.id, peerId, currentMessagesCache);
      renderMessages(currentMessagesCache, false);

      if (!String(targetId).startsWith('msg_')) {
        fetch('/api/messages/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          keepalive: true,
          body: JSON.stringify({ message_id: targetId, user_id: currentUser.id })
        })
          .then(r => r.json())
          .then(data => {
            if (data.error) {
              showCopyToast(data.error);
              fetchMessages();
            }
          })
          .catch(() => {});
      }
      selectedMessage = null;
    }

    function openSettingsScreen() {
      document.getElementById('settings-error').textContent = '';
      document.getElementById('settings-ok').textContent = '';
      document.getElementById('custom-saved-msg').textContent = '';
      document.getElementById('privacy-error').textContent = '';
      document.getElementById('privacy-ok').textContent = '';
      document.getElementById('settings-user-id').textContent = currentUser.id || '—';
      document.getElementById('settings-nick').value = currentUser.nickname;
      selectedAvatar = resolveAvatar(currentUser.id, currentUser.avatar);
      currentUser.avatar = selectedAvatar;
      localStorage.setItem(`pigeon_avatar_${currentUser.id}`, selectedAvatar);
      updateHeaderUI();

      document.getElementById('user-avatar-photo-status').textContent = isImageAvatar(selectedAvatar)
        ? 'Выбрано фото'
        : `Выбран эмодзи ${selectedAvatar}`;

      const passed = Date.now() - (currentUser.lastNickChange || 0);
      const nickInput = document.getElementById('settings-nick');
      const hint = document.getElementById('nick-timer-hint');
      if (passed < 7 * 24 * 60 * 60 * 1000) {
        nickInput.disabled = true;
        hint.textContent = `Смена никнейма доступна через ${Math.ceil((7 * 24 * 60 * 60 * 1000 - passed) / 86400000)} дн.`;
      } else {
        nickInput.disabled = false;
        hint.textContent = 'Никнейм можно менять 1 раз в неделю.';
      }

      const grid = document.getElementById('avatar-grid');
      grid.innerHTML = '';
      ALLOWED_AVATARS.forEach(emoji => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'avatar-option' + (!isImageAvatar(selectedAvatar) && emoji === selectedAvatar ? ' selected' : '');
        btn.textContent = emoji;
        btn.onclick = () => {
          selectedAvatar = emoji;
          document.querySelectorAll('#avatar-grid .avatar-option').forEach(el => el.classList.remove('selected'));
          btn.classList.add('selected');
          document.getElementById('user-avatar-photo-status').textContent = `Выбран эмодзи ${emoji}`;
          currentUser.avatar = emoji;
          localStorage.setItem(`pigeon_avatar_${currentUser.id}`, emoji);
          updateHeaderUI();
          fetch('/api/update-profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            cache: 'no-store',
            body: JSON.stringify({ id: currentUser.id, newNickname: currentUser.nickname, newAvatar: emoji })
          }).then(() => loadChatsList()).catch(() => {});
        };
        grid.appendChild(btn);
      });

      selectedDmPolicy = currentUser.dm_policy === 'nobody' ? 'nobody' : 'all';
      applyPrivacyUI();
      applyCustomizationToUI();
      switchSettingsTab('main');
      document.getElementById('settings-screen').classList.add('active');
      updateFabVisibility();
    }

    function closeSettingsScreen() {
      document.getElementById('settings-screen').classList.remove('active');
      updateFabVisibility();
      loadChatsList();
    }

    function switchSettingsTab(tab) {
      document.getElementById('stab-main').classList.toggle('active', tab === 'main');
      document.getElementById('stab-custom').classList.toggle('active', tab === 'custom');
      document.getElementById('stab-privacy').classList.toggle('active', tab === 'privacy');
      document.getElementById('ssec-main').classList.toggle('active', tab === 'main');
      document.getElementById('ssec-custom').classList.toggle('active', tab === 'custom');
      document.getElementById('ssec-privacy').classList.toggle('active', tab === 'privacy');
    }

    function applyPrivacyUI() {
      document.getElementById('privacy-all-btn').classList.toggle('selected', selectedDmPolicy === 'all');
      document.getElementById('privacy-nobody-btn').classList.toggle('selected', selectedDmPolicy === 'nobody');
    }

    function selectDmPolicy(policy) {
      selectedDmPolicy = policy === 'nobody' ? 'nobody' : 'all';
      applyPrivacyUI();
      document.getElementById('privacy-ok').textContent = '';
      document.getElementById('privacy-error').textContent = '';
    }

    async function savePrivacySettings() {
      if (!currentUser) return;
      const errEl = document.getElementById('privacy-error');
      const okEl = document.getElementById('privacy-ok');
      errEl.textContent = '';
      okEl.textContent = '';
      currentUser.dm_policy = selectedDmPolicy;

      try {
        const res = await fetch('/api/update-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({ id: currentUser.id, dm_policy: selectedDmPolicy })
        });
        const data = await res.json();
        if (!res.ok) {
          errEl.textContent = data.error || 'Не удалось сохранить настройки';
          return;
        }
        currentUser = { ...currentUser, ...data.user };
        okEl.textContent = 'Настройки конфиденциальности сохранены!';
      } catch (e) {
        errEl.textContent = 'Нет связи с сервером';
      }
    }

    function selectMsgSize(size) { customization.msgSize = size; applyCustomizationToUI(); }

    function selectAppTheme(themeName) {
      if (!ALLOWED_THEMES.includes(themeName)) return;
      customization.theme = themeName;
      localStorage.setItem('pigeon_customization', JSON.stringify(customization));
      applyCustomizationToUI();
      document.getElementById('custom-saved-msg').textContent = '';
    }

    function saveCustomization() {
      localStorage.setItem('pigeon_customization', JSON.stringify(customization));
      applyCustomizationToUI();
      document.getElementById('custom-saved-msg').textContent = 'Кастомизация сохранена!';
      if (activePeer) renderMessages(currentMessagesCache, false);
    }

    async function saveMainSettings() {
      const newNickname = document.getElementById('settings-nick').value;
      const errorEl = document.getElementById('settings-error');
      const okEl = document.getElementById('settings-ok');
      errorEl.textContent = '';
      okEl.textContent = '';

      selectedAvatar = normalizeAvatar(selectedAvatar, DEFAULT_AVATAR);
      currentUser.avatar = selectedAvatar;
      localStorage.setItem(`pigeon_avatar_${currentUser.id}`, selectedAvatar);
      updateHeaderUI();
      okEl.textContent = 'Профиль обновлён!';

      try {
        const res = await fetch('/api/update-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({ id: currentUser.id, newNickname, newAvatar: selectedAvatar })
        });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error || 'Ошибка сохранения никнейма на сервере'; return; }
        currentUser = { ...data.user, avatar: normalizeAvatar(data.user.avatar || selectedAvatar, DEFAULT_AVATAR) };
        document.getElementById('settings-user-id').textContent = currentUser.id || '—';
        updateHeaderUI();
        loadChatsList();
      } catch (err) { errorEl.textContent = 'Аватарка сохранена локально, но нет связи с сервером'; }
    }

    function logout() {
      localStorage.removeItem('pigeon_user_id');
      currentUser = null;
      if (chatsListPollTimer) { clearInterval(chatsListPollTimer); chatsListPollTimer = null; }
      closeChatRoom();
      closeSettingsScreen();
      closeSearchScreen();
      closeCreateGroupScene();
      closeChatSettingsScene();
      updateFabVisibility();
      document.getElementById('main-screen').classList.remove('active');
      document.getElementById('auth-nick').value = '';
      document.getElementById('auth-pass').value = '';
      document.getElementById('auth-screen').classList.add('active');
    }

    function escapeHtml(str) {
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
  </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    nickname = (data.get('nickname') or '').strip()
    password = data.get('password') or ''

    if not nickname or not password:
        return jsonify({'error': 'Введи никнейм и пароль!'}), 400
    if len(nickname) < 2 or len(nickname) > 20:
        return jsonify({'error': 'Никнейм должен быть от 2 до 20 символов'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Пароль должен быть минимум 4 символа'}), 400

    db = load_db(force_refresh=True)
    users = db['users']
    if any(u['nickname'].lower() == nickname.lower() for u in users):
        return jsonify({'error': 'Этот никнейм уже занят!'}), 400

    now_ms = int(time.time() * 1000)
    uid = str(now_ms)
    new_user = {
        'id': uid,
        'nickname': nickname,
        'password': password,
        'avatar': DEFAULT_AVATAR,
        'dm_policy': 'all',
        'verified': has_any_checkmark(uid),
        'lastNickChange': now_ms
    }
    users.append(new_user)
    save_db(db)
    return jsonify({'user': safe_user(new_user), 'avatars': ALLOWED_AVATARS})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    nickname = (data.get('nickname') or '').strip()
    password = data.get('password') or ''

    if not nickname or not password:
        return jsonify({'error': 'Введи никнейм и пароль!'}), 400

    db = load_db(force_refresh=True)
    user = next(
        (u for u in db['users'] if u['nickname'].lower() == nickname.lower() and u['password'] == password),
        None
    )
    if not user:
        return jsonify({'error': 'Неверный никнейм или пароль'}), 401

    user['avatar'] = normalize_avatar(user.get('avatar'), DEFAULT_AVATAR)
    user['dm_policy'] = normalize_dm_policy(user.get('dm_policy'))
    user['verified'] = has_any_checkmark(user.get('id'))
    return jsonify({'user': safe_user(user), 'avatars': ALLOWED_AVATARS})


@app.route('/api/me', methods=['POST'])
def me():
    data = request.get_json() or {}
    user_id = data.get('id')
    db = load_db(force_refresh=True)
    user = next((u for u in db['users'] if u['id'] == user_id), None)
    if not user:
        return jsonify({'error': 'Аккаунт не найден'}), 404
    user['avatar'] = normalize_avatar(user.get('avatar'), DEFAULT_AVATAR)
    user['dm_policy'] = normalize_dm_policy(user.get('dm_policy'))
    user['verified'] = has_any_checkmark(user.get('id'))
    return jsonify({'user': safe_user(user), 'avatars': ALLOWED_AVATARS})


@app.route('/api/users/search', methods=['GET'])
def search_users():
    q = (request.args.get('q') or '').strip().lower()
    exclude_id = (request.args.get('exclude_id') or '').strip()
    if not q:
        return jsonify({'users': []})
    db = load_db()
    matched = [
        {
            'id': u['id'],
            'nickname': u['nickname'],
            'avatar': normalize_avatar(u.get('avatar'), DEFAULT_AVATAR),
            'dm_policy': normalize_dm_policy(u.get('dm_policy')),
            'verified': has_any_checkmark(u.get('id')),
            'badge_color': get_badge_color_for_user_id(u.get('id'))
        }
        for u in db['users']
        if (not exclude_id or u['id'] != exclude_id) and u['nickname'].lower().startswith(q)
    ]
    return jsonify({'users': matched})


@app.route('/api/update-profile', methods=['POST'])
def update_profile():
    data = request.get_json() or {}
    user_id = data.get('id')
    new_nickname = (data.get('newNickname') or '').strip()
    new_avatar = data.get('newAvatar')
    new_dm_policy = data.get('dm_policy')

    db = load_db(force_refresh=True)
    users = db['users']
    user_index = next((i for i, u in enumerate(users) if u['id'] == user_id), -1)
    if user_index == -1:
        return jsonify({'error': 'Пользователь не найден'}), 404

    user = users[user_index]
    user['avatar'] = normalize_avatar(user.get('avatar'), DEFAULT_AVATAR)
    user['dm_policy'] = normalize_dm_policy(user.get('dm_policy'))

    if new_avatar is not None and str(new_avatar).strip():
        if not is_image_avatar(new_avatar) and str(new_avatar).strip() not in ALLOWED_AVATARS:
            return jsonify({'error': 'Недопустимая аватарка'}), 400
        user['avatar'] = normalize_avatar(new_avatar, user['avatar'])

    if new_dm_policy is not None:
        if new_dm_policy not in ALLOWED_DM_POLICIES:
            return jsonify({'error': 'Недопустимое значение конфиденциальности'}), 400
        user['dm_policy'] = new_dm_policy

    if new_nickname and new_nickname != user['nickname']:
        if len(new_nickname) < 2 or len(new_nickname) > 20:
            return jsonify({'error': 'Никнейм от 2 до 20 символов'}), 400

        now_ms = int(time.time() * 1000)
        time_passed = now_ms - user.get('lastNickChange', 0)
        if time_passed < WEEK_MS:
            days_left = -(-(WEEK_MS - time_passed) // (1000 * 60 * 60 * 24))
            return jsonify({'error': f'Никнейм можно менять раз в неделю. Осталось дн.: {days_left}'}), 400

        exists = any(idx != user_index and u['nickname'].lower() == new_nickname.lower() for idx, u in enumerate(users))
        if exists:
            return jsonify({'error': 'Этот никнейм уже занят!'}), 400

        user['nickname'] = new_nickname
        user['lastNickChange'] = now_ms

    user['verified'] = has_any_checkmark(user.get('id'))
    users[user_index] = user
    save_db(db)
    return jsonify({'user': safe_user(user)})


@app.route('/api/groups/create', methods=['POST'])
def create_group():
    data = request.get_json() or {}
    creator_id = (data.get('creator_id') or '').strip()
    name = (data.get('name') or '').strip()
    icon_raw = (data.get('icon') or DEFAULT_GROUP_ICON).strip()
    raw_members = data.get('member_ids') if isinstance(data.get('member_ids'), list) else []

    if not creator_id or len(name) < 2:
        return jsonify({'error': 'Укажи название группы'}), 400
    if not is_image_avatar(icon_raw) and icon_raw not in GROUP_ICONS:
        icon_raw = DEFAULT_GROUP_ICON

    members = []
    for mid in [creator_id] + [str(m).strip() for m in raw_members if str(m).strip()]:
        if mid not in members:
            members.append(mid)

    now_ms = int(time.time() * 1000)
    db = load_db(force_refresh=True)
    users_by_id = {u['id']: u for u in db['users']}
    group_id = f'grp_{now_ms}'
    group_obj = {
        'id': group_id,
        'name': name[:32],
        'icon': normalize_group_icon(icon_raw, DEFAULT_GROUP_ICON),
        'owner_id': creator_id,
        'members': members,
        'muted_members': [],
        'created_at': now_ms
    }
    db['groups'].append(group_obj)

    for idx, mid in enumerate(members):
        if mid == creator_id:
            continue
        nick = users_by_id.get(mid, {}).get('nickname', 'Пользователь')
        make_system_group_message(db, group_id, f'{nick} зашел', now_ms + idx + 1)

    save_db(db)
    return jsonify({'group': serialize_group(group_obj, users_by_id)})


@app.route('/api/groups/update', methods=['POST'])
def update_group():
    data = request.get_json() or {}
    group_id = (data.get('group_id') or '').strip()
    user_id = (data.get('user_id') or '').strip()
    db = load_db(force_refresh=True)
    users_by_id = {u['id']: u for u in db['users']}

    grp = next((g for g in db['groups'] if g.get('id') == group_id), None)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    if not user_id or grp.get('owner_id') != user_id:
        return jsonify({'error': 'Только владелец группы может изменять её настройки'}), 403

    if 'name' in data and isinstance(data.get('name'), str):
        clean_name = data['name'].strip()
        if len(clean_name) >= 2:
            grp['name'] = clean_name[:32]
    if 'icon' in data and isinstance(data.get('icon'), str):
        ic_val = data['icon'].strip()
        if is_image_avatar(ic_val) or ic_val in GROUP_ICONS:
            grp['icon'] = normalize_group_icon(ic_val, DEFAULT_GROUP_ICON)

    save_db(db)
    return jsonify({'group': serialize_group(grp, users_by_id)})


@app.route('/api/groups/add-members', methods=['POST'])
def add_group_members():
    data = request.get_json() or {}
    group_id = (data.get('group_id') or '').strip()
    user_id = (data.get('user_id') or '').strip()
    raw_members = data.get('member_ids') if isinstance(data.get('member_ids'), list) else []

    db = load_db(force_refresh=True)
    users_by_id = {u['id']: u for u in db['users']}
    grp = next((g for g in db['groups'] if g.get('id') == group_id), None)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    if not user_id or grp.get('owner_id') != user_id:
        return jsonify({'error': 'Только владелец группы может добавлять участников'}), 403

    members = list(grp.get('members') or [])
    now_ms = int(time.time() * 1000)
    added_idx = 0
    for mid in raw_members:
        sid = str(mid).strip()
        if sid and sid not in members:
            members.append(sid)
            nick = users_by_id.get(sid, {}).get('nickname', 'Пользователь')
            make_system_group_message(db, group_id, f'{nick} зашел', now_ms + added_idx)
            added_idx += 1

    grp['members'] = members
    save_db(db)
    return jsonify({'group': serialize_group(grp, users_by_id)})


@app.route('/api/groups/member-action', methods=['POST'])
def group_member_action():
    data = request.get_json() or {}
    group_id = (data.get('group_id') or '').strip()
    user_id = (data.get('user_id') or '').strip()
    target_user_id = (data.get('target_user_id') or '').strip()
    action = (data.get('action') or '').strip()

    db = load_db(force_refresh=True)
    users_by_id = {u['id']: u for u in db['users']}
    grp = next((g for g in db['groups'] if g.get('id') == group_id), None)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    if not user_id or grp.get('owner_id') != user_id:
        return jsonify({'error': 'Только владелец группы может управлять участниками'}), 403
    if not target_user_id or target_user_id == grp.get('owner_id'):
        return jsonify({'error': 'Нельзя применить это действие к владельцу группы'}), 400

    members = list(grp.get('members') or [])
    muted_members = list(grp.get('muted_members') or [])

    if action == 'mute':
        if target_user_id in members and target_user_id not in muted_members:
            muted_members.append(target_user_id)
    elif action == 'unmute':
        muted_members = [m for m in muted_members if m != target_user_id]
    elif action == 'remove':
        if target_user_id in members:
            target_nick = users_by_id.get(target_user_id, {}).get('nickname', 'Пользователь')
            owner_nick = users_by_id.get(user_id, {}).get('nickname', 'Владелец')
            make_system_group_message(db, group_id, f'{target_nick} был удалён {owner_nick}')
        members = [m for m in members if m != target_user_id]
        muted_members = [m for m in muted_members if m != target_user_id]
    else:
        return jsonify({'error': 'Неизвестное действие'}), 400

    grp['members'] = members
    grp['muted_members'] = muted_members
    save_db(db)
    return jsonify({'group': serialize_group(grp, users_by_id)})


@app.route('/api/groups/leave', methods=['POST'])
def leave_group():
    data = request.get_json() or {}
    group_id = (data.get('group_id') or '').strip()
    user_id = (data.get('user_id') or '').strip()

    db = load_db(force_refresh=True)
    users_by_id = {u['id']: u for u in db['users']}
    grp = next((g for g in db['groups'] if g.get('id') == group_id), None)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    if not user_id:
        return jsonify({'error': 'Не указан пользователь'}), 400

    nick = users_by_id.get(user_id, {}).get('nickname', 'Пользователь')
    members = [m for m in (grp.get('members') or []) if m != user_id]
    muted_members = [m for m in (grp.get('muted_members') or []) if m != user_id]

    if grp.get('owner_id') == user_id:
        if len(members) == 0:
            db['groups'] = [g for g in db['groups'] if g.get('id') != group_id]
            db['messages'] = [m for m in db['messages'] if m.get('group_id') != group_id]
            save_db(db)
            return jsonify({'ok': True, 'deleted': True, 'left_group_id': group_id})
        new_owner = members[0]
        grp['owner_id'] = new_owner
        muted_members = [m for m in muted_members if m != new_owner]

    grp['members'] = members
    grp['muted_members'] = muted_members
    make_system_group_message(db, group_id, f'{nick} вышел')
    save_db(db)
    return jsonify({'ok': True, 'left_group_id': group_id, 'group': serialize_group(grp, users_by_id)})


@app.route('/api/groups/delete', methods=['POST'])
def delete_group():
    data = request.get_json() or {}
    group_id = (data.get('group_id') or '').strip()
    user_id = (data.get('user_id') or '').strip()
    db = load_db(force_refresh=True)

    grp = next((g for g in db['groups'] if g.get('id') == group_id), None)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    if not user_id or grp.get('owner_id') != user_id:
        return jsonify({'error': 'Только владелец группы может удалить её'}), 403

    db['groups'] = [g for g in db['groups'] if g.get('id') != group_id]
    db['messages'] = [m for m in db['messages'] if m.get('group_id') != group_id]
    save_db(db)
    return jsonify({'ok': True, 'deleted_id': group_id})


@app.route('/api/chats/delete', methods=['POST'])
def delete_direct_chat():
    data = request.get_json() or {}
    user_id = (data.get('user_id') or '').strip()
    peer_id = (data.get('peer_id') or '').strip()
    if not user_id or not peer_id:
        return jsonify({'error': 'Не указан пользователь или собеседник'}), 400

    db = load_db(force_refresh=True)
    db['messages'] = [
        m for m in db['messages']
        if m.get('group_id')
        or not ((m.get('sender_id') == user_id and m.get('receiver_id') == peer_id)
                or (m.get('sender_id') == peer_id and m.get('receiver_id') == user_id))
    ]
    save_db(db)
    return jsonify({'ok': True, 'deleted_peer_id': peer_id})


@app.route('/api/chats', methods=['GET'])
def get_chats():
    user_id = (request.args.get('user_id') or '').strip()
    if not user_id:
        return jsonify({'chats': []})

    db = load_db()
    users_by_id = {u['id']: u for u in db['users']}
    partner_ids = set()

    for m in db['messages']:
        if m.get('group_id'):
            continue
        if m.get('sender_id') == user_id and m.get('receiver_id'):
            partner_ids.add(m['receiver_id'])
        elif m.get('receiver_id') == user_id and m.get('sender_id'):
            partner_ids.add(m['sender_id'])

    chats = []
    for pid in partner_ids:
        partner = users_by_id.get(pid)
        if not partner:
            continue
        dialog = [
            m for m in db['messages']
            if not m.get('group_id')
            and ((m.get('sender_id') == user_id and m.get('receiver_id') == pid)
                 or (m.get('sender_id') == pid and m.get('receiver_id') == user_id))
        ]
        dialog.sort(key=lambda x: x.get('timestamp', 0))
        last_msg = dialog[-1] if dialog else None

        chats.append({
            'id': partner['id'],
            'nickname': partner['nickname'],
            'avatar': normalize_avatar(partner.get('avatar'), DEFAULT_AVATAR),
            'dm_policy': normalize_dm_policy(partner.get('dm_policy')),
            'verified': has_any_checkmark(partner['id']),
            'badge_color': get_badge_color_for_user_id(partner['id']),
            'isGroup': False,
            'lastMessage': last_msg.get('text', '') if last_msg else '',
            'lastSenderId': last_msg.get('sender_id', '') if last_msg else '',
            'lastTimestamp': last_msg.get('timestamp', 0) if last_msg else 0
        })

    for grp in db['groups']:
        members = grp.get('members') or []
        if user_id not in members and grp.get('owner_id') != user_id:
            continue
        ser_grp = serialize_group(grp, users_by_id)
        gid = ser_grp['id']
        g_msgs = [m for m in db['messages'] if m.get('group_id') == gid]
        g_msgs.sort(key=lambda x: x.get('timestamp', 0))
        last_msg = g_msgs[-1] if g_msgs else None
        last_sender = users_by_id.get(last_msg.get('sender_id', ''), {}) if last_msg else {}

        chats.append({
            'id': gid,
            'nickname': ser_grp['name'],
            'avatar': ser_grp['icon'],
            'verified': False,
            'badge_color': None,
            'isGroup': True,
            'ownerId': ser_grp['owner_id'],
            'members': ser_grp['members'],
            'mutedMembers': ser_grp['muted_members'],
            'memberDetails': ser_grp['member_details'],
            'lastMessage': last_msg.get('text', '') if last_msg else '',
            'lastSenderId': last_msg.get('sender_id', '') if last_msg else '',
            'lastSenderName': last_sender.get('nickname', '') if last_msg else '',
            'lastTimestamp': last_msg.get('timestamp', 0) if last_msg else ser_grp['created_at']
        })

    chats.sort(key=lambda c: c['lastTimestamp'], reverse=True)
    return jsonify({'chats': chats})


@app.route('/api/messages', methods=['GET'])
def get_messages():
    user_id = (request.args.get('user_id') or '').strip()
    peer_id = (request.args.get('peer_id') or '').strip()
    group_id = (request.args.get('group_id') or '').strip()

    db = load_db()
    users_by_id = {u['id']: u for u in db['users']}
    if group_id:
        grp = next((g for g in db['groups'] if g.get('id') == group_id), None)
        if not grp:
            return jsonify({'messages': [], 'group': None})
        g_msgs = [m for m in db['messages'] if m.get('group_id') == group_id]
        g_msgs.sort(key=lambda x: x.get('timestamp', 0))
        return jsonify({'messages': g_msgs, 'group': serialize_group(grp, users_by_id)})

    if not user_id or not peer_id:
        return jsonify({'messages': []})

    dialog = [
        m for m in db['messages']
        if not m.get('group_id')
        and ((m.get('sender_id') == user_id and m.get('receiver_id') == peer_id)
             or (m.get('sender_id') == peer_id and m.get('receiver_id') == user_id))
    ]
    dialog.sort(key=lambda x: x.get('timestamp', 0))
    return jsonify({'messages': dialog})


@app.route('/api/messages/send', methods=['POST'])
def send_message():
    data = request.get_json() or {}
    sender_id = (data.get('sender_id') or '').strip()
    receiver_id = (data.get('receiver_id') or '').strip()
    group_id = (data.get('group_id') or '').strip()
    text = (data.get('text') or '').strip()
    reply_to = data.get('reply_to')

    if not sender_id or not text:
        return jsonify({'error': 'Пустое сообщение'}), 400
    if not group_id and not receiver_id:
        return jsonify({'error': 'Не указан получатель или группа'}), 400
    if len(text) > 1000:
        return jsonify({'error': 'Сообщение слишком длинное'}), 400

    db = load_db()
    users_by_id = {u['id']: u for u in db['users']}

    if group_id:
        grp = next((g for g in db['groups'] if g.get('id') == group_id), None)
        if not grp:
            return jsonify({'error': 'Группа не найдена'}), 404
        members = grp.get('members') or []
        if sender_id not in members and grp.get('owner_id') != sender_id:
            return jsonify({'error': 'Вы не состоите в этой группе'}), 403
        if grp.get('owner_id') != sender_id and sender_id in (grp.get('muted_members') or []):
            return jsonify({'error': 'Владелец группы запретил вам писать сообщения'}), 403
    else:
        if users_by_id and (sender_id not in users_by_id or receiver_id not in users_by_id):
            return jsonify({'error': 'Пользователь не найден'}), 404
        recipient = users_by_id.get(receiver_id)
        if recipient and normalize_dm_policy(recipient.get('dm_policy')) == 'nobody' and sender_id != receiver_id:
            return jsonify({'error': 'Пользователь запретил входящие сообщения (Никто)'}), 403

    now_ms = int(time.time() * 1000)
    clean_reply = None
    if isinstance(reply_to, dict) and reply_to.get('text'):
        clean_reply = {
            'id': str(reply_to.get('id', '')),
            'sender_nick': str(reply_to.get('sender_nick', ''))[:30],
            'text': str(reply_to.get('text', ''))[:120]
        }

    sender_nick = users_by_id.get(sender_id, {}).get('nickname', 'Участник')
    msg = {
        'id': f'{now_ms}_{len(db["messages"]) + 1}',
        'sender_id': sender_id,
        'sender_nick': sender_nick,
        'receiver_id': '' if group_id else receiver_id,
        'group_id': group_id,
        'text': text,
        'timestamp': now_ms,
        'reply_to': clean_reply,
        'reactions': {}
    }
    db['messages'].append(msg)
    save_db(db, async_cloud=True)
    return jsonify({'message': msg})


@app.route('/api/messages/reaction', methods=['POST'])
def toggle_reaction():
    data = request.get_json() or {}
    msg_id = (data.get('message_id') or '').strip()
    user_id = (data.get('user_id') or '').strip()
    emoji = (data.get('emoji') or '').strip()

    if not msg_id or not user_id or emoji not in ALLOWED_REACTIONS:
        return jsonify({'error': 'Некорректные данные реакции'}), 400

    db = load_db()
    users_by_id = {u['id']: u for u in db['users']}
    nickname = (data.get('nickname') or '').strip() or (users_by_id.get(user_id, {}).get('nickname') or 'Пользователь')

    target_msg = next((m for m in db['messages'] if m.get('id') == msg_id), None)
    if not target_msg:
        return jsonify({'ok': True, 'reactions': {}})

    reactions = target_msg.get('reactions') if isinstance(target_msg.get('reactions'), dict) else {}
    had_this = False
    next_reactions = {}

    for em, users_list in reactions.items():
        if em not in ALLOWED_REACTIONS or not isinstance(users_list, list):
            continue
        if any(u.get('user_id') == user_id for u in users_list if isinstance(u, dict)) and em == emoji:
            had_this = True
        filtered = [u for u in users_list if isinstance(u, dict) and u.get('user_id') != user_id]
        if filtered:
            next_reactions[em] = filtered

    if not had_this:
        next_reactions.setdefault(emoji, []).append({'user_id': user_id, 'nickname': nickname})

    target_msg['reactions'] = next_reactions
    save_db(db, async_cloud=True)
    return jsonify({'ok': True, 'reactions': next_reactions})


@app.route('/api/messages/delete', methods=['POST'])
def delete_message():
    data = request.get_json() or {}
    msg_id = (data.get('message_id') or '').strip()
    user_id = (data.get('user_id') or '').strip()

    if not msg_id:
        return jsonify({'error': 'Не указан ID сообщения'}), 400

    db = load_db()
    target_msg = next((m for m in db['messages'] if m.get('id') == msg_id), None)
    if not target_msg:
        return jsonify({'error': 'Сообщение не найдено'}), 404

    gid = (target_msg.get('group_id') or '').strip()
    if gid:
        grp = next((g for g in db['groups'] if g.get('id') == gid), None)
        if not grp:
            return jsonify({'error': 'Группа не найдена'}), 404
        if not user_id or grp.get('owner_id') != user_id:
            return jsonify({'error': 'Удалять сообщения в группе может только владелец'}), 403
    else:
        if user_id and target_msg.get('sender_id') != user_id and target_msg.get('receiver_id') != user_id:
            return jsonify({'error': 'Нет прав на удаление сообщения'}), 403

    db['messages'] = [m for m in db['messages'] if m.get('id') != msg_id]
    save_db(db, async_cloud=True)
    return jsonify({'ok': True, 'deleted_id': msg_id})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
