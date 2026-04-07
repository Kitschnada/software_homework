import os
from werkzeug.utils import secure_filename
from flask import current_app  # 导入 current_app 替代手动创建 app

def allowed_file(filename):
    # 使用 current_app 获取配置，它代表当前运行的应用实例
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

def save_file(file, folder_config_name):
    """
    folder_config_name: 传入 'UPLOAD_FOLDER' 或 'RESULT_FOLDER'
    """
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # 动态获取当前应用的路径配置
        base_path = current_app.config[folder_config_name]
        file.save(os.path.join(base_path, filename))
        return filename
    return None