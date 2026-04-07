from flask import redirect, url_for, session
from app import create_app
import os

app = create_app()

@app.route('/')
def index():
    # 强制约束：只要没登录，全部打回登录界面
    if 'user_id' not in session:
        return redirect(url_for('login')) # 匹配 HTML 中的端点名
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    if not os.path.exists(app.config['DATABASE']):
        with app.app_context():
            from app.db import init_db
            init_db()
    app.run(debug=True, port=5000)