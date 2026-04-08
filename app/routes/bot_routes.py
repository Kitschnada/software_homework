from flask import Blueprint, request, jsonify, current_app
from app.db import get_db
from werkzeug.security import check_password_hash
import datetime
import os
import json

bot_bp = Blueprint('bot', __name__, url_prefix='/api/bot')

def verify_token():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return False
    # Expect "Bearer <token>"
    parts = auth_header.split()
    if len(parts) != 2 or parts[0] != 'Bearer':
        return False
    
    expected = current_app.config.get('QQ_BOT_TOKEN')
    settings_file = current_app.config.get('BOT_SETTINGS_FILE')
    if settings_file and os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                expected = json.load(f).get('qq_bot_token', expected)
        except: pass
        
    return parts[1] == expected


@bot_bp.before_request
def require_bot_token():
    if not verify_token():
        return jsonify({"status": "error", "message": "Unauthorized API access"}), 401



@bot_bp.route('/bind_qq', methods=['POST'])
def bind_qq():
    """验证系统账号和密码，并绑定给定的 QQ 号"""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload"}), 400
    
    uid = data.get('uid')
    password = data.get('password')
    qq_number = data.get('qq_number')
    
    if not uid or not password or not qq_number:
        return jsonify({"status": "error", "message": "缺少必要的字段(uid, password, qq_number)"}), 400
    
    db = get_db()
    # 查找用户
    user = db.execute('SELECT * FROM users WHERE uid = ? OR phone = ? OR card_id = ?', (uid, uid, uid)).fetchone()
    
    if not user:
        return jsonify({"status": "error", "message": "找不到该用户账号"}), 404
        
    if not check_password_hash(user['password'], password):
        return jsonify({"status": "error", "message": "账号或密码错误"}), 403
        
    try:
        db.execute('UPDATE users SET qq_number = ? WHERE id = ?', (qq_number, user['id']))
        db.commit()
        return jsonify({"status": "ok", "message": f"成功绑定 QQ 号至系统账号: {user['real_name']}"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"绑定失败，可能该 QQ 已被其他账号绑定: {str(e)}"}), 500


@bot_bp.route('/ticket/<int:ticket_id>', methods=['GET'])
def get_ticket(ticket_id):
    """通过工单号查询工单"""
    db = get_db()
    order = db.execute('''
        SELECT w.id, w.status, w.created_at, w.deadline, w.requirements,
               u.real_name as applicant_name, c.name as category_name,
               (SELECT COUNT(*) FROM assignments a WHERE a.work_order_id = w.id) as current_acceptors,
               w.max_acceptors
        FROM work_orders w
        JOIN users u ON w.applicant_id = u.id
        JOIN categories c ON w.category_id = c.id
        WHERE w.id = ?
    ''', (ticket_id,)).fetchone()
    
    if not order:
        return jsonify({"status": "error", "message": "未找到指定工单号"}), 404
        
    return jsonify({
        "status": "ok",
        "data": dict(order)
    }), 200


@bot_bp.route('/tickets/user/<qq>', methods=['GET'])
def get_user_tickets(qq):
    """查询QQ对应的普通用户的最近工单（发起），或成员用户的最近工单（受理）"""
    db = get_db()
    # 先找有没有绑定该QQ的用户
    user = db.execute('SELECT id, role, real_name FROM users WHERE qq_number = ?', (qq,)).fetchone()
    if not user:
        return jsonify({"status": "error", "message": "该 QQ 未绑定系统账号"}), 404
        
    user_id = user['id']
    role = user['role']
    
    # 找工单
    if role in ('applicant', 'admin', 'dept_admin'):
        # 查询作为发起人的工单
        orders = db.execute('''
            SELECT w.id, w.status, w.created_at, c.name as category_name
            FROM work_orders w
            JOIN categories c ON w.category_id = c.id
            WHERE w.applicant_id = ?
            ORDER BY w.created_at DESC LIMIT 5
        ''', (user_id,)).fetchall()
        role_type = "发起"
    else:
        # role == 'acceptor' 查询作为受理人的工单
        orders = db.execute('''
            SELECT w.id, w.status, w.created_at, c.name as category_name
            FROM work_orders w
            JOIN categories c ON w.category_id = c.id
            JOIN assignments a ON a.work_order_id = w.id
            WHERE a.acceptor_id = ?
            ORDER BY w.created_at DESC LIMIT 5
        ''', (user_id,)).fetchall()
        role_type = "受理"
        
    return jsonify({
        "status": "ok",
        "role_type": role_type,
        "real_name": user['real_name'],
        "orders": [dict(o) for o in orders]
    }), 200


@bot_bp.route('/stats', methods=['GET'])
def get_stats():
    """获取工单统计信息"""
    db = get_db()
    today_start = datetime.datetime.now().strftime('%Y-%m-%d 00:00:00')
    month_start = datetime.datetime.now().strftime('%Y-%m-01 00:00:00')
    
    # 今日工单
    today_count = db.execute('SELECT COUNT(*) FROM work_orders WHERE created_at >= ?', (today_start,)).fetchone()[0]
    # 本月工单
    month_count = db.execute('SELECT COUNT(*) FROM work_orders WHERE created_at >= ?', (month_start,)).fetchone()[0]
    # 当前待处理 (pending)
    pending_count = db.execute('SELECT COUNT(*) FROM work_orders WHERE status = "pending"').fetchone()[0]
    
    return jsonify({
        "status": "ok",
        "data": {
            "today": today_count,
            "month": month_count,
            "pending": pending_count
        }
    }), 200


@bot_bp.route('/pending_summary', methods=['GET'])
def get_pending_summary():
    """获取待处理单摘要，用于定时播报"""
    db = get_db()
    # 统计各大类的待处理工单数
    summary = db.execute('''
        SELECT c.name, COUNT(w.id) as count
        FROM work_orders w
        JOIN categories c ON w.category_id = c.id
        WHERE w.status = "pending"
        GROUP BY c.id
    ''').fetchall()
    
    total = sum(s['count'] for s in summary)
    
    return jsonify({
        "status": "ok",
        "data": {
            "total": total,
            "categories": [{"name": s['name'], "count": s['count']} for s in summary]
        }
    }), 200


@bot_bp.route('/accept_ticket', methods=['POST'])
def accept_ticket():
    """成员通过QQ号快捷接单"""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload"}), 400
        
    qq_number = data.get('qq_number')
    ticket_id = data.get('ticket_id')
    
    if not qq_number or not ticket_id:
        return jsonify({"status": "error", "message": "Missing qq_number or ticket_id"}), 400
        
    db = get_db()
    res = _common_accept_logic(db, qq_number, ticket_id)
    
    status_code = 200 if res['status'] == 'ok' else 400
    if '异常' in res['message']: status_code = 500
        
    return jsonify(res), status_code


def _common_accept_logic(db, qq_number, ticket_id):
    """提取的通用接单逻辑，供 accept_ticket 和 grab_order_by_reply 重复使用"""
    user = db.execute('SELECT * FROM users WHERE qq_number = ?', (qq_number,)).fetchone()
    if not user:
        return {"status": "error", "message": "该 QQ 未绑定系统账号，请使用/绑定命令绑定账号"}
        
    if user['role'] != 'acceptor':
        return {"status": "error", "message": "仅融媒体中心成员(受理人)可以在群内接单"}
        
    # 检查工单是否存在及状态
    order = db.execute('SELECT * FROM work_orders WHERE id = ?', (ticket_id,)).fetchone()
    if not order:
        return {"status": "error", "message": "该工单不存在"}
        
    user_id = user['id']
    
    # 检查接单人数是否已满
    current_acceptors = db.execute('SELECT COUNT(*) FROM assignments WHERE work_order_id = ?', (ticket_id,)).fetchone()[0]
    
    # 检查此人是否已接单
    existing_assignment = db.execute('SELECT id FROM assignments WHERE work_order_id = ? AND acceptor_id = ?', (ticket_id, user_id)).fetchone()
    if existing_assignment:
        return {"status": "error", "message": "您已经接了这单了，请勿重复接单"}
        
    if order['status'] not in ('pending', 'accepted'):
        return {"status": "error", "message": f"该工单状态为 {order['status']}，无法接单"}
        
    if current_acceptors >= order['max_acceptors']:
        return {"status": "error", "message": "抱歉，该工单受理人数已满"}
        
    try:
        # 新增接单记录
        db.execute('INSERT INTO assignments (work_order_id, acceptor_id) VALUES (?, ?)', (ticket_id, user_id))
        # 更新工单状态为 accepted
        db.execute('UPDATE work_orders SET status = "accepted" WHERE id = ?', (ticket_id,))
        db.commit()
        return {"status": "ok", "message": f"接单成功！您是当前第 {current_acceptors + 1} 位接单者。"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": f"接单异常: {str(e)}"}


@bot_bp.route('/grab_order_by_reply', methods=['POST'])
def grab_order_by_reply():
    """成员通过回复“抢单”来接单"""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload"}), 400
        
    qq_number = data.get('qq_number')
    message_id = data.get('message_id')
    
    if not qq_number or not message_id:
        return jsonify({"status": "error", "message": "Missing qq_number or message_id"}), 400
        
    db = get_db()
    
    # 查找 message_id 对应的工单
    map_row = db.execute('SELECT work_order_id FROM qq_message_map WHERE message_id = ? ORDER BY created_at DESC LIMIT 1', (str(message_id),)).fetchone()
    if not map_row:
        return jsonify({"status": "error", "message": "无法找到该消息对应的工单"}), 404
        
    ticket_id = map_row['work_order_id']
    
    # 调用通用逻辑
    res = _common_accept_logic(db, qq_number, ticket_id)
    status_code = 200 if res['status'] == 'ok' else 400
    # 异常可能是 500，稍微做个检查
    if '异常' in res['message']: status_code = 500
    
    return jsonify(res), status_code


@bot_bp.route('/subscribe', methods=['POST'])
def subscribe():
    """QQ 订阅类目"""
    data = request.get_json()
    qq_number = data.get('qq_number')
    category_name = data.get('category_name')
    
    if not qq_number or not category_name:
        return jsonify({"status": "error", "message": "Missing arguments"}), 400
        
    db = get_db()
    cat = db.execute('SELECT id FROM categories WHERE name = ?', (category_name,)).fetchone()
    if not cat:
        return jsonify({"status": "error", "message": f"未找到名为 {category_name} 的分类"}), 404
        
    try:
        db.execute('INSERT INTO qq_subscriptions (qq_number, category_id) VALUES (?, ?)', (qq_number, cat['id']))
        db.commit()
        return jsonify({"status": "ok", "message": f"成功订阅: {category_name}"})
    except Exception as e:
        # likely UNIQUE constraint failed
        return jsonify({"status": "error", "message": f"您可能已经订阅过该分类，或发生错误: {str(e)}"}), 400

@bot_bp.route('/unsubscribe', methods=['POST'])
def unsubscribe():
    """取消 QQ 订阅"""
    data = request.get_json()
    qq_number = data.get('qq_number')
    category_name = data.get('category_name')
    
    if not qq_number or not category_name:
        return jsonify({"status": "error", "message": "Missing arguments"}), 400
        
    db = get_db()
    cat = db.execute('SELECT id FROM categories WHERE name = ?', (category_name,)).fetchone()
    if not cat:
        return jsonify({"status": "error", "message": f"未找到名为 {category_name} 的分类"}), 404
        
    db.execute('DELETE FROM qq_subscriptions WHERE qq_number = ? AND category_id = ?', (qq_number, cat['id']))
    db.commit()
    return jsonify({"status": "ok", "message": f"成功取消订阅: {category_name}"})
