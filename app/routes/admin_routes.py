from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from app.services.admin_service import AdminService
from app.db import get_db
from werkzeug.security import generate_password_hash
from app.services.order_service import OrderService
import json
import os

# 创建蓝图
admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/dashboard')
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
    
    stats = AdminService.get_system_stats() if (role == 'admin' or is_media_admin) else None
    departments = get_db().execute('SELECT * FROM departments').fetchall()
    upcoming_tasks = AdminService.get_upcoming_tasks() if (role == 'admin' or is_media_admin) else []
    
    return render_template('admin.html', 
                           orders=orders, 
                           stats=stats, 
                           is_media_admin=is_media_admin, 
                           departments=departments,
                           upcoming_tasks=upcoming_tasks)

@admin_bp.route('/create_department', methods=['POST'])
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

@admin_bp.route('/delete_department/<int:dept_id>', methods=['POST'])
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

@admin_bp.route('/approve_user_route/<int:user_id>', methods=['POST'])
def approve_user_route(user_id):
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    success, msg = AdminService.approve_user(session['user_id'], session['role'], user_id)
    flash(msg)
    return redirect(url_for('manage_users'))

@admin_bp.route('/manage_users')
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

@admin_bp.route('/create_user', methods=['POST'])
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

@admin_bp.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    """【修复】调用 Service 进行安全删除"""
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    
    success, msg = AdminService.delete_user(session['user_id'], session['role'], user_id)
    flash(msg)
    return redirect(url_for('manage_users'))

@admin_bp.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
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
            'qq_number': request.form.get('qq_number', ''),
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

@admin_bp.route('/delete_order/<int:order_id>', methods=['POST'])
def delete_order(order_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    AdminService.purge_order(order_id, current_app.config['UPLOAD_FOLDER'], current_app.config['RESULT_FOLDER'])
    flash('物理删除成功')
    return redirect(url_for('admin_dashboard'))

@admin_bp.route('/reject_order/<int:order_id>', methods=['POST'])
def reject_order(order_id):
    if session.get('role') not in ['admin', 'dept_admin']: return redirect(url_for('login'))
    db = get_db()
    db.execute('UPDATE work_orders SET status = "rejected" WHERE id = ?', (order_id,))
    db.commit()
    flash('工单已驳回')
    return redirect(url_for('admin_dashboard'))

@admin_bp.route('/data_screen')
def data_screen():
    """数据可视化大屏路由"""
    # 允许所有登录用户观看，或者您可以限制为仅 admin
    if 'user_id' not in session: return redirect(url_for('login'))
    
    data = AdminService.get_data_screen_stats()
    return render_template('data_screen.html', data=data)

@admin_bp.route('/edit_department/<int:dept_id>', methods=['GET', 'POST'])
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

@admin_bp.route('/edit_volunteer_hours/<int:assignment_id>', methods=['GET', 'POST'])
def edit_volunteer_hours(assignment_id):
    """
    编辑志愿时长的路由。
    :param assignment_id: 任务分配的 ID
    """
    db = get_db()

    if request.method == 'POST':
        new_hours = float(request.form['volunteer_hours'])
        if new_hours < 0 or new_hours > 30:
            flash('志愿时长必须在 0 到 30 小时之间！')
            return redirect(url_for('admin_dashboard'))

        # 更新志愿时长
        db.execute('UPDATE assignments SET volunteer_hours = ? WHERE id = ?', (new_hours, assignment_id))
        db.commit()
        flash('志愿时长已成功更新！')
        return redirect(url_for('admin_dashboard'))

    # 获取当前志愿时长
    assignment = db.execute('SELECT volunteer_hours FROM assignments WHERE id = ?', (assignment_id,)).fetchone()
    if not assignment:
        flash('未找到对应的任务分配记录！')
        return redirect(url_for('admin_dashboard'))

    return render_template('edit_volunteer_hours.html', assignment_id=assignment_id, current_hours=assignment['volunteer_hours'])

@admin_bp.route('/complete_order/<int:order_id>', methods=['POST'])
def complete_order(order_id):
    """
    接单员完成任务后，分配志愿时长。
    """
    if session.get('role') != 'acceptor':
        return redirect(url_for('login'))

    db = get_db()

    # 获取任务信息
    order = db.execute(
        'SELECT a.id as assignment_id, c.name as category_name '
        'FROM work_orders w '
        'JOIN assignments a ON w.id = a.work_order_id '
        'JOIN categories c ON w.category_id = c.id '
        'WHERE w.id = ? AND a.acceptor_id = ?',
        (order_id, session['user_id'])
    ).fetchone()

    if not order:
        flash('任务不存在或您无权完成此任务。')
        return redirect(url_for('acceptor_dashboard'))

    # 更新任务状态为已完成
    db.execute(
        'UPDATE work_orders SET status = "completed" WHERE id = ?',
        (order_id,)
    )

    # 分配志愿时长
    try:
        OrderService.assign_volunteer_hours(order['assignment_id'], order['category_name'])
        flash('任务已完成，志愿时长已分配！')
    except Exception as e:
        flash(f'任务完成，但分配志愿时长失败：{str(e)}')

    db.commit()
    return redirect(url_for('acceptor_dashboard'))

@admin_bp.route('/manage_hours')
def manage_volunteer_hours():
    """工时管理页面：列出所有接单员及其志愿工时"""
    if session.get('role') != 'admin': return redirect(url_for('login'))
    acceptors = AdminService.get_all_acceptor_hours()
    return render_template('manage_hours.html', acceptors=acceptors)

@admin_bp.route('/set_hours', methods=['POST'])
def set_volunteer_hours():
    """管理员直接设置接单员工时"""
    if session.get('role') != 'admin': return redirect(url_for('login'))
    acceptor_id = request.form.get('acceptor_id', type=int)
    hours = request.form.get('hours', type=float, default=0)
    success, msg = AdminService.admin_set_volunteer_hours(acceptor_id, hours)
    flash(msg)
    return redirect(url_for('manage_volunteer_hours'))

@admin_bp.route('/update_max_acceptors', methods=['POST'])
def update_max_acceptors():
    """管理员修改工单可接单人数"""
    role = session.get('role')
    if role not in ('admin', 'dept_admin'):
        return redirect(url_for('login'))
    if role == 'dept_admin' and session.get('dept_code') != 'MEDIA':
        flash('权限不足')
        return redirect(url_for('admin_dashboard'))
    
    order_id = request.form.get('order_id', type=int)
    max_acc = request.form.get('max_acceptors', type=int, default=1)
    if max_acc < 1: max_acc = 1
    if max_acc > 10: max_acc = 10
    
    db = get_db()
    order = db.execute('SELECT status FROM work_orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        flash('工单不存在')
        return redirect(url_for('admin_dashboard'))
    
    # 已完成和已驳回的工单不允许修改人数
    if order['status'] in ('completed', 'rejected'):
        flash('已完成或已驳回的工单无法修改接单人数')
        return redirect(url_for('admin_dashboard'))
    
    # 获取当前接单人数
    current = db.execute('SELECT COUNT(*) FROM assignments WHERE work_order_id = ?', (order_id,)).fetchone()[0]
    
    # 如果新人数 < 当前已接单人数，自动取消最后接单的人
    if max_acc < current:
        excess = current - max_acc
        # 按接单时间倒序，取消最后 N 个
        excess_assignments = db.execute('''
            SELECT id FROM assignments WHERE work_order_id = ?
            ORDER BY accepted_at DESC LIMIT ?
        ''', (order_id, excess)).fetchall()
        for a in excess_assignments:
            db.execute('DELETE FROM assignments WHERE id = ?', (a['id'],))
    
    db.execute('UPDATE work_orders SET max_acceptors = ? WHERE id = ?', (max_acc, order_id))
    
    # 重新计算接单人数并更新状态
    new_current = db.execute('SELECT COUNT(*) FROM assignments WHERE work_order_id = ?', (order_id,)).fetchone()[0]
    if new_current >= max_acc:
        db.execute('UPDATE work_orders SET status = "accepted" WHERE id = ?', (order_id,))
    else:
        db.execute('UPDATE work_orders SET status = "pending" WHERE id = ?', (order_id,))
    
    db.commit()
    if max_acc < current:
        flash(f'工单 #{order_id} 人数已调整为 {max_acc}，已自动取消 {current - max_acc} 位接单者')
    else:
        flash(f'工单 #{order_id} 接单人数已更新为 {max_acc}')
    return redirect(url_for('admin_dashboard'))

@admin_bp.route('/test_qq_bot', methods=['POST'])
def test_qq_bot():
    """管理员发送测试通知到队列"""
    if session.get('role') != 'admin': return redirect(url_for('login'))
    from app.services.qq_notify import send_test_notification
    success, msg = send_test_notification()
    flash(msg)
    return redirect(url_for('admin_dashboard'))

# ============================================================
# QQ 机器人通知拉取 API（供本地 qq_worker.py 调用）
# ============================================================

from flask import jsonify

@admin_bp.route('/api/notifications', methods=['GET'])
def api_get_notifications():
    """本地机器人拉取待发送通知（需 Token 鉴权）"""
    from app.routes.bot_routes import verify_token
    if not verify_token():
        return jsonify({'error': 'Unauthorized'}), 401
    
    from app.services.qq_notify import get_pending_notifications
    notifications = get_pending_notifications()
    return jsonify({'notifications': notifications})

@admin_bp.route('/api/notifications/mark_sent', methods=['POST'])
def api_mark_sent():
    """本地机器人标记通知已发送（需 Token 鉴权）"""
    from app.routes.bot_routes import verify_token
    if not verify_token():
        return jsonify({'error': 'Unauthorized'}), 401
    
    items = request.json.get('items', [])
    if items:
        from app.services.qq_notify import mark_notifications_sent
        mark_notifications_sent(items)
    return jsonify({'status': 'ok', 'marked': len(items)})

@admin_bp.route('/bot_settings', methods=['GET', 'POST'])
def bot_settings():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    settings_file = current_app.config.get('BOT_SETTINGS_FILE')
    
    if request.method == 'POST':
        data = {
            "qq_bot_token": request.form.get('qq_bot_token', '')
        }
        try:
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            flash("API 鉴权令牌配置更新成功！")
        except Exception as e:
            flash(f"保存配置失败: {str(e)}")
        return redirect(url_for('admin.bot_settings'))
        
    # GET 请求
    settings = {}
    if settings_file and os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except:
            pass
            
    return render_template('admin_bot_config.html', settings=settings)

@admin_bp.route('/volunteer_hours_settings', methods=['GET', 'POST'])
def volunteer_hours_settings():
    """管理全局默认志愿时长配置"""
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        total = int(request.form.get('total_categories', 0))
        new_mapping = {}
        for i in range(total):
            cat = request.form.get(f'category_{i}')
            hours_str = request.form.get(f'hours_{i}')
            if cat and hours_str:
                try:
                    new_mapping[cat] = float(hours_str)
                except ValueError:
                    pass
        
        try:
            OrderService.set_hours_mapping(new_mapping)
            flash("默认志愿时长配置更新成功！即将生效。")
        except Exception as e:
            flash(f"保存配置失败: {str(e)}")
            
        return redirect(url_for('admin.volunteer_hours_settings'))
        
    # GET 请求：读取当前配置
    mapping = OrderService.get_hours_mapping()
    return render_template('admin_hours_config.html', mapping=mapping)