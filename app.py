import os
import json
import time
import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
DB_FILE = 'users.json'

JSONBIN_BIN_ID = os.environ.get('JSONBIN_BIN_ID', '').strip()
JSONBIN_API_KEY = os.environ.get('JSONBIN_API_KEY', '').strip()

# 17 аватарок: заменено 🧩 на 🍐, сохранены 🦜, 🐗, 🎩
ALLOWED_AVATARS = [
    '🕊️', '🦜', '🐗', '🎩', '🚀', '🤖',
    '😎', '👻', '🔥', '⭐', '🎮', '💎',
    '🍕', '⚡', '👑', '🎨', '🍐'
]

WEEK_MS = 7 * 24 * 60 * 60 * 1000


def use_cloud_db() -> bool:
    return bool(JSONBIN_BIN_ID and JSONBIN_API_KEY)


def load_db():
    default_db = {'users': [], 'messages': []}

    if use_cloud_db():
        url = f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest'
        headers = {'X-Master-Key': JSONBIN_API_KEY}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            record = resp.json().get('record', {})

            if isinstance(record, list):
                return {'users': record, 'messages': []}
            if isinstance(record, dict):
                return {
                    'users': record.get('users') if isinstance(record.get('users'), list) else [],
                    'messages': record.get('messages') if isinstance(record.get('messages'), list) else []
                }
            return default_db
        except Exception as e:
            print(f'Ошибка загрузки из JSONBin: {e}')
            return default_db

    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_db, f, ensure_ascii=False, indent=2)
        return default_db
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return {'users': data, 'messages': []}
            if isinstance(data, dict):
                return {
                    'users': data.get('users', []),
                    'messages': data.get('messages', [])
                }
            return default_db
    except Exception:
        return default_db


def save_db(db_data):
    payload = {
        'users': db_data.get('users', []),
        'messages': db_data.get('messages', [])
    }

    if use_cloud_db():
        url = f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}'
        headers = {
            'Content-Type': 'application/json',
            'X-Master-Key': JSONBIN_API_KEY
        }
        try:
            resp = requests.put(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            return
        except Exception as e:
            print(f'Ошибка сохранения в JSONBin: {e}')

    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def has_blue_checkmark(nickname: str) -> bool:
    return nickname.strip().lower() == 'владислав'


def safe_user(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != 'password'}


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


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

    db = load_db()
    users = db['users']

    if any(u['nickname'].lower() == nickname.lower() for u in users):
        return jsonify({'error': 'Этот никнейм уже занят!'}), 400

    now_ms = int(time.time() * 1000)
    new_user = {
        'id': str(now_ms),
        'nickname': nickname,
        'password': password,
        'avatar': '🕊️',
        'verified': has_blue_checkmark(nickname),
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

    db = load_db()
    user = next(
        (u for u in db['users'] if u['nickname'].lower() == nickname.lower() and u['password'] == password),
        None
    )

    if not user:
        return jsonify({'error': 'Неверный никнейм или пароль'}), 401

    user['verified'] = has_blue_checkmark(user['nickname'])
    return jsonify({'user': safe_user(user), 'avatars': ALLOWED_AVATARS})


@app.route('/api/me', methods=['POST'])
def me():
    data = request.get_json() or {}
    user_id = data.get('id')

    db = load_db()
    user = next((u for u in db['users'] if u['id'] == user_id), None)

    if not user:
        return jsonify({'error': 'Аккаунт не найден'}), 404

    user['verified'] = has_blue_checkmark(user['nickname'])
    return jsonify({'user': safe_user(user), 'avatars': ALLOWED_AVATARS})


@app.route('/api/users/search', methods=['GET'])
def search_users():
    q = (request.args.get('q') or '').strip().lower()
    if not q:
        return jsonify({'users': []})

    db = load_db()
    matched = [
        {
            'id': u['id'],
            'nickname': u['nickname'],
            'avatar': u.get('avatar', '🕊️'),
            'verified': has_blue_checkmark(u['nickname'])
        }
        for u in db['users']
        if u['nickname'].lower().startswith(q)
    ]

    return jsonify({'users': matched})


@app.route('/api/update-profile', methods=['POST'])
def update_profile():
    data = request.get_json() or {}
    user_id = data.get('id')
    new_nickname = (data.get('newNickname') or '').strip()
    new_avatar = data.get('newAvatar')

    db = load_db()
    users = db['users']
    user_index = next((i for i, u in enumerate(users) if u['id'] == user_id), -1)

    if user_index == -1:
        return jsonify({'error': 'Пользователь не найден'}), 404

    user = users[user_index]

    if new_avatar:
        if new_avatar not in ALLOWED_AVATARS:
            return jsonify({'error': 'Недопустимая аватарка'}), 400
        user['avatar'] = new_avatar

    if new_nickname and new_nickname != user['nickname']:
        if len(new_nickname) < 2 or len(new_nickname) > 20:
            return jsonify({'error': 'Никнейм от 2 до 20 символов'}), 400

        now_ms = int(time.time() * 1000)
        time_passed = now_ms - user.get('lastNickChange', 0)

        if time_passed < WEEK_MS:
            days_left = -(-(WEEK_MS - time_passed) // (1000 * 60 * 60 * 24))
            return jsonify({
                'error': f'Никнейм можно менять раз в неделю. Осталось дн.: {days_left}'
            }), 400

        exists = any(
            idx != user_index and u['nickname'].lower() == new_nickname.lower()
            for idx, u in enumerate(users)
        )
        if exists:
            return jsonify({'error': 'Этот никнейм уже занят!'}), 400

        user['nickname'] = new_nickname
        user['verified'] = has_blue_checkmark(new_nickname)
        user['lastNickChange'] = now_ms

    users[user_index] = user
    save_db(db)

    return jsonify({'user': safe_user(user)})


@app.route('/api/chats', methods=['GET'])
def get_chats():
    user_id = (request.args.get('user_id') or '').strip()
    if not user_id:
        return jsonify({'chats': []})

    db = load_db()
    users_by_id = {u['id']: u for u in db['users']}
    partner_ids = set()

    for m in db['messages']:
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
            if (m.get('sender_id') == user_id and m.get('receiver_id') == pid)
            or (m.get('sender_id') == pid and m.get('receiver_id') == user_id)
        ]
        dialog.sort(key=lambda x: x.get('timestamp', 0))
        last_msg = dialog[-1] if dialog else None

        chats.append({
            'id': partner['id'],
            'nickname': partner['nickname'],
            'avatar': partner.get('avatar', '🕊️'),
            'verified': has_blue_checkmark(partner['nickname']),
            'lastMessage': last_msg.get('text', '') if last_msg else '',
            'lastTimestamp': last_msg.get('timestamp', 0) if last_msg else 0
        })

    chats.sort(key=lambda c: c['lastTimestamp'], reverse=True)
    return jsonify({'chats': chats})


@app.route('/api/messages', methods=['GET'])
def get_messages():
    user_id = (request.args.get('user_id') or '').strip()
    peer_id = (request.args.get('peer_id') or '').strip()

    if not user_id or not peer_id:
        return jsonify({'messages': []})

    db = load_db()
    dialog = [
        m for m in db['messages']
        if (m.get('sender_id') == user_id and m.get('receiver_id') == peer_id)
        or (m.get('sender_id') == peer_id and m.get('receiver_id') == user_id)
    ]
    dialog.sort(key=lambda x: x.get('timestamp', 0))
    return jsonify({'messages': dialog})


@app.route('/api/messages/send', methods=['POST'])
def send_message():
    data = request.get_json() or {}
    sender_id = (data.get('sender_id') or '').strip()
    receiver_id = (data.get('receiver_id') or '').strip()
    text = (data.get('text') or '').strip()

    if not sender_id or not receiver_id or not text:
        return jsonify({'error': 'Пустое сообщение'}), 400

    if len(text) > 1000:
        return jsonify({'error': 'Сообщение слишком длинное'}), 400

    db = load_db()
    users_by_id = {u['id']: u for u in db['users']}
    if sender_id not in users_by_id or receiver_id not in users_by_id:
        return jsonify({'error': 'Пользователь не найден'}), 404

    now_ms = int(time.time() * 1000)
    msg = {
        'id': f'{now_ms}_{len(db["messages"]) + 1}',
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'text': text,
        'timestamp': now_ms
    }

    db['messages'].append(msg)
    save_db(db)

    return jsonify({'message': msg})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
