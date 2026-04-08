import os
import uuid
import json
from flask import current_app
from werkzeug.utils import secure_filename
from app.db import get_db

class OrderService:
    # =========================================================
    # 1. 读操作：数据查询
    # =========================================================
    
    @staticmethod
    def get_applicant_data(user_id):
        """
        获取申请者看板数据
        返回两组数据：
        1. my_orders: 我的工单 (拥有全部操作权限)
        2. dept_orders: 本部门其他人的工单 (仅查看权限)
        """
        db = get_db()
        
        # 1. 我的工单 (查询我提交的所有工单)
        # 关联查询接单人姓名，方便我知道谁在处理我的事
        my_orders = db.execute('''
            SELECT w.*, c.name as category_name, u.real_name as acceptor_name, a.result_path, d.name as dept_name
            FROM work_orders w
            JOIN categories c ON w.category_id = c.id
            LEFT JOIN assignments a ON w.id = a.work_order_id
            LEFT JOIN users u ON a.acceptor_id = u.id
            LEFT JOIN departments d ON w.department_id = d.id
            WHERE w.applicant_id = ?
            ORDER BY w.created_at DESC
        ''', (user_id,)).fetchall()

        # 2. 本部门其他人工单 (Visibility: Visible)
        # 先获取当前用户部门
        user = db.execute('SELECT department_id FROM users WHERE id = ?', (user_id,)).fetchone()
        dept_orders = []
        
        if user and user['department_id']:
            # 查询：同部门 + 非本人提交
            # 同时也查出是谁申请的 (applicant_name) 和 谁接单的 (acceptor_name)
            dept_orders = db.execute('''
                SELECT w.*, c.name as category_name, 
                       u1.real_name as applicant_name, -- 申请人
                       u2.real_name as acceptor_name   -- 接单人
                FROM work_orders w
                JOIN categories c ON w.category_id = c.id
                JOIN users u1 ON w.applicant_id = u1.id
                LEFT JOIN assignments a ON w.id = a.work_order_id
                LEFT JOIN users u2 ON a.acceptor_id = u2.id
                WHERE w.department_id = ? AND w.applicant_id != ?
                ORDER BY w.created_at DESC
            ''', (user['department_id'], user_id)).fetchall()
        
        return my_orders, dept_orders

    @staticmethod
    def get_acceptor_view_data(user_id):
        """获取接单员看板数据 (全局视野)"""
        db = get_db()
        # 1. 待接单池 (全校可见)
        available = db.execute('''
            SELECT w.*, c.name as category_name, 
                   u.real_name as applicant_name, u.uid as applicant_uid, u.phone as applicant_phone,
                   d.name as dept_name,
                   w.max_acceptors,
                   (SELECT COUNT(*) FROM assignments a2 WHERE a2.work_order_id = w.id) as current_acceptors
            FROM work_orders w 
            JOIN categories c ON w.category_id = c.id
            JOIN users u ON w.applicant_id = u.id 
            LEFT JOIN departments d ON w.department_id = d.id
            WHERE (w.status = 'pending'
                   OR (w.status = 'accepted' 
                       AND (SELECT COUNT(*) FROM assignments a3 WHERE a3.work_order_id = w.id) < w.max_acceptors))
              AND w.id NOT IN (SELECT a4.work_order_id FROM assignments a4 WHERE a4.acceptor_id = ?)
            ORDER BY w.created_at ASC
        ''', (user_id,)).fetchall()

        # 2. 我的任务
        my_tasks = db.execute('''
            SELECT w.*, c.name as category_name, 
                   u.real_name as applicant_name, u.phone as applicant_phone,
                   d.name as dept_name,
                   a.id as assignment_id, a.accepted_at, a.completed_at, a.result_path
            FROM assignments a 
            JOIN work_orders w ON a.work_order_id = w.id
            JOIN categories c ON w.category_id = c.id 
            JOIN users u ON w.applicant_id = u.id
            LEFT JOIN departments d ON w.department_id = d.id
            WHERE a.acceptor_id = ?
            ORDER BY w.status DESC, a.accepted_at DESC
        ''', (user_id,)).fetchall()
        return available, my_tasks

    @staticmethod
    def get_order_by_id(order_id):
        db = get_db()
        return db.execute('SELECT * FROM work_orders WHERE id = ?', (order_id,)).fetchone()

    # =========================================================
    # 2. 写操作：权限控制 (Action: Private)
    # =========================================================

    @staticmethod
    def create_order(user_id, form, file):
        db = get_db()
        user = db.execute('SELECT department_id FROM users WHERE id = ?', (user_id,)).fetchone()
        
        filename = None
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            filename = str(uuid.uuid4()) + ext
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            
        max_acceptors = int(form.get('max_acceptors', 1))
        if max_acceptors < 1: max_acceptors = 1
        if max_acceptors > 10: max_acceptors = 10

        try:
            cursor = db.execute('''
                INSERT INTO work_orders (applicant_id, category_id, department_id, contact, deadline, requirements, attachment_path, max_acceptors) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, form['category_id'], user['department_id'], 
                  form['contact'], form['deadline'], form['requirements'], filename, max_acceptors))
            work_order_id = cursor.lastrowid
            db.commit()
            
            # 写入 QQ 通知队列（本地机器人会轮询拉取发送）
            try:
                from app.services.qq_notify import notify_new_order
                cat = db.execute('SELECT name FROM categories WHERE id = ?', (form['category_id'],)).fetchone()
                dept = db.execute('SELECT name FROM departments WHERE id = ?', (user['department_id'],)).fetchone()
                notify_new_order(
                    app=None,
                    work_order_id=work_order_id,
                    category_name=cat['name'] if cat else '未知',
                    dept_name=dept['name'] if dept else '未知',
                    requirements=form['requirements'],
                    deadline=form['deadline'],
                    max_acceptors=max_acceptors,
                    contact=form['contact']
                )
            except Exception as e:
                print(f"[QQ Bot] 通知触发异常(不影响工单): {e}")
            
            return True, "工单创建成功"
        except Exception as e:
            return False, f"创建失败: {str(e)}"

    @staticmethod
    def edit_order(order_id, user_id, form, file):
        db = get_db()
        order = db.execute('SELECT * FROM work_orders WHERE id = ?', (order_id,)).fetchone()
        
        # 【权限铁闸】严防修改他人订单
        if not order: return False, "工单不存在"
        if str(order['applicant_id']) != str(user_id): return False, "权限不足：您只能修改自己提交的工单"
        if order['status'] not in ('pending', 'rejected'): return False, "工单已在处理中，无法修改"
        
        new_filename = order['attachment_path']
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            unique_name = str(uuid.uuid4()) + ext
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name))
            new_filename = unique_name
            if order['attachment_path']:
                try: os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], order['attachment_path']))
                except OSError: pass

        max_acceptors = int(form.get('max_acceptors', order['max_acceptors'] or 1))
        if max_acceptors < 1: max_acceptors = 1
        if max_acceptors > 10: max_acceptors = 10

        db.execute('''
            UPDATE work_orders 
            SET contact = ?, deadline = ?, requirements = ?, attachment_path = ?, max_acceptors = ?, status = 'pending'
            WHERE id = ?
        ''', (form['contact'], form['deadline'], form['requirements'], new_filename, max_acceptors, order_id))
        db.commit()
        
        if order['status'] == 'rejected':
            # 驳回重提交：写入 QQ 通知队列
            try:
                from app.services.qq_notify import notify_new_order
                cat = db.execute('SELECT name FROM categories WHERE id = ?', (order['category_id'],)).fetchone()
                dept = db.execute('SELECT name FROM departments WHERE id = ?', (order['department_id'],)).fetchone()
                notify_new_order(
                    app=None,
                    work_order_id=order_id,
                    category_name=(cat['name'] if cat else '未知') + '（重新提交）',
                    dept_name=dept['name'] if dept else '未知',
                    requirements=form['requirements'],
                    deadline=form['deadline'],
                    max_acceptors=max_acceptors,
                    contact=form['contact']
                )
            except Exception as e:
                print(f"[QQ Bot] 通知触发异常(不影响工单): {e}")
            return True, "工单已重新提交，等待接单"
        return True, "工单更新成功"

    @staticmethod
    def cancel_order(order_id, user_id):
        db = get_db()
        order = db.execute('SELECT * FROM work_orders WHERE id = ?', (order_id,)).fetchone()
        
        # 【权限铁闸】严防撤销他人订单
        if not order: return False, "工单不存在"
        if str(order['applicant_id']) != str(user_id): return False, "权限不足：您只能撤销自己提交的工单"
        if order['status'] != 'pending': return False, "无法撤销已接单的任务"
        
        if order['attachment_path']:
            try: os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], order['attachment_path']))
            except OSError: pass
            
        db.execute('DELETE FROM work_orders WHERE id = ?', (order_id,))
        db.commit()
        return True, "工单已撤销"

    @staticmethod
    def rate_order(order_id, user_id, rating, comment):
        db = get_db()
        db.execute('UPDATE work_orders SET rating = ?, comment = ? WHERE id = ? AND applicant_id = ? AND status="completed"', 
                   (rating, comment, order_id, user_id))
        db.commit()
        return True, "评价提交成功"

    @staticmethod
    def accept_order(order_id, acceptor_id):
        db = get_db()
        order = db.execute('SELECT status, max_acceptors FROM work_orders WHERE id = ?', (order_id,)).fetchone()
        if not order or order['status'] not in ('pending', 'accepted'):
            return False, "工单已完成或已被驳回"

        # 检查是否已接过这个单
        already = db.execute('SELECT id FROM assignments WHERE work_order_id = ? AND acceptor_id = ?', (order_id, acceptor_id)).fetchone()
        if already:
            return False, "您已接过此工单"

        # 检查名额
        max_acc = order['max_acceptors'] or 1
        current = db.execute('SELECT COUNT(*) FROM assignments WHERE work_order_id = ?', (order_id,)).fetchone()[0]
        if current >= max_acc:
            return False, "手慢了，接单名额已满"

        db.execute('INSERT INTO assignments (work_order_id, acceptor_id) VALUES (?, ?)', (order_id, acceptor_id))
        
        # 名额填满后将工单状态设为 accepted
        if current + 1 >= max_acc:
            db.execute('UPDATE work_orders SET status = "accepted" WHERE id = ?', (order_id,))
        
        db.commit()
        return True, "抢单成功"

    @staticmethod
    def upload_result(assignment_id, acceptor_id, file):
        if not file or not file.filename: return False, "无文件"
        db = get_db()
        assign = db.execute('SELECT * FROM assignments WHERE id = ? AND acceptor_id = ?', (assignment_id, acceptor_id)).fetchone()
        if not assign: return False, "无权操作"
        ext = os.path.splitext(file.filename)[1].lower()
        filename = str(uuid.uuid4()) + ext
        file.save(os.path.join(current_app.config['RESULT_FOLDER'], filename))
        db.execute('UPDATE assignments SET result_path = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?', (filename, assignment_id))
        
        # 多人接单时，只有所有人都提交成果后才标记工单完成
        total_assignments = db.execute('SELECT COUNT(*) FROM assignments WHERE work_order_id = ?', (assign['work_order_id'],)).fetchone()[0]
        completed_assignments = db.execute('SELECT COUNT(*) FROM assignments WHERE work_order_id = ? AND result_path IS NOT NULL', (assign['work_order_id'],)).fetchone()[0]
        if completed_assignments >= total_assignments:
            db.execute('UPDATE work_orders SET status = "completed" WHERE id = ?', (assign['work_order_id'],))
        db.commit()

        # 工单完成后自动分配志愿时长
        try:
            order = db.execute(
                'SELECT c.name as category_name FROM work_orders w '
                'JOIN categories c ON w.category_id = c.id '
                'WHERE w.id = ?', (assign['work_order_id'],)
            ).fetchone()
            if order:
                OrderService.assign_volunteer_hours(assignment_id, order['category_name'])
        except Exception:
            pass  # 志愿时长分配失败不影响工单完成

        return True, "上传成功，工单已完成"
    
    @staticmethod
    def assign_volunteer_hours(assignment_id, category_name):
        """
        根据任务类型分配志愿时长，并确保接单员的累计总时长不超过30小时。
        同时更新 assignments 单条记录和 acceptor_hours 总计。
        """
        db = get_db()

        # 获取当前 assignment 信息和接单员 ID
        assignment = db.execute(
            'SELECT volunteer_hours, acceptor_id FROM assignments WHERE id = ?',
            (assignment_id,)
        ).fetchone()

        if not assignment:
            raise ValueError("Assignment not found")

        # 从 order_service 管理的配置中读取默认志愿时长
        hours_mapping = OrderService.get_hours_mapping()

        # 防止 key 为 string 导致 float(:) 时抛异常
        # 默认值为 0 
        additional_hours = float(hours_mapping.get(category_name, 0))

        # 从 acceptor_hours 表获取累计总时长
        total = OrderService.get_acceptor_total_hours(assignment['acceptor_id'])

        # 确保接单员累计总时长不超过30小时
        if total + additional_hours > 30:
            additional_hours = max(0, 30 - total)

        if additional_hours > 0:
            # 更新单条 assignment 记录
            new_hours = assignment['volunteer_hours'] + additional_hours
            db.execute(
                'UPDATE assignments SET volunteer_hours = ? WHERE id = ?',
                (new_hours, assignment_id)
            )
            # 更新 acceptor_hours 总计表
            db.execute('''
                INSERT INTO acceptor_hours (acceptor_id, total_hours) VALUES (?, ?)
                ON CONFLICT(acceptor_id) DO UPDATE SET total_hours = total_hours + ?
            ''', (assignment['acceptor_id'], additional_hours, additional_hours))
            db.commit()

    @staticmethod
    def get_acceptor_total_hours(acceptor_id):
        """
        从 acceptor_hours 表获取接单员的累计志愿时长。
        """
        db = get_db()
        result = db.execute(
            'SELECT total_hours FROM acceptor_hours WHERE acceptor_id = ?',
            (acceptor_id,)
        ).fetchone()
        return result['total_hours'] if result else 0

    @staticmethod
    def get_hours_mapping():
        """获取默认志愿时长配置"""
        config_path = os.path.join(os.path.dirname(__file__), 'volunteer_hours.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            '视频制作': 5.0,
            '海报设计': 4.0,
            '图文排版': 2.5,
            '活动摄影': 2.0,
            '文案撰写': 2.0,
            '其他': 1.0
        }

    @staticmethod
    def set_hours_mapping(mapping):
        """保存默认志愿时长配置"""
        config_path = os.path.join(os.path.dirname(__file__), 'volunteer_hours.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            # 确保存储为浮点型，并去除首尾空格
            clean_mapping = {str(k).strip(): float(v) for k, v in mapping.items()}
            json.dump(clean_mapping, f, ensure_ascii=False, indent=4)


    @staticmethod
    def get_calendar_events(user_id, role, dept_code, dept_id):
        """
        获取日历事件数据，按权限分级：
        1. 融媒体管理员：看全校所有正在进行的工单
        2. 部门管理员：看本部门正在进行的工单
        3. 成员(接单员)：看自己认领的工单
        4. 申请者：看自己发起的工单
        """
        db = get_db()
        base_sql = '''
            SELECT w.id, w.deadline, w.requirements, c.name as category_name, w.status 
            FROM work_orders w
            JOIN categories c ON w.category_id = c.id
        '''
        events = []
        
        if role == 'dept_admin':
            if dept_code == 'MEDIA':
                events = db.execute(base_sql + " WHERE w.status IN ('pending', 'accepted')").fetchall()
            else:
                events = db.execute(base_sql + " WHERE w.status IN ('pending', 'accepted') AND w.department_id = ?", (dept_id,)).fetchall()
        elif role == 'acceptor':
            events = db.execute(base_sql + " JOIN assignments a ON w.id = a.work_order_id WHERE w.status = 'accepted' AND a.acceptor_id = ?", (user_id,)).fetchall()
        elif role == 'applicant':
            events = db.execute(base_sql + " WHERE w.status IN ('pending', 'accepted') AND w.applicant_id = ?", (user_id,)).fetchall()

        # 转换为 FullCalendar 接受的 JSON 格式
        formatted_events = []
        for e in events:
            req = e['requirements'] or ''
            title = f"[{e['category_name']}] {req[:10]}..."
            # pending(待接单)为黄色，accepted(处理中)为蓝色
            color = '#ffc107' if e['status'] == 'pending' else '#007bff'
            formatted_events.append({
                'id': e['id'],
                'title': title,
                'start': e['deadline'],
                'color': color,
                'allDay': True  # 全天事件
            })
        return formatted_events