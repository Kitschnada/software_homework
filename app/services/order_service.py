import os
import uuid
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
                   d.name as dept_name
            FROM work_orders w 
            JOIN categories c ON w.category_id = c.id
            JOIN users u ON w.applicant_id = u.id 
            LEFT JOIN departments d ON w.department_id = d.id
            WHERE w.status = 'pending'
            ORDER BY w.created_at ASC
        ''').fetchall()

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
            
        try:
            db.execute('''
                INSERT INTO work_orders (applicant_id, category_id, department_id, contact, deadline, requirements, attachment_path) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, form['category_id'], user['department_id'], 
                  form['contact'], form['deadline'], form['requirements'], filename))
            db.commit()
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
        if order['status'] != 'pending': return False, "工单已在处理中，无法修改"
        
        new_filename = order['attachment_path']
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            unique_name = str(uuid.uuid4()) + ext
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name))
            new_filename = unique_name
            if order['attachment_path']:
                try: os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], order['attachment_path']))
                except OSError: pass

        db.execute('''
            UPDATE work_orders 
            SET contact = ?, deadline = ?, requirements = ?, attachment_path = ?
            WHERE id = ?
        ''', (form['contact'], form['deadline'], form['requirements'], new_filename, order_id))
        db.commit()
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
        order = db.execute('SELECT status FROM work_orders WHERE id = ?', (order_id,)).fetchone()
        if not order or order['status'] != 'pending':
            return False, "手慢了，工单已被抢走"
        db.execute('UPDATE work_orders SET status = "accepted" WHERE id = ?', (order_id,))
        db.execute('INSERT INTO assignments (work_order_id, acceptor_id) VALUES (?, ?)', (order_id, acceptor_id))
        db.commit()
        return True, "抢单成功"

    @staticmethod
    def upload_result(assignment_id, acceptor_id, file):
        if not file or not file.filename: return False, "未选择文件"
        db = get_db()
        assign = db.execute('SELECT * FROM assignments WHERE id = ? AND acceptor_id = ?', (assignment_id, acceptor_id)).fetchone()
        if not assign: return False, "无权操作"
        ext = os.path.splitext(file.filename)[1].lower()
        filename = str(uuid.uuid4()) + ext
        file.save(os.path.join(current_app.config['RESULT_FOLDER'], filename))
        db.execute('UPDATE assignments SET result_path = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?', (filename, assignment_id))
        db.execute('UPDATE work_orders SET status = "completed" WHERE id = ?', (assign['work_order_id'],))
        db.commit()
        return True, "上传成功，工单已完成"
    
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