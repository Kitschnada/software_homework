# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # 基础安全配置
    SECRET_KEY = 'dev_key_for_testing_only'
    DATABASE = os.path.join(basedir, 'database.db')  # 绝对路径（PythonAnywhere 必需）
    
    # 物理路径配置
    UPLOAD_FOLDER = os.path.join(basedir, 'app', 'static', 'uploads')
    RESULT_FOLDER = os.path.join(basedir, 'app', 'static', 'results')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'pdf', 'zip', 'rar', 'mp4', 'mov'}
    
    # 系统管理员初始化配置
    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD = 'wjxxyrmtzx'

    # ============================================================
    #  QQ 机器人与动态配置
    # ============================================================
    
    # 服务器端 API 鉴权令牌（两端必须一致）
    QQ_BOT_TOKEN = 'IThK.RzDME3JBfme'

    # 动态配置文件路径
    BOT_SETTINGS_FILE = os.path.join(basedir, 'bot_settings.json')

    # ============================================================
    #  PythonAnywhere 自动续期配置
    # ============================================================
    PA_USERNAME = 'LiuMuqing'                          # PythonAnywhere 用户名
    PA_PASSWORD = 'lmq20041123'                                    # PythonAnywhere 密码（填上）
    PA_DOMAIN = 'liumuqing.pythonanywhere.com'          # 你的网站域名

# 自动创建物理目录
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.RESULT_FOLDER, exist_ok=True)