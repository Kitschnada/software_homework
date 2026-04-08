# PythonAnywhere WSGI 配置文件
# 部署时将此文件的内容粘贴到 PythonAnywhere 的 WSGI configuration file 中
# 路径通常是 /var/www/你的用户名_pythonanywhere_com_wsgi.py

import sys
import os

# 项目路径（根据你的 PythonAnywhere 用户名修改）
project_home = '/home/LiuMuqing'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# 设置环境变量（可选，也可以写在 config.py 里）
os.environ['FLASK_ENV'] = 'production'

from app import create_app
from app.db import init_db

application = create_app()

# 首次部署时初始化数据库（之后可以注释掉）
db_path = os.path.join(project_home, 'database.db')
if not os.path.exists(db_path):
    with application.app_context():
        init_db()
