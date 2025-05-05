# apptest1.py
import os
import sqlite3
from flask import Flask, request, abort, jsonify, g

# ===== SQLite 資料庫設定 =====
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'move.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(
            DATABASE,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        db.row_factory = sqlite3.Row
    return db

def close_db(e=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """依 schema.sql 建表（第一次啟動或 schema 更新時呼叫）"""
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    with open(SCHEMA_PATH, encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

# ===== Flask App & 自動建表 =====
app = Flask(__name__)
with app.app_context():
    init_db()
app.teardown_appcontext(close_db)

# ===== LINE Bot v3 SDK 正確 Import =====
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
    'LINE_CHANNEL_ACCESS_TOKEN',
    '你的 Channel Access Token'
)
LINE_CHANNEL_SECRET = os.getenv(
    'LINE_CHANNEL_SECRET',
    '你的 Channel Secret'
)

# 建立 v3 client 與 handler
config        = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
api_client    = ApiClient(config)
messaging_api = MessagingApi(api_client)
handler       = WebhookHandler(channel_secret=LINE_CHANNEL_SECRET)

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400, 'Invalid signature')
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id   = event.source.user_id
    user_text = event.message.text
    bot_reply = f"你說：「{user_text}」"

    # 寫入 chat_log
    db = get_db()
    db.execute(
        "INSERT INTO chat_log (user_id, user_text, bot_reply) VALUES (?, ?, ?)",
        (user_id, user_text, bot_reply)
    )
    db.commit()

    # v3 回覆
    messaging_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[ TextMessage(text=bot_reply) ]
        )
    )

# ===== Flask API：列表 & 取資料 =====
@app.route('/tables', methods=['GET'])
def list_tables():
    db = get_db()
    cursor = db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    )
    tables = [r['name'] for r in cursor.fetchall()]
    return jsonify(tables)

@app.route('/data/<table_name>', methods=['GET'])
def get_table_data(table_name):
    if not table_name.isidentifier():
        abort(400, 'Invalid table name')
    db = get_db()
    try:
        cursor = db.execute(f"SELECT * FROM {table_name} LIMIT 100")
    except sqlite3.OperationalError:
        abort(404, f"Table `{table_name}` not found")
    data = [dict(r) for r in cursor.fetchall()]
    return jsonify(data)

# ===== 啟動 =====
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
