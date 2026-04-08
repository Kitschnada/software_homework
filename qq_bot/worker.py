#!/usr/bin/env python3
"""
QQ 机器人本地工作脚本（qq_worker.py）

运行在你的本地机器上（WSL/Windows），功能：
1. 每隔几秒轮询远程服务器的通知 API (后台线程)
2. 收到待发通知后，通过本地 NapCat 发送到 QQ 群
3. 每 7 天自动续期 PythonAnywhere 免费账号 (后台线程)
4. [新增] 运行 Flask Webhook 服务器，接收 NapCat 事件，实现机器人互动
"""

import sys
import time
import datetime
import requests
import threading
import json
import random
import os
from flask import Flask, request, jsonify, render_template, redirect

app = Flask(__name__, template_folder='.')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SETTINGS_FILE = os.path.join(SCRIPT_DIR, 'local_bot_settings.json')

def load_local_settings():
    default_settings = {
        "server_url": "http://127.0.0.1:5000",
        "qq_bot_token": "IThK.RzDME3JBfme",
        "napcat_api": "http://127.0.0.1:3000",
        "napcat_token": "",
        "bot_qq": "",
        "work_group_id": "",
        "enable_llm": True,
        "openrouter_api_key": "",
        "default_llm_model": "deepseek",
        "system_prompt": "你是一个群聊智能助手。请简洁回答问题。",
        "pa_username": "",
        "pa_password": "",
        "pa_domain": "",
        "webhook_port": 6060,
        "poll_interval": 5
    }
    if os.path.exists(LOCAL_SETTINGS_FILE):
        try:
            with open(LOCAL_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                default_settings.update(data)
        except Exception as e:
            print(f"❌ 读取本地配置失败: {e}")
    return default_settings

app = Flask(__name__, template_folder=SCRIPT_DIR)

DYNAMIC_SETTINGS = load_local_settings()
current_model = DYNAMIC_SETTINGS.get('default_llm_model', 'deepseek')

SERVER_URL = DYNAMIC_SETTINGS['server_url']
BOT_TOKEN = DYNAMIC_SETTINGS['qq_bot_token']
NAPCAT_API = DYNAMIC_SETTINGS['napcat_api']
NAPCAT_TOKEN = DYNAMIC_SETTINGS['napcat_token']
WEBHOOK_PORT = int(DYNAMIC_SETTINGS.get('webhook_port', 6000))
POLL_INTERVAL = int(DYNAMIC_SETTINGS.get('poll_interval', 5))
# ============================================================

user_chat_history  = {} # {qq: [{'role':'user', 'content':...}]}

# PythonAnywhere 自动续期配置
PA_USERNAME = DYNAMIC_SETTINGS.get('pa_username', '')
PA_PASSWORD = DYNAMIC_SETTINGS.get('pa_password', '')
PA_DOMAIN   = DYNAMIC_SETTINGS.get('pa_domain', '')


# ============================================================
#  API 辅助函数 
# ============================================================
def server_api_call(endpoint, method='GET', payload=None):
    url = f"{SERVER_URL.rstrip('/')}{endpoint}"
    headers = {'Authorization': f'Bearer {BOT_TOKEN}', 'Content-Type': 'application/json'}
    try:
        if method == 'GET':
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # 兼容空响应
        if not resp.text.strip():
            return {}
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": f"连接服务器失败: {e}"}

def send_private_msg(qq, message):
    url = f"{NAPCAT_API.rstrip('/')}/send_private_msg"
    payload = {"user_id": int(qq), "message": message}
    headers = {}
    if NAPCAT_TOKEN: headers['Authorization'] = f'Bearer {NAPCAT_TOKEN}'
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        if resp.status_code != 200:
            print(f"[Worker] ⚠️ 发送私聊消息给 {qq} 失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"[Worker] ❌ 发送私聊消息给 {qq} 异常: {e}")

# ============================================================
#  轮询推送功能 (背景线程)
# ============================================================
def pull_notifications():
    """从服务器拉取待发送通知"""
    url = f"{SERVER_URL.rstrip('/')}/api/notifications"
    headers = {'Authorization': f'Bearer {BOT_TOKEN}'}
    try:
        resp = requests.get(url, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        if resp.status_code == 401:
            print("[Worker] ❌ Token 鉴权失败，请检查 config.py 中的 QQ_BOT_TOKEN")
            return []
        resp.raise_for_status()
        return resp.json().get('notifications', [])
    except Exception as e:
        return []

def send_to_qq_group(message):
    """通过本地 NapCat 发送消息到 QQ 群"""
    work_group_id = DYNAMIC_SETTINGS.get('work_group_id')
    if not work_group_id:
        print("[Worker] ⚠️ 未配置工作群号(work_group_id)，无法发送通知")
        return False
        
    url = f"{NAPCAT_API.rstrip('/')}/send_group_msg"
    payload = {
        "group_id": int(work_group_id),
        "message": message
    }
    headers = {}
    if NAPCAT_TOKEN:
        headers['Authorization'] = f'Bearer {NAPCAT_TOKEN}'
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        result = resp.json()
        if result.get('status') == 'ok':
            return result.get('data', {}).get('message_id', True)
        else:
            print(f"[Worker] ⚠️ NapCat 返回: {result}")
            return False
    except Exception as e:
        print(f"[Worker] ❌ 发送到 QQ 群失败: {e}")
        return False

def mark_sent(items):
    """通知服务器：这些消息已发送成功"""
    url = f"{SERVER_URL.rstrip('/')}/api/notifications/mark_sent"
    headers = {'Authorization': f'Bearer {BOT_TOKEN}', 'Content-Type': 'application/json'}
    try:
        requests.post(url, json={'items': items}, headers=headers, timeout=10)
    except Exception as e:
        pass

_last_renew_time = None
def auto_renew_pythonanywhere():
    global _last_renew_time
    now = datetime.datetime.now()
    if _last_renew_time and (now - _last_renew_time).days < 7:
        return
    if not PA_USERNAME or not PA_PASSWORD:
        return
    
    import re
    print("[Renew] 🔄 正在自动续期 PythonAnywhere...")
    session = requests.Session()
    BASE = 'https://www.pythonanywhere.com'
    try:
        login_page = session.get(f'{BASE}/login/', timeout=15)
        csrf = session.cookies.get('csrftoken', '')
        if not csrf:
            m = re.search(r'csrfmiddlewaretoken.*?value="(.+?)"', login_page.text)
            csrf = m.group(1) if m else ''
        if not csrf:
            _last_renew_time = now
            return
            
        login_resp = session.post(
            f'{BASE}/login/',
            data={'auth-username': PA_USERNAME, 'auth-password': PA_PASSWORD, 'csrfmiddlewaretoken': csrf, 'login_view-current_step': 'auth'},
            headers={'Referer': f'{BASE}/login/'},
            timeout=15, allow_redirects=True
        )
        if PA_USERNAME.lower() not in login_resp.url.lower() and 'Log out' not in login_resp.text:
            _last_renew_time = now
            return
            
        webapp_url = f'{BASE}/user/{PA_USERNAME}/webapps/{PA_USERNAME}.pythonanywhere.com/'
        webapp_page = session.get(webapp_url, timeout=15)
        csrf2 = session.cookies.get('csrftoken', csrf)
        m2 = re.search(r'action="[^"]*extend[^"]*".*?csrfmiddlewaretoken.*?value="(.+?)"', webapp_page.text, re.DOTALL)
        if m2: csrf2 = m2.group(1)
        
        extend_url = f'{BASE}/user/{PA_USERNAME}/webapps/{PA_USERNAME}.pythonanywhere.com/extend'
        extend_resp = session.post(extend_url, data={'csrfmiddlewaretoken': csrf2}, headers={'Referer': webapp_url}, timeout=15, allow_redirects=True)
        if extend_resp.status_code in (200, 302):
            next_time = now + datetime.timedelta(days=7)
            print(f"[Renew] ✅ 续期成功！下次: {next_time.strftime('%Y-%m-%d %H:%M')}")
        _last_renew_time = now
    except Exception as e:
        _last_renew_time = now


def fetch_dynamic_settings():
    """从本地文件重载配置"""
    global current_model, SERVER_URL, BOT_TOKEN, NAPCAT_API, NAPCAT_TOKEN
    global PA_USERNAME, PA_PASSWORD, PA_DOMAIN, WEBHOOK_PORT, POLL_INTERVAL
    
    DYNAMIC_SETTINGS.update(load_local_settings())
    current_model = DYNAMIC_SETTINGS.get('default_llm_model', 'deepseek')
    SERVER_URL = DYNAMIC_SETTINGS.get('server_url', '')
    BOT_TOKEN = DYNAMIC_SETTINGS.get('qq_bot_token', '')
    NAPCAT_API = DYNAMIC_SETTINGS.get('napcat_api', '')
    NAPCAT_TOKEN = DYNAMIC_SETTINGS.get('napcat_token', '')
    
    PA_USERNAME = DYNAMIC_SETTINGS.get('pa_username', '')
    PA_PASSWORD = DYNAMIC_SETTINGS.get('pa_password', '')
    PA_DOMAIN   = DYNAMIC_SETTINGS.get('pa_domain', '')
    WEBHOOK_PORT  = int(DYNAMIC_SETTINGS.get('webhook_port', 6000))
    POLL_INTERVAL = int(DYNAMIC_SETTINGS.get('poll_interval', 5))

def background_tasks():
    print("\n🟢 背景推送与续期线程已启动\n")
    loop_count = 0
    fetch_dynamic_settings() # 启动时先拉一次
    
    while True:
        try:
            notifications = pull_notifications()
            if notifications:
                print(f"📬 收到 {len(notifications)} 条待发通知")
                sent_items = []
                for n in notifications:
                    print(f"  → 发送通知 #{n['id']}...")
                    msg_id = send_to_qq_group(n['message'])
                    if msg_id:
                        sent_items.append({'id': n['id'], 'message_id': str(msg_id) if msg_id is not True else None})
                if sent_items:
                    mark_sent(sent_items)
                    
            loop_count += 1
            if loop_count % 360 == 1:
                auto_renew_pythonanywhere()
            # 每隔大概1分钟更新一次配置
            if loop_count % (60 // POLL_INTERVAL) == 0:
                fetch_dynamic_settings()
        except Exception as e:
            print(f"[Background] 异常: {e}")
        time.sleep(POLL_INTERVAL)

def daily_reminder_task():
    print("🟢 每日汇总提醒线程已启动")
    while True:
        now = datetime.datetime.now()
        # 每天早上 9 点播报
        if now.hour == 9 and now.minute == 0:
            try:
                res = server_api_call("/api/bot/pending_summary")
                if res.get('status') == 'ok':
                    d = res['data']
                    if d['total'] > 0:
                        msg = f"🌅 早上好！今日系统共有 {d['total']} 个工单待处理：\n"
                        for c in d['categories']:
                            if c['count'] > 0:
                                msg += f"- {c['name']}: {c['count']} 个\n"
                        msg += "请融媒体中心的同学们及时接单处理哦~"
                        send_to_qq_group(msg)
            except Exception as e:
                print(f"[Daily Reminder] 异常: {e}")
            time.sleep(60) # 休眠一分钟防止重复发送
        else:
            time.sleep(30)

# ============================================================
#  Webhook 处理与机器人指令
# ============================================================

# AVAILABLE_MODELS 作为硬编码保留，也可移动到服务端，不过目前先放内部
AVAILABLE_MODELS = {
    'deepseek': 'deepseek/deepseek-r1-0528:free',
    'qwen': 'qwen/qwen3-next-80b-a3b-instruct:free',
    'qwencoder': 'qwen/qwen-2.5-coder-32b-instruct:free',
    'llama': 'meta-llama/llama-3.3-70b-instruct:free',
    'gemma': 'google/gemma-3-27b-it:free',
    'trinity':'arcee-ai/trinity-large-preview:free',
    'glm':'z-ai/glm-4.5-air:free',
    'step':'stepfun/step-3.5-flash:free',
    'gpt':'openai/gpt-oss-120b:free',
    'auto':'openrouter/free',
}

def call_openrouter(prompt, qq):
    global current_model
    ak = DYNAMIC_SETTINGS.get('openrouter_api_key')
    if not ak:
        return "管理员尚未配置 OpenRouter API Key。"
    if qq not in user_chat_history: user_chat_history[qq] = []
    
    history = user_chat_history[qq]
    history.append({"role": "user", "content": prompt})
    if len(history) > 10: history = history[-10:] # 最多保留10条上下文
        
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {ak}", "Content-Type": "application/json"}
    model_id = AVAILABLE_MODELS.get(current_model, "deepseek/deepseek-chat:free")
    
    # 构造将要发送的 messages（始终确保包含系统提示词）
    sys_prompt = DYNAMIC_SETTINGS.get('system_prompt', '你是一个群聊智能助手。')
    messages = [{"role": "system", "content": sys_prompt}] + history
    
    data = {"model": model_id, "messages": messages}
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        result = resp.json()
        reply = result['choices'][0]['message']['content']
        history.append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        history.pop()
        return f"请求大模型失败: {e}"

def handle_command(qq, text):
    global current_model
    text = text.strip()
    
    if text == "/帮助":
        help_msg = "🤖 融媒体中心机器人指令：\n【交流与查询】\n"
        if DYNAMIC_SETTINGS.get('enable_llm', True):
            help_msg += ("  @机器人 /ai [内容] - AI对话\n"
                         "  /模型列表 - 查看所有可用模型\n"
                         "  /切换模型 [名称] - 切换AI模型\n")
        help_msg += ("  /查单 [单号] - 查询工单进度\n"
                     "  /我的工单 - 查询我相关的工单\n"
                     "【系统功能】\n"
                     "  /接单 #[单号] - 快捷接单\n"
                     "  /订阅 [分类] - 有新系统单时私聊\n"
                     "  /取消订阅 [分类]\n"
                     "  /统计 - 查看系统工单数据统计\n"
                     "  /绑定 [账号] [密码] - 绑定系统\n"
                     "【趣味工具】\n"
                     "  /天气 [城市] - 查天气\n"
                     "  /一言 - 随机名言句子\n"
                     "  /今日运势 - 每日抽签"
                     "本系统连接AstrBot相关服务，已经接入Gemini 3.0 Flash模型，可以在私聊或非工作群聊中进行AI对话。")
        return help_msg
        
    elif text == "/模型列表":
        res = "可用免费模型:\n"
        for k, v in AVAILABLE_MODELS.items():
            res += f"- {k}\n"
        res += f"\n当前模型: {current_model}"
        return res
        
    elif text.startswith("/切换模型"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2: return "格式错误，请使用 /切换模型 [名称]"
        name = parts[1].strip()
        if name in AVAILABLE_MODELS:
            current_model = name
            return f"✅ 已成功切换至 {name} 模型！"
        else:
            return "❌ 找不到该模型，请通过 /模型列表 查询"
            
    elif text.startswith("/查单"):
        parts = text.split()
        if len(parts) < 2: return "格式错误，请使用 /查单 [单号]"
        tid = parts[1].replace('#', '')
        if not tid.isdigit(): return "单号必须是数字"
        
        res = server_api_call(f"/api/bot/ticket/{tid}")
        if res.get('status') == 'ok':
            d = res['data']
            return f"📄 工单 #{d['id']}\n分类: {d['category_name']}\n发起人: {d['applicant_name']}\n状态: {d['status']}\n进度: {d['current_acceptors']}/{d['max_acceptors']} 人接单\n截止: {d['deadline']}\n需求: {d['requirements']}"
        else:
            return f"❌ {res.get('message', '查询失败')}"
            
    elif text == "/我的工单":
        res = server_api_call(f"/api/bot/tickets/user/{qq}")
        if res.get('status') == 'ok':
            out = f"👤 {res['real_name']} 最近{res['role_type']}的工单：\n"
            for o in res['orders']:
                out += f"#{o['id']} [{o['category_name']}] - 状态: {o['status']}\n"
            if not res['orders']: out += "暂无近期工单"
            return out
        else:
            return f"❌ {res.get('message', '查询失败 (可能未绑定QQ)')}"
            
    elif text == "/统计":
        res = server_api_call("/api/bot/stats")
        if res.get('status') == 'ok':
            d = res['data']
            return f"📊 系统工单统计:\n今日新增: {d['today']} 单\n本月累计: {d['month']} 单\n当前待处理: {d['pending']} 单"
        return "❌ 统计数据获取失败"
            
    elif text.startswith("/接单"):
        parts = text.split()
        if len(parts) < 2: return "格式: /接单 #[单号]"
        tid = parts[1].replace('#', '')
        res = server_api_call("/api/bot/accept_ticket", 'POST', {"qq_number": qq, "ticket_id": tid})
        return f"{'✅' if res.get('status')=='ok' else '❌'} {res.get('message')}"
            
    elif text.startswith("/绑定"):
        parts = text.split()
        if len(parts) != 3: return "格式错误，请使用 /绑定 [账号] [密码]"
        res = server_api_call("/api/bot/bind_qq", 'POST', {"uid": parts[1], "password": parts[2], "qq_number": str(qq)})
        return f"{'✅' if res.get('status')=='ok' else '❌'} {res.get('message')}"
            
    elif text.startswith("/订阅 ") or text == "/订阅":
        parts = text.split(maxsplit=1)
        if len(parts) < 2: return "格式: /订阅 [分类]"
        res = server_api_call("/api/bot/subscribe", 'POST', {"qq_number": qq, "category_name": parts[1]})
        return res.get('message', '请求失败')
        
    elif text.startswith("/取消订阅 ") or text == "/取消订阅":
        parts = text.split(maxsplit=1)
        if len(parts) < 2: return "格式: /取消订阅 [分类]"
        res = server_api_call("/api/bot/unsubscribe", 'POST', {"qq_number": qq, "category_name": parts[1]})
        return res.get('message', '请求失败')
        
    elif text.startswith("/天气"):
        parts = text.split(maxsplit=1)
        city = parts[1] if len(parts) > 1 else "南京"
        try:
            r = requests.get(f"https://api.paugram.com/weather/?city={city}", timeout=5)
            data = r.json()
            if "forecast_24h" in data and len(data["forecast_24h"]) > 0:
                today = data["forecast_24h"][0]
                day_weather = today.get("day_weather", "未知")
                min_degree = today.get("min_degree", "?")
                max_degree = today.get("max_degree", "?")
                wind_dir = today.get("day_wind_direction", "未知")
                wind_power = today.get("day_wind_power", "未知")
                aqi = today.get("aqi_name", "未知")
                ans = f"{city}今日天气：{day_weather}\n🌡️ 气温：{min_degree}~{max_degree}℃\n🍃 风向：{wind_dir} {wind_power}\n🌿 空气质量：{aqi}"
            else:
                ans = "查询失败，未找到对应城市天气"
            return f"☁️ 天气查询结果：\n{ans}"
        except Exception as e:
            return f"❌ 天气服务不可用: {e}"
            
    elif text == "/一言":
        try:
            r = requests.get("https://v1.hitokoto.cn/?c=i", timeout=5)
            d = r.json()
            return f"「{d['hitokoto']}」 —— {d['from']}"
        except: return "❌ 一言服务不可用"
            
    elif text == "/今日运势":
        fortunes = ["大吉 🌟", "中吉 ☀️", "小吉 ⛅", "平 ☁️", "末吉 🌧️"]
        seed = int(time.time() // 86400) + int(qq)
        random.seed(seed)
        return f"🔮 你的今日运势是：{random.choice(fortunes)}"
        
    elif text.startswith("/ai ") or text == "/ai":
        prompt = text[len("/ai"):].strip()
        if not prompt: return "你想聊点什么？"
        return call_openrouter(prompt, qq)
        
    return None


@app.route('/')
def index():
    return redirect('/admin')

@app.route('/admin', methods=['GET', 'POST'])
def admin_page():
    msg = ""
    if request.method == 'POST':
        new_settings = {
            "server_url": request.form.get("server_url", ""),
            "qq_bot_token": request.form.get("qq_bot_token", ""),
            "napcat_api": request.form.get("napcat_api", ""),
            "napcat_token": request.form.get("napcat_token", ""),
            "bot_qq": request.form.get("bot_qq", ""),
            "work_group_id": request.form.get("work_group_id", ""),
            "enable_llm": "enable_llm" in request.form,
            "openrouter_api_key": request.form.get("openrouter_api_key", ""),
            "default_llm_model": request.form.get("default_llm_model", "deepseek"),
            "system_prompt": request.form.get("system_prompt", "你是一个群聊智能助手。"),
            "pa_username": request.form.get("pa_username", ""),
            "pa_password": request.form.get("pa_password", ""),
            "pa_domain": request.form.get("pa_domain", ""),
            "webhook_port": int(request.form.get("webhook_port", 6000)),
            "poll_interval": int(request.form.get("poll_interval", 5))
        }
        with open(LOCAL_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_settings, f, ensure_ascii=False, indent=2)
        fetch_dynamic_settings()
        msg = "✅ 配置已成功保存并重新加载！"
    
    return render_template('admin.html', settings=DYNAMIC_SETTINGS, available_models=AVAILABLE_MODELS, msg=msg)


@app.route('/napcat', methods=['POST'])
def napcat_webhook():
    data = request.json
    if not data: return jsonify({})
        
    post_type = data.get('post_type')
    if post_type != 'message':
        return jsonify({})
        
    msg_type = data.get('message_type')
    group_id = str(data.get('group_id', ''))
    work_group_id = DYNAMIC_SETTINGS.get('work_group_id', '')
    
    qq = str(data.get('sender', {}).get('user_id', ''))
    raw_message = data.get('raw_message', '')
    
    is_at_me = False
    reply_msg_id = None
    message_list = data.get('message', [])
    clean_text = raw_message
    
    bot_qq = DYNAMIC_SETTINGS.get('bot_qq', '')
    
    if isinstance(message_list, list):
        for m in message_list:
            if m.get('type') == 'reply':
                reply_msg_id = m.get('data', {}).get('id')
            if m.get('type') == 'at' and str(m.get('data', {}).get('qq')) == bot_qq:
                is_at_me = True
        texts = [m['data']['text'] for m in message_list if m.get('type') == 'text']
        clean_text = "".join(texts).strip()

    # == 工作群：仅允许工单通知与抢单 ==
    if msg_type == 'group' and group_id == work_group_id:
        if reply_msg_id and clean_text == '抢单':
            res = server_api_call("/api/bot/grab_order_by_reply", 'POST', {"qq_number": qq, "message_id": str(reply_msg_id)})
            send_to_qq_group([
                {"type": "at", "data": {"qq": qq}},
                {"type": "text", "data": {"text": "\n" + res.get('message', '抢单请求失败')}}
            ])
        return jsonify({})
        
    # == 其他群和私聊：开放所有功能 ==
    reply_msg = None
    if clean_text.startswith('/'):
        reply_msg = handle_command(qq, clean_text)
    elif is_at_me or msg_type == 'private':
        if DYNAMIC_SETTINGS.get('enable_llm', True):
            prompt = clean_text.strip()
            reply_msg = call_openrouter(prompt, qq)
        
    if reply_msg:
        if msg_type == 'group':
            url = f"{NAPCAT_API.rstrip('/')}/send_group_msg"
            payload = {"group_id": int(group_id), "message": [{"type": "at", "data": {"qq": qq}}, {"type": "text", "data": {"text": "\n" + reply_msg}}]}
            headers = {'Authorization': f'Bearer {NAPCAT_TOKEN}'} if NAPCAT_TOKEN else {}
            try: requests.post(url, json=payload, headers=headers, timeout=10)
            except: pass
        else:
            send_private_msg(qq, reply_msg)
            
    return jsonify({})

def run():
    fetch_dynamic_settings()
    print("=" * 50)
    print("🤖 QQ 工单通知机器人 (包含 Webhook)")
    print("=" * 50)
    print(f"  服务器:  {SERVER_URL}")
    print(f"  NapCat:  {NAPCAT_API} (目标群号: {DYNAMIC_SETTINGS.get('work_group_id')})")
    print(f"  Webhook: 监听在端口 {WEBHOOK_PORT}")
    print(f"  大模型:  {current_model} (可选 {len(AVAILABLE_MODELS)} 个)")
    print("=" * 50)

    if not BOT_TOKEN:
        print("❌ qq_config.py 中未设置 QQ_BOT_TOKEN")
        sys.exit(1)
        
    # 启动后台线程
    import threading
    threading.Thread(target=background_tasks, daemon=True).start()
    threading.Thread(target=daily_reminder_task, daemon=True).start()
    
    # 启动 Flask 监听 Webhook
    app.run(host='0.0.0.0', port=WEBHOOK_PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    run()
