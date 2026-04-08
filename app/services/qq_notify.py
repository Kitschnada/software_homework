# app/services/qq_notify.py
"""
QQ 群通知服务（队列模式）

架构：
  服务器端（Flask）→ 写入通知队列（数据库）
  本地端（qq_worker.py）→ 轮询拉取 → 通过本地 NapCat 发送到 QQ 群

这样 NapCat 只需在本地运行，服务器无需安装 QQ 相关组件。
"""

from app.db import get_db


def _format_order_message(work_order_id, category_name, dept_name, requirements, deadline, max_acceptors, contact):
    """格式化工单为可读的群消息"""
    req_preview = requirements[:80] + ('...' if len(requirements) > 80 else '')
    
    msg = (
        f"📋 【新工单通知】\n"
        f"🏷️ 单号：#{work_order_id}\n"
        f"📌 类别：{category_name}\n"
        f"🏢 部门：{dept_name or '未知'}\n"
        f"📝 需求：{req_preview}\n"
        f"⏰ 截止：{deadline}\n"
        f"👥 可接单：{max_acceptors} 人\n"
        f"📞 联系方式：{contact}\n"
        f"🔔 请登录工单系统抢单！"
    )
    return msg


def notify_new_order(app, work_order_id, category_name, dept_name, requirements, deadline, max_acceptors, contact):
    """
    将新工单通知写入数据库队列。
    本地的 qq_worker.py 会轮询拉取并通过 NapCat 发送。
    """
    message = _format_order_message(
        work_order_id, category_name, dept_name, requirements, deadline, max_acceptors, contact
    )
    
    try:
        db = get_db()
        db.execute('INSERT INTO qq_notifications (message, work_order_id) VALUES (?, ?)', (message, work_order_id))
        db.commit()
        print(f"[QQ Bot] ✅ 通知已加入队列")
    except Exception as e:
        print(f"[QQ Bot] ⚠️ 写入队列失败: {e}")


def get_pending_notifications():
    """获取所有待发送的通知（供 API 调用）"""
    db = get_db()
    rows = db.execute(
        'SELECT id, message, created_at FROM qq_notifications WHERE sent = 0 ORDER BY id ASC'
    ).fetchall()
    return [{'id': r['id'], 'message': r['message'], 'created_at': r['created_at']} for r in rows]


def mark_notifications_sent(items):
    """标记通知为已发送，同时记录 message_id 与 work_order_id 的映射
    items: [{'id': nid, 'message_id': msg_id}]
    """
    db = get_db()
    for item in items:
        nid = item.get('id')
        msg_id = item.get('message_id')
        
        # 获取 work_order_id
        row = db.execute('SELECT work_order_id FROM qq_notifications WHERE id = ?', (nid,)).fetchone()
        
        db.execute('UPDATE qq_notifications SET sent = 1 WHERE id = ?', (nid,))
        
        if row and row['work_order_id'] and msg_id:
            db.execute('INSERT INTO qq_message_map (message_id, work_order_id) VALUES (?, ?)', 
                       (str(msg_id), row['work_order_id']))
            
    db.commit()


def send_test_notification():
    """写入一条测试通知"""
    try:
        db = get_db()
        db.execute(
            'INSERT INTO qq_notifications (message) VALUES (?)',
            ('🤖 【系统测试】\n工单系统 QQ 通知功能已连通！',)
        )
        db.commit()
        return True, "测试通知已加入队列，等待本地机器人拉取发送"
    except Exception as e:
        return False, f"写入失败: {e}"
