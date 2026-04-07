from flask import render_template, request, redirect, url_for, session, flash, current_app
from app.services.admin_service import AdminService
from app.db import get_db
from werkzeug.security import generate_password_hash

def admin_dashboard():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['admin', 'dept_admin']:
        return redirect(url_for('login'))

    user_info, is_media_admin = AdminService.get_admin_context(user_id, role)
    
    # 接收筛选参数
    q = request.args.get('q', '').strip()
    filter_dept = request.args.get('filter_dept', '')
    
    orders = AdminService.get_visible_orders(user_id, role, q, filter_dept)
    
    stats = AdminService.get_system_stats() if role == 'admin' else None
    departments = get_db().execute('SELECT * FROM departments').fetchall()
    upcoming_tasks = AdminService.get_upcoming_tasks() if role == 'admin' else []
    
    return render_template('admin.html', 
                           orders=orders, 
                           stats=stats, 
                           is_media_admin=is_media_admin, 
                           departments=departments,
                           upcoming_tasks=upcoming_tasks)

def create_department():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    success, msg = AdminService.setup_new_department(
        request.form['name'], 
        request.form['code'],
        request.form.get('head_name', ''),
        request.form.get('phone', ''),
        request.form.get('qq', '')
    )
    flash(msg)
    return redirect(url_for('admin_dashboard'))

def delete_department(dept_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    db = get_db()
    dept = db.execute('SELECT code FROM departments WHERE id = ?', (dept_id,)).fetchone()
    if dept and dept['code'] == 'MEDIA':
        flash('无法删除核心部门')
    else:
        # 级联删除：部门下的用户也会被删
        db.execute('DELETE FROM users WHERE department_id = ?', (dept_id,))
        db.execute('DELETE FROM departments WHERE id = ?', (dept_id,))
        db.commit()
        flash('部门及其用户已删除')
    return redirect(url_for('admin_dashboard'))

def approve_user_route(user_id):
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    success, msg = AdminService.approve_user(session['user_id'], session['role'], user_id)
    flash(msg)
    return redirect(url_for('manage_users'))

def manage_users():
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    
    # 接收筛选参数
    q = request.args.get('q', '').strip()
    filter_dept = request.args.get('filter_dept', '')
    filter_role = request.args.get('filter_role', '')
    
    active_users = AdminService.get_manageable_users(session['user_id'], session['role'], q, filter_dept, filter_role)
    pending_users = AdminService.get_pending_users(session['user_id'], session['role'], q, filter_dept, filter_role)
    
    depts = get_db().execute('SELECT * FROM departments').fetchall()
    return render_template('manage_users.html', users=active_users, pending_users=pending_users, departments=depts)

def create_user():
    """手动创建用户：使用新逻辑"""
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    db = get_db()

    # 1. 接收新字段
    real_name = request.form['real_name']
    card_id = request.form['card_id']
    phone = request.form['phone']
    password = request.form['password']
    role = request.form['role']
    dept_id = request.form.get('department_id')
    
    # 2. 部门管理员权限锁定
    if session['role'] == 'dept_admin':
        current_admin = db.execute('SELECT department_id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        dept_id = current_admin['department_id']
        if role in ['admin', 'dept_admin']:
            flash('权限不足：无法创建管理账户')
            return redirect(url_for('manage_users'))

    # 3. 自动生成 UID
    uid = AdminService.generate_unique_id(dept_id)
    if not uid:
        flash('UID生成失败，请检查部门配置')
        return redirect(url_for('manage_users'))

    try:
        # 4. 免审入库 (is_approved=1)
        db.execute('''
            INSERT INTO users (uid, password, card_id, real_name, phone, role, department_id, is_approved) 
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ''', (uid, generate_password_hash(password), card_id, real_name, phone, role, dept_id))
        
        db.commit()
        flash(f'用户 {real_name} 添加成功！UID: {uid}')
    except Exception as e:
        flash(f'添加失败：一卡通或手机号已存在 ({str(e)})')
        
    return redirect(url_for('manage_users'))

def delete_user(user_id):
    """【修复】调用 Service 进行安全删除"""
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    
    success, msg = AdminService.delete_user(session['user_id'], session['role'], user_id)
    flash(msg)
    return redirect(url_for('manage_users'))

def edit_user(user_id):
    """【重构】管理员全权编辑用户信息"""
    if session.get('role') not in ['admin', 'dept_admin']: 
        return redirect(url_for('login'))
    
    # 1. POST 请求：提交修改
    if request.method == 'POST':
        # 收集表单数据
        form_data = {
            'real_name': request.form['real_name'],
            'card_id': request.form['card_id'],
            'phone': request.form['phone'],
            'nickname': request.form.get('nickname'), # 允许为空
            'role': request.form['role'],
            'department_id': request.form['department_id'],
            'password': request.form.get('password')  # 允许为空
        }
        
        # 调用 Service 进行更新 (含权限校验)
        success, msg = AdminService.update_user_details(
            session['user_id'], 
            session['role'], 
            user_id, 
            form_data
        )
        
        flash(msg)
        if success:
            return redirect(url_for('manage_users'))
        # 如果失败，停留在当前页面以便修正（下面会继续执行渲染 GET）

    # 2. GET 请求：获取数据回显
    # 复用 Service 中的获取逻辑，确保拿到 dept_name
    user_info = AdminService.get_user_for_edit(user_id)
    if not user_info:
        flash('用户不存在')
        return redirect(url_for('manage_users'))
        
    depts = get_db().execute('SELECT * FROM departments').fetchall()
    return render_template('edit_user.html', user=user_info, departments=depts)

def delete_order(order_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    AdminService.purge_order(order_id, current_app.config['UPLOAD_FOLDER'], current_app.config['RESULT_FOLDER'])
    flash('物理删除成功')
    return redirect(url_for('admin_dashboard'))

def reject_order(order_id):
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    db = get_db()
    db.execute('UPDATE work_orders SET status = "rejected" WHERE id = ?', (order_id,))
    db.commit()
    flash('工单已驳回')
    return redirect(url_for('admin_dashboard'))

def data_screen():
    """数据可视化大屏路由"""
    # 允许所有登录用户观看，或者您可以限制为仅 admin
    if 'user_id' not in session: return redirect(url_for('login'))
    
    data = AdminService.get_data_screen_stats()
    return render_template('data_screen.html', data=data)

def edit_department(dept_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    db = get_db()
    
    if request.method == 'POST':
        success, msg = AdminService.update_department(
            dept_id,
            request.form['name'],
            request.form['code'],
            request.form.get('head_name', ''),
            request.form.get('phone', ''),
            request.form.get('qq', '')
        )
        flash(msg)
        if success:
            return redirect(url_for('admin_dashboard'))
            
    # GET 请求：回显数据
    dept = db.execute('SELECT * FROM departments WHERE id = ?', (dept_id,)).fetchone()
    if not dept:
        flash("部门不存在")
        return redirect(url_for('admin_dashboard'))
    return render_template('edit_department.html', dept=dept)