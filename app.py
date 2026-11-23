import os
import json
import time
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
DB_FILE = 'users.json'

# 17 аватарок: разные объекты/символы + обязательно 🦜, 🐗, 🎩
ALLOWED_AVATARS = [
    '🕊️', '🦜', '🐗', '🎩', '🚀', '🤖',
    '😎', '👻', '🔥', '⭐', '🎮', '💎',
    '🍕', '⚡', '👑', '🎨', '🧩'
]

WEEK_MS = 7 * 24 * 60 * 60 * 1000


def load_users():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
        return []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_users(users):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


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

    users = load_users()
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
    save_users(users)

    return jsonify({'user': safe_user(new_user), 'avatars': ALLOWED_AVATARS})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    nickname = (data.get('nickname') or '').strip()
    password = data.get('password') or ''

    if not nickname or not password:
        return jsonify({'error': 'Введи никнейм и пароль!'}), 400

    users = load_users()
    user = next(
        (u for u in users if u['nickname'].lower() == nickname.lower() and u['password'] == password),
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

    users = load_users()
    user = next((u for u in users if u['id'] == user_id), None)

    if not user:
        return jsonify({'error': 'Аккаунт не найден'}), 404

    user['verified'] = has_blue_checkmark(user['nickname'])
    return jsonify({'user': safe_user(user), 'avatars': ALLOWED_AVATARS})


@app.route('/api/users/search', methods=['GET'])
def search_users():
    q = (request.args.get('q') or '').strip().lower()
    if not q:
        return jsonify({'users': []})

    users = load_users()
    matched = [
        {
            'id': u['id'],
            'nickname': u['nickname'],
            'avatar': u.get('avatar', '🕊️'),
            'verified': has_blue_checkmark(u['nickname'])
        }
        for u in users
        if u['nickname'].lower().startswith(q)
    ]

    return jsonify({'users': matched})


@app.route('/api/update-profile', methods=['POST'])
def update_profile():
    data = request.get_json() or {}
    user_id = data.get('id')
    new_nickname = (data.get('newNickname') or '').strip()
    new_avatar = data.get('newAvatar')

    users = load_users()
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
    save_users(users)

    return jsonify({'user': safe_user(user)})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
