from flask import render_template, request, redirect, url_for, session, flash, current_app
from app.services.order_service import OrderService
from app.db import get_db

# =========================================================
# 申请者模块 (Applicant)
# =========================================================

def applicant_dashboard():
    if session.get('role') != 'applicant': return redirect(url_for('login'))
    
    # 调用 Service 获取数据
    orders, dept_orders = OrderService.get_applicant_data(session['user_id'])
    categories = get_db().execute('SELECT * FROM categories').fetchall()
    
    return render_template('applicant.html', orders=orders, dept_orders=dept_orders, categories=categories)

def create_order():
    if session.get('role') != 'applicant': return redirect(url_for('login'))
    
    if request.method == 'POST':
        # 调用 Service 处理创建逻辑
        success, msg = OrderService.create_order(
            session['user_id'], 
            request.form, 
            request.files.get('attachment')
        )
        flash(msg)
        
    return redirect(url_for('applicant_dashboard'))

def edit_order(order_id):
    if session.get('role') != 'applicant': return redirect(url_for('login'))
    
    # POST: 提交修改
    if request.method == 'POST':
        success, msg = OrderService.edit_order(
            order_id, 
            session['user_id'], 
            request.form, 
            request.files.get('attachment')
        )
        flash(msg)
        return redirect(url_for('applicant_dashboard'))
    
    # GET: 获取工单详情渲染页面
    order = OrderService.get_order_by_id(order_id)
    if not order:
        flash('工单不存在')
        return redirect(url_for('applicant_dashboard'))
        
    return render_template('edit_order.html', order=order)

def cancel_order(order_id):
    if session.get('role') != 'applicant': return redirect(url_for('login'))
    if request.method != 'POST': return redirect(url_for('applicant_dashboard'))
    
    success, msg = OrderService.cancel_order(order_id, session['user_id'])
    flash(msg)
    return redirect(url_for('applicant_dashboard'))

def rate_order(order_id):
    if session.get('role') != 'applicant': return redirect(url_for('login'))
    
    if request.method == 'POST':
        success, msg = OrderService.rate_order(
            order_id, 
            session['user_id'], 
            request.form.get('rating'), 
            request.form.get('comment')
        )
        flash(msg)
    return redirect(url_for('applicant_dashboard'))

# =========================================================
# 接单者模块 (Acceptor)
# =========================================================

def acceptor_dashboard():
    if session.get('role') != 'acceptor': return redirect(url_for('login'))
    
    available, my_tasks = OrderService.get_acceptor_view_data(session['user_id'])
    total_hours = OrderService.get_acceptor_total_hours(session['user_id'])
    return render_template('acceptor.html', available_orders=available, my_orders=my_tasks, total_hours=total_hours)

def accept_order(order_id):
    if session.get('role') != 'acceptor': return redirect(url_for('login'))
    if request.method != 'POST': return redirect(url_for('acceptor_dashboard'))
    
    success, msg = OrderService.accept_order(order_id, session['user_id'])
    flash(msg)
    return redirect(url_for('acceptor_dashboard'))

def upload_result(assignment_id):
    if session.get('role') != 'acceptor': return redirect(url_for('login'))
    
    if request.method == 'POST':
        success, msg = OrderService.upload_result(
            assignment_id, 
            session['user_id'], 
            request.files.get('result_file')
        )
        flash(msg)
    return redirect(url_for('acceptor_dashboard'))

def calendar_view():
    """日历排期页面路由"""
    if 'user_id' not in session: return redirect(url_for('login'))
    role = session.get('role')
    
    # 系统管理员不需要看详细日历，直接跳回看板
    if role == 'admin': return redirect(url_for('admin_dashboard'))
    
    # 获取用户部门信息以判定权限边界
    db = get_db()
    user = db.execute('SELECT u.department_id, d.code FROM users u LEFT JOIN departments d ON u.department_id = d.id WHERE u.id = ?', (session['user_id'],)).fetchone()
    
    dept_code = user['code'] if user else None
    dept_id = user['department_id'] if user else None
    
    # 调用刚刚写的服务层拉取数据
    events = OrderService.get_calendar_events(session['user_id'], role, dept_code, dept_id)
    return render_template('calendar.html', events=events)