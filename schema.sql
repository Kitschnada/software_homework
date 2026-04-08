-- Active: 1771783827639@@127.0.0.1@3306
/* 吴健雄学院融媒体中心工单系统 - 数据库结构
支持五级权限隔离：系统管理员、融媒体管理员、一般管理员、成员、一般用户 
*/

-- 1. 清理旧表（注意删除顺序以符合外键依赖）
DROP TABLE IF EXISTS assignments;

DROP TABLE IF EXISTS acceptor_hours;

DROP TABLE IF EXISTS work_orders;

DROP TABLE IF EXISTS categories;

DROP TABLE IF EXISTS users;

DROP TABLE IF EXISTS departments;

-- 2. 部门表：增加 code 字段以支持权限逻辑识别
CREATE TABLE departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL, -- 部门全称
    code TEXT UNIQUE NOT NULL -- 部门唯一代码（如: MEDIA, SEU, WJX）
    head_name TEXT, -- 部门负责人 (后期新增)
    phone TEXT, -- 负责人联系电话 (后期新增)
    qq TEXT -- 负责人QQ号 (后期新增)
);

-- 3. 用户表：整合权限角色与部门归属
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT UNIQUE NOT NULL, -- 1. 唯一识别码 (系统自动生成，如 MEDIA2026001)
    card_id TEXT UNIQUE NOT NULL, -- 2. 一卡通号
    real_name TEXT NOT NULL, -- 真实姓名
    phone TEXT UNIQUE NOT NULL, -- 3. 手机号
    nickname TEXT UNIQUE, -- 4. 昵称 (允许为空)
    password TEXT NOT NULL, -- 存储哈希后的密码
    role TEXT NOT NULL CHECK (
        role IN (
            'applicant',
            'acceptor',
            'admin',
            'dept_admin'
        )
    ),
    department_id INTEGER, -- 部门管理员和普通用户均需关联部门
    is_approved INTEGER DEFAULT 0, -- 0: 未审核, 1: 已审核
    qq_number TEXT UNIQUE, -- 绑定的 QQ 号
    FOREIGN KEY (department_id) REFERENCES departments (id) ON DELETE SET NULL
);

-- 4. 工单分类表
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL -- 视频制作、海报设计等
);

-- 5. 工单主表：增加级联删除以支持系统管理员的清理操作
CREATE TABLE work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    applicant_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    department_id INTEGER, -- 记录发起部门，用于管理员视野分层
    contact TEXT NOT NULL, -- 联系方式
    deadline DATE NOT NULL, -- 截止日期
    requirements TEXT NOT NULL, -- 需求描述
    attachment_path TEXT, -- 附件文件名
    max_acceptors INTEGER DEFAULT 1, -- 可接单人数（默认1人）
    status TEXT DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'accepted',
            'completed',
            'rejected'
        )
    ),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    rating INTEGER, -- 满意度评价 (1-5)
    comment TEXT, -- 评价内容
    FOREIGN KEY (applicant_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories (id),
    FOREIGN KEY (department_id) REFERENCES departments (id) ON DELETE SET NULL
);

-- 6. 任务分配表：记录受理人（成员账户）的任务进度
CREATE TABLE assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_id INTEGER NOT NULL,
    acceptor_id INTEGER NOT NULL,
    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    result_path TEXT, -- 成果文件路径
    completed_at TIMESTAMP,
    volunteer_hours REAL DEFAULT 0, -- 志愿时长（小时）
    FOREIGN KEY (work_order_id) REFERENCES work_orders (id) ON DELETE CASCADE,
    FOREIGN KEY (acceptor_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 7. 接单员工时表：独立记录每位接单员的累计志愿时长
CREATE TABLE acceptor_hours (
    acceptor_id INTEGER PRIMARY KEY,
    total_hours REAL DEFAULT 0, -- 累计志愿时长（小时），上限30
    FOREIGN KEY (acceptor_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 8. QQ 通知队列表：服务器存入，本地机器人轮询拉取
CREATE TABLE qq_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL, -- 要发送的消息内容
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent INTEGER DEFAULT 0, -- 0: 待发送, 1: 已发送
    work_order_id INTEGER
);

-- 9. QQ 订阅通知表：本地机器人触发群成员订阅事件
CREATE TABLE qq_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qq_number TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories (id),
    UNIQUE (qq_number, category_id)
);

CREATE TABLE qq_message_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,
    work_order_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);