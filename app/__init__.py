from flask import Flask,g
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 1. 延迟导入视图函数（防止循环导入）
    from app.routes import auth_routes, order_routes, admin_routes

    # 2. 核心：手动映射端点，确保 url_for('xxx') 即使在 HTML 中不改也能生效
    
    # 身份认证模块
    app.add_url_rule('/login', endpoint='login', view_func=auth_routes.login, methods=['GET', 'POST'])
    app.add_url_rule('/register', endpoint='register', view_func=auth_routes.register, methods=['GET', 'POST'])
    app.add_url_rule('/logout', endpoint='logout', view_func=auth_routes.logout)
    app.add_url_rule('/dashboard', endpoint='dashboard', view_func=auth_routes.dashboard)
    app.add_url_rule('/profile', endpoint='profile', view_func=auth_routes.profile, methods=['GET', 'POST'])
    # 工单业务模块
    app.add_url_rule('/applicant', endpoint='applicant_dashboard', view_func=order_routes.applicant_dashboard)
    app.add_url_rule('/create_order', endpoint='create_order', view_func=order_routes.create_order, methods=['POST'])
    app.add_url_rule('/rate_order/<int:order_id>', endpoint='rate_order', view_func=order_routes.rate_order, methods=['POST'])
    app.add_url_rule('/acceptor', endpoint='acceptor_dashboard', view_func=order_routes.acceptor_dashboard)
    app.add_url_rule('/accept_order/<int:order_id>', endpoint='accept_order', view_func=order_routes.accept_order)
    app.add_url_rule('/upload_result/<int:assignment_id>', endpoint='upload_result', view_func=order_routes.upload_result, methods=['POST'])
    app.add_url_rule('/calendar', endpoint='calendar_view', view_func=order_routes.calendar_view)

    # 后台管理模块
    app.add_url_rule('/admin', endpoint='admin_dashboard', view_func=admin_routes.admin_dashboard)
    app.add_url_rule('/create_department', endpoint='create_department', view_func=admin_routes.create_department, methods=['POST'])
    app.add_url_rule('/delete_department/<int:dept_id>', endpoint='delete_department', view_func=admin_routes.delete_department)
    app.add_url_rule('/manage_users', endpoint='manage_users', view_func=admin_routes.manage_users)
    app.add_url_rule('/create_user', endpoint='create_user', view_func=admin_routes.create_user, methods=['POST'])
    app.add_url_rule('/approve_user/<int:user_id>', endpoint='approve_user', view_func=admin_routes.approve_user_route)
    app.add_url_rule('/edit_order/<int:order_id>', endpoint='edit_order', view_func=order_routes.edit_order, methods=['GET', 'POST'])
    app.add_url_rule('/cancel_order/<int:order_id>', endpoint='cancel_order', view_func=order_routes.cancel_order)
    app.add_url_rule('/delete_user/<int:user_id>', endpoint='delete_user', view_func=admin_routes.delete_user)
    app.add_url_rule('/edit_user/<int:user_id>', endpoint='edit_user', view_func=admin_routes.edit_user, methods=['GET', 'POST'])
    app.add_url_rule('/reject_order/<int:order_id>', endpoint='reject_order', view_func=admin_routes.reject_order)
    app.add_url_rule('/delete_order/<int:order_id>', endpoint='delete_order', view_func=admin_routes.delete_order)
    app.add_url_rule('/data_screen', endpoint='data_screen', view_func=admin_routes.data_screen)
    app.add_url_rule('/edit_department/<int:dept_id>', endpoint='edit_department', view_func=admin_routes.edit_department, methods=['GET', 'POST'])
    # 逻辑搬运：请求结束自动关闭数据库

    @app.teardown_appcontext
    def close_connection(exception):
        db = getattr(g, '_database', None)
        if db is not None:
            db.close()

    return app