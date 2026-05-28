# app.py
import os
from datetime import datetime, timedelta

from flask import Flask, render_template, redirect, url_for, session, request
from flask_login import LoginManager, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from logging.handlers import RotatingFileHandler
import logging

# ---------- 创建应用 ----------
app = Flask(__name__, instance_relative_config=True)

# 加载默认配置
app.config.from_object('config.Config')

# 尝试从 instance 文件夹加载覆盖配置（如密钥、本地数据库密码等），失败不报错
app.config.from_pyfile('config.py', silent=True)

# ---------- 日志配置 ----------
def setup_logging(app):
    app.logger.handlers.clear()

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'app.log')

    # 文件日志：按大小滚动，保留10个备份
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=10, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    ))
    file_handler.setLevel(logging.DEBUG if app.config.get('DEBUG') else logging.INFO)

    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)

    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)

setup_logging(app)

# ---------- 数据库初始化 ----------
from models import db
db.init_app(app)

# ---------- 登录管理器 ----------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'       # 未登录跳转的视图
login_manager.login_message = '请先登录系统'
login_manager.session_protection = "strong"

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return db.session.get(User, int(user_id))

# ---------- 蓝图注册 ----------
# 必须在导入蓝图之前完成 db 和 login_manager 的初始化，避免循环引用
from auth import auth_bp
from admin import admin_bp
from chat import chat_bp

app.register_blueprint(auth_bp)                # 登录/登出/修改密码/验证码
app.register_blueprint(admin_bp, url_prefix='/admin')   # 系统设置/用户管理/数据库设置
app.register_blueprint(chat_bp, url_prefix='/chat')     # 问答页面

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('chat.chat_page'))
    else:
        return redirect(url_for('auth.login'))

# ---------- 全局请求钩子 ----------
@app.before_request
def check_session_timeout():
    """检查会话是否超时，若超时则自动登出并跳转到登录页"""
    # 跳过登录页面、验证码和静态资源
    if request.endpoint in ('auth.login', 'auth.captcha', 'auth.logout', 'static'):
        return

    # 确保用户已登录（flask_login 会处理未登录情况，但这里检查超时）
    if current_user.is_authenticated:
        now = datetime.utcnow()
        last_active = session.get('last_active')

        if last_active:
            # 将字符串转为 datetime
            last_active_time = datetime.fromisoformat(last_active)
            timeout_seconds = app.config.get('PERMANENT_SESSION_LIFETIME', 3600)
            if (now - last_active_time).total_seconds() > timeout_seconds:
                app.logger.info(f"用户 {current_user.username} 会话超时，强制登出")
                logout_user()
                session.clear()
                return redirect(url_for('auth.login', next=request.url))

        # 更新最后活跃时间
        session['last_active'] = now.isoformat()

# ---------- 错误处理 ----------
@app.errorhandler(404)
def not_found_error(error):
    app.logger.warning(f"404 错误：{request.url}")
    return render_template('error.html', error='页面未找到'), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"500 错误：{str(error)}")
    # 确保数据库回滚，避免锁表
    db.session.rollback()
    return render_template('error.html', error='服务器内部错误，请稍后重试'), 500

# ---------- 启动前创建表 ----------
with app.app_context():
    # 导入所有模型，确保它们在 create_all 之前被注册
    import models
    db.create_all()
    app.logger.info("数据库表已就绪")
    # 自动创建默认管理员（仅当用户表为空时）
    from models import User

    if User.query.count() == 0:
        admin = User(username='admin', role='admin', is_active=True)
        admin.set_password('admin123')  # 请修改为强密码
        db.session.add(admin)
        db.session.commit()
        app.logger.info("默认管理员已创建: admin / admin123")
    else:
        app.logger.info("用户表已有数据，跳过初始化")

# ---------- 应用入口 ----------
if __name__ == '__main__':
    app.run(
        debug=app.config.get('DEBUG', False),
        host=app.config.get('HOST', '0.0.0.0'),
        port=app.config.get('PORT', 8081)
    )