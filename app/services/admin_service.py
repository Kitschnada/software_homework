from app.db import get_db
import os
from werkzeug.security import generate_password_hash
import datetime

class AdminService:
    @staticmethod
    def generate_unique_id(dept_id):
        """
        核心算法：生成唯一识别码 (UID)
        格式：部门Code + 年份 + 3位流水号 (例如 MEDIA2026001)
        使用 MAX 提取最大流水号，防止删除用户后产生 UID 冲突
        """
        db = get_db()
        
        # 1. 获取部门代码 (如 MEDIA)
        dept = db.execute('SELECT code FROM departments WHERE id = ?', (dept_id,)).fetchone()
        if not dept: return None
        dept_code = dept['code']
        
        # 2. 获取当前年份
        year = datetime.datetime.now().year
        
        # 3. 提取该部门该年份的最大流水号
        prefix = f"{dept_code}{year}"
        prefix_len = len(prefix)
        row = db.execute(
            'SELECT MAX(CAST(SUBSTR(uid, ?) AS INTEGER)) as max_seq FROM users WHERE uid LIKE ?',
            (prefix_len + 1, f'{prefix}%')
        ).fetchone()
        
        next_seq = (row['max_seq'] or 0) + 1
        
        # 4. 拼接 (流水号补零至3位)
        new_uid = f"{prefix}{str(next_seq).zfill(3)}"
        return new_uid
    
    @staticmethod
    def get_admin_context(user_id, role):
        """获取管理员身份上下文，识别融媒体管理员"""
        db = get_db()
        user = db.execute('''
            SELECT u.*, d.code as dept_code 
            FROM users u LEFT JOIN departments d ON u.department_id = d.id 
            WHERE u.id = ?
        ''', (user_id,)).fetchone()
        
        is_media_admin = (role == 'dept_admin' and user and user['dept_code'] == 'MEDIA')
        return user, is_media_admin

    @staticmethod
    def setup_new_department(name, code, head_name='', phone='', qq=''):
        """创建新部门并自动派生管理员账户 (包含附加信息)"""
        db = get_db()
        try:
            cursor = db.cursor()
            # 1. 插入部门 (带上新字段)
            cursor.execute('''
                INSERT INTO departments (name, code, head_name, phone, qq) 
                VALUES (?, ?, ?, ?, ?)
            ''', (name, code, head_name, phone, qq))
            dept_id = cursor.lastrowid
            
            # 2. 自动生成部门管理员
            admin_uid = f"ADMIN_{code}"
            admin_name = f"{name}管理员"
            virtual_card = f"ADM_{code}"
            virtual_phone = f"000_{code}"
            hashed_pwd = generate_password_hash(admin_uid)
            
            cursor.execute('''
                INSERT INTO users 
                (uid, password, role, department_id, real_name, card_id, phone, is_approved) 
                VALUES (?, ?, "dept_admin", ?, ?, ?, ?, 1)
            ''', (admin_uid, hashed_pwd, dept_id, admin_name, virtual_card, virtual_phone))
            
            db.commit()
            return True, f"部门 '{name}' 创建成功。管理员UID: {admin_uid} (密码相同)"
        except Exception as e:
            return False, f"创建失败：部门代码或名称冲突 ({str(e)})"
        
    @staticmethod
    def update_department(dept_id, name, code, head_name, phone, qq):
        """更新部门信息"""
        db = get_db()
        try:
            db.execute('''
                UPDATE departments 
                SET name=?, code=?, head_name=?, phone=?, qq=? 
                WHERE id=?
            ''', (name, code, head_name, phone, qq, dept_id))
            db.commit()
            return True, "部门信息更新成功"
        except Exception as e:
            return False, f"更新失败：代码可能与其他部门冲突 ({str(e)})"
        
    @staticmethod
    def get_visible_orders(user_id, role, q='',filter_dept=""):
        """视野分层逻辑 (已修复 username 报错)"""
        db = get_db()
        user, is_media_admin = AdminService.get_admin_context(user_id, role)
        p = f'%{q}%'
        
        # 修复：u1.username -> u1.real_name / u1.uid
        base_sql = '''
        SELECT w.*, c.name as category_name, u1.real_name as applicant_name, u1.uid as applicant_uid, d.name as dept_name,
               w.max_acceptors,
               GROUP_CONCAT(u2.real_name, '、') as acceptor_names,
               COUNT(a.id) as current_acceptors
        FROM work_orders w JOIN categories c ON w.category_id = c.id
        JOIN users u1 ON w.applicant_id = u1.id LEFT JOIN departments d ON w.department_id = d.id
        LEFT JOIN assignments a ON w.id = a.work_order_id
        LEFT JOIN users u2 ON a.acceptor_id = u2.id
        WHERE 1=1
    '''
        params = []
        
        # 1. 权限与部门筛选
        if role == 'admin' or is_media_admin:
            if filter_dept:
                base_sql += " AND w.department_id = ?"
                params.append(filter_dept)
        else:
            # 部门管理员强制锁死在本部门
            base_sql += " AND w.department_id = ?"
            params.append(user['department_id'])
            
        # 2. 任意有效字段模糊搜索
        if q:
            base_sql += " AND (w.requirements LIKE ? OR u1.real_name LIKE ? OR u1.uid LIKE ? OR u1.phone LIKE ? OR c.name LIKE ?)"
            p = f'%{q}%'
            params.extend([p, p, p, p, p])
            
        base_sql += " GROUP BY w.id ORDER BY w.created_at DESC"
        return db.execute(base_sql, params).fetchall()

    @staticmethod
    def get_manageable_users(user_id, role, q='', filter_dept='', filter_role=''):
        """获取正式成员 + 筛选搜索"""
        db = get_db()
        user, _ = AdminService.get_admin_context(user_id, role)
        
        base_sql = '''
            SELECT u.*, d.name as dept_name 
            FROM users u LEFT JOIN departments d ON u.department_id = d.id
            WHERE u.is_approved = 1
        '''
        params = []
        
        # 1. 部门筛选与权限锁定
        if role == 'admin':
            if filter_dept:
                base_sql += " AND u.department_id = ?"
                params.append(filter_dept)
        else:
            base_sql += " AND u.department_id = ?"
            params.append(user['department_id'])
            
        # 2. 角色筛选
        if filter_role:
            base_sql += " AND u.role = ?"
            params.append(filter_role)
            
        # 3. 任意有效字段搜索 (涵盖姓名/UID/手机/一卡通/昵称)
        if q:
            p = f'%{q}%'
            base_sql += " AND (u.real_name LIKE ? OR u.uid LIKE ? OR u.phone LIKE ? OR u.card_id LIKE ? OR u.nickname LIKE ?)"
            params.extend([p, p, p, p, p])
            
        return db.execute(base_sql, params).fetchall()
    
    @staticmethod
    def get_pending_users(user_id, role, q='', filter_dept='', filter_role=''):
        """获取待审核成员 + 筛选搜索"""
        db = get_db()
        user, _ = AdminService.get_admin_context(user_id, role)
        
        base_sql = '''
            SELECT u.*, d.name as dept_name 
            FROM users u LEFT JOIN departments d ON u.department_id = d.id 
            WHERE u.is_approved = 0
        '''
        params = []
        
        if role == 'admin':
            if filter_dept:
                base_sql += " AND u.department_id = ?"
                params.append(filter_dept)
        else:
            base_sql += " AND u.department_id = ?"
            params.append(user['department_id'])
            
        if filter_role:
            base_sql += " AND u.role = ?"
            params.append(filter_role)
            
        if q:
            p = f'%{q}%'
            base_sql += " AND (u.real_name LIKE ? OR u.uid LIKE ? OR u.phone LIKE ? OR u.card_id LIKE ? OR u.nickname LIKE ?)"
            params.extend([p, p, p, p, p])
            
        return db.execute(base_sql, params).fetchall()

    @staticmethod
    def approve_user(admin_id, admin_role, target_user_id):
        """审核通过"""
        db = get_db()
        target = db.execute('SELECT department_id FROM users WHERE id = ?', (target_user_id,)).fetchone()
        if not target: return False, "用户不存在"
        
        if admin_role != 'admin':
            me, _ = AdminService.get_admin_context(admin_id, admin_role)
            if str(me['department_id']) != str(target['department_id']):
                return False, "跨部门操作被拒绝"
        
        db.execute('UPDATE users SET is_approved = 1 WHERE id = ?', (target_user_id,))
        db.commit()
        return True, "审核通过"
    
    @staticmethod
    def delete_user(admin_id, admin_role, target_user_id):
        """【新增】删除用户 (安全校验)"""
        db = get_db()
        # 1. 不能删自己
        if str(admin_id) == str(target_user_id):
            return False, "无法删除自己的账户"

        # 2. 获取目标信息
        target = db.execute('SELECT role, department_id FROM users WHERE id = ?', (target_user_id,)).fetchone()
        if not target: return False, "用户不存在"

        # 3. 部门管理员权限检查
        if admin_role != 'admin':
            me, _ = AdminService.get_admin_context(admin_id, admin_role)
            # 不能删别部门的人
            if str(me['department_id']) != str(target['department_id']):
                return False, "无权删除其他部门用户"
            # 不能删同级的管理员或上级
            if target['role'] in ['admin', 'dept_admin']:
                return False, "权限不足：无法删除管理员账户"

        # 4. 超级管理员也不能删超级管理员 (硬性规则)
        if target['role'] == 'admin':
            return False, "无法删除超级管理员"

        db.execute('DELETE FROM users WHERE id = ?', (target_user_id,))
        db.commit()
        return True, "用户已删除"

    @staticmethod
    def get_system_stats():
        """统计数据"""
        db = get_db()
        try:
            return {
                'total': db.execute('SELECT COUNT(*) FROM work_orders').fetchone()[0],
                'completed': db.execute('SELECT COUNT(*) FROM work_orders WHERE status="completed"').fetchone()[0],
                'pending': db.execute('SELECT COUNT(*) FROM work_orders WHERE status="pending"').fetchone()[0]
            }
        except:
            return {'total':0, 'completed':0, 'pending':0}

    @staticmethod
    def purge_order(order_id, upload_dir, result_dir):
        """物理删除（支持多人接单）"""
        db = get_db()
        order = db.execute('SELECT attachment_path FROM work_orders WHERE id = ?', (order_id,)).fetchone()
        
        # 删除原始附件
        if order and order['attachment_path']:
            try: os.remove(os.path.join(upload_dir, order['attachment_path']))
            except OSError: pass
        
        # 删除所有接单人的成果文件
        assigns = db.execute('SELECT result_path FROM assignments WHERE work_order_id = ?', (order_id,)).fetchall()
        for assign in assigns:
            if assign['result_path']:
                try: os.remove(os.path.join(result_dir, assign['result_path']))
                except OSError: pass

        db.execute('DELETE FROM assignments WHERE work_order_id = ?', (order_id,))
        db.execute('DELETE FROM work_orders WHERE id = ?', (order_id,))
        db.commit()

    @staticmethod
    def get_user_for_edit(user_id):
        """获取单个用户的完整信息用于编辑"""
        db = get_db()
        return db.execute('''
            SELECT u.*, d.name as dept_name 
            FROM users u 
            LEFT JOIN departments d ON u.department_id = d.id 
            WHERE u.id = ?
        ''', (user_id,)).fetchone()

    @staticmethod
    def update_user_details(admin_id, admin_role, target_user_id, form):
        """
        管理员强制更新用户信息
        逻辑：
        1. 权限边界检查 (部门管理员不能跨部门操作，不能提权)
        2. 唯一性检查 (手机/一卡通不能与其他用户冲突)
        3. 执行更新
        """
        db = get_db()
        
        # --- A. 权限检查 ---
        if admin_role == 'dept_admin':
            # 1. 获取管理员自己的部门
            me = db.execute('SELECT department_id FROM users WHERE id = ?', (admin_id,)).fetchone()
            my_dept_id = str(me['department_id'])
            
            # 2. 检查目标是否试图被移出本部门
            if str(form['department_id']) != my_dept_id:
                return False, "权限不足：无法将成员移动到其他部门"
            
            # 3. 检查是否试图提升为超级管理员
            if form['role'] == 'admin':
                return False, "权限不足：无法设置为系统管理员"
                
            # 4. 检查目标原本是不是别的部门的人 (防止通过 URL 遍历修改他人)
            target_origin = db.execute('SELECT department_id FROM users WHERE id = ?', (target_user_id,)).fetchone()
            if target_origin and str(target_origin['department_id']) != my_dept_id:
                 return False, "权限不足：无法修改其他部门成员"

        # --- B. 唯一性冲突检查 (排除自己) ---
        # 检查一卡通
        conflict_card = db.execute('SELECT id FROM users WHERE card_id = ? AND id != ?', 
                                 (form['card_id'], target_user_id)).fetchone()
        if conflict_card: return False, "修改失败：该一卡通号已被其他人占用"
        
        # 检查手机号
        conflict_phone = db.execute('SELECT id FROM users WHERE phone = ? AND id != ?', 
                                  (form['phone'], target_user_id)).fetchone()
        if conflict_phone: return False, "修改失败：该手机号已被其他人占用"
        
        # 检查QQ号
        if form.get('qq_number'):
            conflict_qq = db.execute('SELECT id FROM users WHERE qq_number = ? AND id != ?', 
                                     (form['qq_number'], target_user_id)).fetchone()
            if conflict_qq: return False, "修改失败：该 QQ 号已被其他人占用"

        # --- C. 执行更新 ---
        try:
            # 如果输入了密码，则重置；否则只更新资料
            if form['password'] and form['password'].strip():
                hashed_pw = generate_password_hash(form['password'])
                db.execute('''
                    UPDATE users 
                    SET real_name=?, card_id=?, phone=?, qq_number=?, nickname=?, role=?, department_id=?, password=?
                    WHERE id=?
                ''', (form['real_name'], form['card_id'], form['phone'], form.get('qq_number'), form['nickname'], 
                      form['role'], form['department_id'], hashed_pw, target_user_id))
                msg = "用户资料及密码已强制更新"
            else:
                db.execute('''
                    UPDATE users 
                    SET real_name=?, card_id=?, phone=?, qq_number=?, nickname=?, role=?, department_id=?
                    WHERE id=?
                ''', (form['real_name'], form['card_id'], form['phone'], form.get('qq_number'), form['nickname'], 
                      form['role'], form['department_id'], target_user_id))
                msg = "用户资料已更新"
                
            db.commit()
            return True, msg
            
        except Exception as e:
            return False, f"数据库写入错误: {str(e)}"
        
    @staticmethod
    def get_data_screen_stats():
        """
        获取数据大屏所需的实时统计数据
        """
        db = get_db()
        
        # 1. 核心指标
        # 在岗人数 (定义为：角色为 acceptor 且 审核通过的人数)
        staff_count = db.execute('SELECT COUNT(*) FROM users WHERE role="acceptor" AND is_approved=1').fetchone()[0]
        
        # 工单总产出 (已完成的工单)
        finished_order = db.execute('SELECT COUNT(*) FROM work_orders WHERE status="completed"').fetchone()[0]
        
        # 正在处理 (繁忙度)
        processing_order = db.execute('SELECT COUNT(*) FROM work_orders WHERE status="accepted"').fetchone()[0]
        
        # 2. 系统运行时长 (假设系统上线日期为 2026-01-01，您可以根据实际情况修改)
        launch_date = datetime.datetime(2026, 1, 1)
        delta = datetime.datetime.now() - launch_date
        run_days = delta.days
        
        # 3. 部门贡献榜 (Top 5 活跃部门)
        # 统计哪个部门提交的工单最多
        dept_ranking = db.execute('''
            SELECT d.name, COUNT(w.id) as count 
            FROM work_orders w 
            JOIN departments d ON w.department_id = d.id 
            GROUP BY d.name 
            ORDER BY count DESC 
            LIMIT 5
        ''').fetchall()
            # 4. 实时动态 (最近 5 条完成记录)
        recent_activities = db.execute('''
            SELECT u.real_name, c.name as category, a.completed_at
            FROM work_orders w
            JOIN assignments a ON w.id = a.work_order_id                           
            JOIN users u ON w.applicant_id = u.id
            JOIN categories c ON w.category_id = c.id
            WHERE w.status = 'completed'
            ORDER BY w.created_at DESC
            LIMIT 5
        ''').fetchall()
        upcoming_tasks = db.execute('''
            SELECT w.*, c.name as category_name, d.name as dept_name, u.real_name as applicant_name
            FROM work_orders w
            JOIN categories c ON w.category_id = c.id
            JOIN users u ON w.applicant_id = u.id
            LEFT JOIN departments d ON w.department_id = d.id
            WHERE w.status IN ('pending', 'accepted') 
              AND w.deadline >= date('now', 'localtime') 
              AND w.deadline <= date('now', '+3 days', 'localtime')
            ORDER BY w.deadline ASC
        ''').fetchall()

        return {
            'staff_count': staff_count,
            'finished_order': finished_order,
            'processing_order': processing_order,
            'run_days': run_days,
            'dept_ranking': dept_ranking,
            'recent_activities': recent_activities,
            'upcoming_tasks': upcoming_tasks
        }  
    
    @staticmethod
    def get_upcoming_tasks():
        """获取未来3天内将截止的未完成工单 (系统管理员看板滚动播报专用)"""
        db = get_db()
        return db.execute('''
            SELECT w.*, c.name as category_name, d.name as dept_name, u.real_name as applicant_name
            FROM work_orders w
            JOIN categories c ON w.category_id = c.id
            JOIN users u ON w.applicant_id = u.id
            LEFT JOIN departments d ON w.department_id = d.id
            WHERE w.status IN ('pending', 'accepted') 
              AND w.deadline >= date('now', 'localtime') 
              AND w.deadline <= date('now', '+3 days', 'localtime')
            ORDER BY w.deadline ASC
        ''').fetchall()      
    
    @staticmethod
    def get_all_acceptor_hours():
        """获取所有接单员及其累计志愿工时"""
        db = get_db()
        return db.execute('''
            SELECT u.id, u.uid, u.real_name, u.phone,
                   COALESCE(ah.total_hours, 0) as total_hours,
                   (SELECT COUNT(*) FROM assignments a WHERE a.acceptor_id = u.id) as task_count,
                   (SELECT COUNT(*) FROM assignments a 
                    JOIN work_orders w ON a.work_order_id = w.id 
                    WHERE a.acceptor_id = u.id AND w.status = 'completed') as completed_count
            FROM users u
            LEFT JOIN acceptor_hours ah ON u.id = ah.acceptor_id
            WHERE u.role = 'acceptor' AND u.is_approved = 1
            ORDER BY ah.total_hours DESC
        ''').fetchall()

    @staticmethod
    def admin_set_volunteer_hours(acceptor_id, hours):
        """管理员直接设置接单员工时（封顶30）"""
        if hours < 0 or hours > 30:
            return False, "工时必须在 0 到 30 小时之间"
        db = get_db()
        # 确认目标是 acceptor
        user = db.execute('SELECT role FROM users WHERE id = ?', (acceptor_id,)).fetchone()
        if not user or user['role'] != 'acceptor':
            return False, "目标用户不是接单员"
        db.execute('''
            INSERT INTO acceptor_hours (acceptor_id, total_hours) VALUES (?, ?)
            ON CONFLICT(acceptor_id) DO UPDATE SET total_hours = ?
        ''', (acceptor_id, hours, hours))
        db.commit()
        return True, "工时更新成功"