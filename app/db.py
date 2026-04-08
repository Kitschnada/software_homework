import sqlite3
import os
from flask import g, current_app
from werkzeug.security import generate_password_hash

def get_db():
    """获取数据库连接"""
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        # 强制开启外键约束，保证级联删除生效
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

def close_db(e=None):
    """关闭数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """初始化数据库结构并注入核心基础数据"""
    db = get_db()
    schema_path = os.path.join(current_app.root_path, '..', 'schema.sql')
    
    # ==========================================
    # 1. 执行最新的 schema.sql，建立完整表结构
    # ==========================================
    try:
        with open(schema_path, mode='r', encoding='utf-8') as f:
            db.cursor().executescript(f.read())
        print("[*] 成功读取并执行 schema.sql，数据库结构已初始化。")
    except Exception as e:
        print(f"[!] 读取 schema.sql 失败: {e}")
        return # 如果建表失败，直接返回，不执行后续插入

    # ==========================================
    # 2. 注入系统必须的基础数据
    # ==========================================
    try:
        # 2.1 注入默认核心部门
        db.execute('INSERT OR IGNORE INTO departments (name, code) VALUES ("融媒体中心", "MEDIA")')
        
        # 2.2 注入系统超级管理员 (不受部门权限限制)
        admin_uid = 'ADMIN001' 
        admin_card = '000000000'      # 预留一卡通号
        admin_phone = '00000000000'   # 预留手机号
        admin_name = current_app.config.get('ADMIN_USERNAME', '系统管理员')
        admin_pwd = generate_password_hash(current_app.config.get('ADMIN_PASSWORD', 'admin123')) 
        
        db.execute('''
            INSERT OR IGNORE INTO users 
            (uid, password, card_id, real_name, phone, nickname, role, is_approved) 
            VALUES (?, ?, ?, ?, ?, "admin", "admin", 1)
        ''', (admin_uid, admin_pwd, admin_card, admin_name, admin_phone))
   
        default_categories = ['视频制作', '海报设计', '图文排版', '活动摄影', '文案撰写', '其他']
        for cat in default_categories:
            db.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (cat,))
        
        db.commit()
        print("[*] 数据库初始化完成，超级管理员及基础数据已注入！")
        
    except Exception as e:
        print(f"[!] 基础数据注入失败: {e}")




    