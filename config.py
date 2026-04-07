# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))
class Config:
    # 鍩虹瀹夊叏閰嶇疆
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_key_for_testing_only')
    DATABASE = 'database.db'
    
    # 鐗╃悊璺緞閰嶇疆
    UPLOAD_FOLDER = os.path.join(basedir, 'app', 'static', 'uploads')
    RESULT_FOLDER = os.path.join(basedir, 'app', 'static', 'results')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'pdf', 'zip', 'rar', 'mp4', 'mov'}
    
    # --- 绯荤粺绠＄悊鍛樺垵濮嬪寲閰嶇疆 (浠庣幆澧冨彉閲忚鍙�) ---
    # 濡傛灉鐜鍙橀噺涓病璁惧畾锛屽垯鎻愪緵涓€涓緝澶嶆潅鐨勯粯璁ゅ€硷紙浠呯敤浜庡紑鍙戞祴璇曪級
    ADMIN_USERNAME = os.environ.get('INIT_ADMIN_USER', 'admin')
    ADMIN_PASSWORD = os.environ.get('INIT_ADMIN_PWD', 'wjxxyrmtzx')

# 鑷姩鍒涘缓鐗╃悊鐩綍
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.RESULT_FOLDER, exist_ok=True)