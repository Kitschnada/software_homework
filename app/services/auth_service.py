# app/services/auth_service.py
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db
import datetime

class AuthService:
    @staticmethod
    def generate_unique_id(dept_id):
        """
        核心算法：生成唯一识别码 (UID)
        格式：部门Code + 年份 + 3位流水号 (例如 MEDIA2026001)
        """
        db = get_db()
        
        # 1. 获取部门代码 (如 MEDIA)
        dept = db.execute('SELECT code FROM departments WHERE id = ?', (dept_id,)).fetchone()
        if not dept: return None
        dept_code = dept['code']
        
        # 2. 获取当前年份
        year = datetime.datetime.now().year
        
        # 3. 计算该部门今年已注册多少人，生成流水号
        # 使用 LIKE 查询该部门该年份前缀的现有用户数
        prefix = f"{dept_code}{year}"
        count = db.execute('SELECT COUNT(*) FROM users WHERE uid LIKE ?', (f'{prefix}%',)).fetchone()[0]
        
        # 4. 拼接 (流水号+1，并补零至3位)
        new_uid = f"{prefix}{str(count + 1).zfill(3)}"
        return new_uid

    @staticmethod
    def register_user(form):
        """
        重构后的注册逻辑：
        输入：一卡通、姓名、手机、部门、密码
        输出：自动分配的 UID
        """
        db = get_db()
        card_id = form.get('card_id')
        real_name = form.get('real_name')
        phone = form.get('phone')
        dept_id = form.get('department_id')
        role = form.get('role')
        password = form.get('password')
        
        # 1. 角色与部门修正
        if role in ['admin', 'dept_admin']: return False, "禁止注册管理账户"
        if role == 'acceptor':
            media = db.execute('SELECT id FROM departments WHERE code = "MEDIA"').fetchone()
            dept_id = media['id'] if media else None
            
        if not dept_id: return False, "必须选择所属部门"

        # 2. 检查唯一性冲突 (一卡通、手机号)
        exist = db.execute('SELECT id FROM users WHERE card_id = ? OR phone = ?', (card_id, phone)).fetchone()
        if exist: return False, "注册失败：一卡通号或手机号已被占用"

        # 3. 生成唯一识别码 UID
        uid = AuthService.generate_unique_id(dept_id)
        if not uid: return False, "UID生成失败，请检查部门代码配置"

        try:
            db.execute('''
                INSERT INTO users (uid, password, card_id, real_name, phone, role, department_id, is_approved) 
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ''', (uid, generate_password_hash(password), card_id, real_name, phone, role, dept_id))
            db.commit()
            return True, f"注册成功！您的唯一识别码为：{uid}。需等待审核通过后方可登录。"
        except Exception as e:
            return False, f"数据库错误: {str(e)}"

    @staticmethod
    def authenticate_user(identifier, password):
        """
        重构后的登录逻辑：支持 识别码/一卡通/手机/昵称 混登
        identifier: 用户输入的登录账号
        """
        db = get_db()
        
        # 1. 多字段匹配查询
        user = db.execute('''
            SELECT * FROM users 
            WHERE uid = ? OR card_id = ? OR phone = ? OR nickname = ?
        ''', (identifier, identifier, identifier, identifier)).fetchone()
        
        # 2. 密码校验
        if user and check_password_hash(user['password'], password):
            # 3. 审核状态校验
            if user['is_approved'] == 0:
                return "pending"
            return user
            
        return None
        
    @staticmethod
    def get_user_profile(user_id):
        """获取用户详细信息（含部门名称，用于展示）"""
        db = get_db()
        return db.execute('''
            SELECT u.*, d.name as dept_name 
            FROM users u 
            LEFT JOIN departments d ON u.department_id = d.id 
            WHERE u.id = ?
        ''', (user_id,)).fetchone()

    @staticmethod
    def update_profile(user_id, nickname, phone, new_password=None):
        """
        综合更新个人信息
        1. 校验手机号/昵称唯一性 (排除自己)
        2. 更新 昵称、手机
        3. 如果提供了新密码，则加密更新；否则保留原密码
        """
        db = get_db()
        
        # 1. 唯一性检查 (排除当前用户 ID)
        # 检查手机号
        exist_phone = db.execute('SELECT id FROM users WHERE phone = ? AND id != ?', (phone, user_id)).fetchone()
        if exist_phone: return False, "修改失败：该手机号已被其他账号绑定"
        
        # 检查昵称 (如果昵称不为空)
        if nickname:
            exist_nick = db.execute('SELECT id FROM users WHERE nickname = ? AND id != ?', (nickname, user_id)).fetchone()
            if exist_nick: return False, "修改失败：该昵称太受欢迎了，换一个吧"

        try:
            # 2. 动态构建 SQL
            if new_password and new_password.strip():
                # 情况A: 修改信息 + 修改密码
                hashed_pw = generate_password_hash(new_password)
                db.execute('''
                    UPDATE users 
                    SET nickname = ?, phone = ?, password = ? 
                    WHERE id = ?
                ''', (nickname, phone, hashed_pw, user_id))
                msg = "个人信息与密码已同步更新"
            else:
                # 情况B: 仅修改信息
                db.execute('''
                    UPDATE users 
                    SET nickname = ?, phone = ? 
                    WHERE id = ?
                ''', (nickname, phone, user_id))
                msg = "个人信息更新成功"
                
            db.commit()
            return True, msg
        except Exception as e:
            return False, f"数据库错误: {str(e)}"