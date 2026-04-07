from flask import render_template, request, redirect, url_for, session, flash
from app.services.auth_service import AuthService
from app.db import get_db
def login():
    if request.method == 'POST':
        # 这里的 identifier 可以是 UID, 一卡通, 手机号, 昵称
        identifier = request.form['identifier']
        password = request.form['password']
        
        user = AuthService.authenticate_user(identifier, password)
        
        if user == "pending":
            flash('账号审核中，请稍后尝试。')
        elif user:
            session.clear()
            session['user_id'] = user['id']
            session['uid'] = user['uid']         # 存入 UID
            session['username'] = user['nickname'] if user['nickname'] else user['real_name']
            session['role'] = user['role']
            
            flash(f'欢迎回来，{session["username"]}')
            return redirect(url_for('dashboard'))
        else:
            flash('账号或密码错误')
            
    return render_template('login.html')

def register():
    if request.method == 'POST':
        # 收集新字段
        form_data = {
            'card_id': request.form['card_id'],
            'real_name': request.form['real_name'],
            'phone': request.form['phone'],
            'role': request.form['role'],
            'department_id': request.form.get('department_id'),
            'password': request.form['password']
        }
        
        success, msg = AuthService.register_user(form_data)
        flash(msg)
        if success:
            return redirect(url_for('login'))
            
    departments = get_db().execute('SELECT * FROM departments').fetchall()
    return render_template('register.html', departments=departments)


def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    role = session['role']
    if role == 'applicant':
        return redirect(url_for('applicant_dashboard'))
    elif role == 'acceptor':
        return redirect(url_for('acceptor_dashboard'))
    elif role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif role == 'dept_admin':
        return redirect(url_for('manage_users'))
    return redirect(url_for('logout'))    
    # 这里后面需要补充一个逻辑，就是融媒体中心管理员会拥有一个比其它部门管理员更高一点的逻辑权限，
    # if 'user_id' not in session: return redirect(url_for('login'))
    # role, code = session['role'], session.get('dept_code')
    # if role == 'admin' or (role == 'dept_admin' and code == 'MEDIA'): return redirect(url_for('admin_dashboard'))
    # mapping = {'dept_admin': 'manage_users', 'acceptor': 'acceptor_dashboard', 'applicant': 'applicant_dashboard'}
    # return redirect(url_for(mapping.get(role, 'logout')))

def logout():
    session.clear()
    return redirect(url_for('login'))

def profile():
    """个人信息维护：展示只读信息，修改可变信息"""
    if 'user_id' not in session: return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if request.method == 'POST':
        # 获取表单数据
        nickname = request.form.get('nickname', '').strip()
        phone = request.form.get('phone', '').strip()
        new_password = request.form.get('new_password', '').strip()
        
        # 调用 Service 更新
        success, msg = AuthService.update_profile(user_id, nickname, phone, new_password)
        flash(msg)
        
        if success:
            # 实时更新 Session 中的显示名称
            user_info = AuthService.get_user_profile(user_id)
            session['username'] = user_info['nickname'] if user_info['nickname'] else user_info['real_name']
            # 保持在当前页面
            return redirect(url_for('profile'))
            
    # GET 请求：获取完整用户信息用于回显
    user = AuthService.get_user_profile(user_id)
    return render_template('profile.html', user=user)