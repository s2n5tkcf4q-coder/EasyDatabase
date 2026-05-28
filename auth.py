# auth.py
import random
import string
import io
from datetime import datetime

from flask import (
    Blueprint, render_template, redirect, url_for, request,
    session, flash, send_file, make_response
)
from flask_login import login_user, logout_user, login_required, current_user
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from models import db, User, SystemLog

auth_bp = Blueprint('auth', __name__)


# ---------- 验证码生成 ----------
def generate_captcha():
    """生成验证码图片和对应文本，文本存入 session，返回图片对象"""
    # 随机生成 4 位数字和大写字母组合
    chars = string.digits
    code = ''.join(random.choices(chars, k=4))
    session['captcha'] = code.upper()

    # 图片尺寸
    width, height = 120, 50
    image = Image.new('RGB', (width, height), color=(255, 255, 255))

    draw = ImageDraw.Draw(image)

    # 尝试加载字体（如果系统有），否则使用默认
    try:
        font = ImageFont.truetype('arial.ttf', 36)
    except IOError:
        font = ImageFont.load_default()

    # 绘制文字
    for i, ch in enumerate(code):
        x = 10 + i * 25
        y = random.randint(2, 8)
        draw.text((x, y), ch, font=font, fill=(random.randint(0, 128), random.randint(0, 128), random.randint(0, 128)))

    # 添加干扰线和噪点
    for _ in range(random.randint(3, 6)):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=(random.randint(0, 128), random.randint(0, 128), random.randint(0, 128)))

    for _ in range(100):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(0, 128), random.randint(0, 128), random.randint(0, 128)))

    # 模糊滤镜
    image = image.filter(ImageFilter.BLUR)

    return image


# ---------- 路由 ----------
@auth_bp.route('/captcha')
def captcha():
    """返回验证码图片"""
    img = generate_captcha()
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    response = make_response(send_file(buf, mimetype='image/png'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return response


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    # 如果用户已登录，直接重定向到问答页面
    if current_user.is_authenticated:
        return redirect(url_for('chat.chat_page'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        captcha_input = request.form.get('captcha', '').strip().upper()

        # 验证码校验
        if 'captcha' not in session or captcha_input != session.get('captcha'):
            flash('验证码错误或已过期', 'danger')
            return render_template('login.html')

        # 清除验证码，避免重用
        session.pop('captcha', None)

        # 用户验证
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=True)
            session['last_active'] = datetime.utcnow().isoformat()

            # 更新最后登录时间
            user.last_login = datetime.utcnow()
            db.session.commit()

            # 记录日志
            SystemLog.add_log(
                user_id=user.id,
                action='login',
                details={'username': username},
                success=True,
                ip_address=request.remote_addr
            )

            flash(f'欢迎回来，{username}！', 'success')

            # 根据角色跳转：管理员到管理页，普通用户到问答页
            if user.role == 'admin':
                return redirect(url_for('admin.settings'))
            else:
                return redirect(url_for('chat.chat_page'))
        else:
            flash('用户名或密码错误，或账户已被禁用', 'danger')
            # 记录失败日志
            if user:
                SystemLog.add_log(
                    user_id=user.id,
                    action='login_failed',
                    details={'username': username, 'reason': 'wrong_password_or_disabled'},
                    success=False,
                    ip_address=request.remote_addr
                )
            else:
                SystemLog.add_log(
                    user_id=None,
                    action='login_failed',
                    details={'username': username, 'reason': 'user_not_found'},
                    success=False,
                    ip_address=request.remote_addr
                )

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """登出"""
    uid = current_user.id
    username = current_user.username
    logout_user()
    session.clear()
    flash('您已成功退出系统', 'info')
    SystemLog.add_log(
        user_id=uid,
        action='logout',
        details={'username': username},
        success=True,
        ip_address=request.remote_addr
    )
    return redirect(url_for('auth.login'))


@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码"""
    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        user = current_user

        # 验证旧密码
        if not user.check_password(old_password):
            flash('旧密码不正确', 'danger')
            return redirect(url_for('auth.change_password'))

        # 验证新密码一致性
        if new_password != confirm_password:
            flash('两次输入的新密码不一致', 'danger')
            return redirect(url_for('auth.change_password'))

        # 密码强度简单检查（至少6位）
        if len(new_password) < 6:
            flash('新密码长度至少6位', 'danger')
            return redirect(url_for('auth.change_password'))

        # 更新密码
        user.set_password(new_password)
        db.session.commit()

        # 记录日志
        SystemLog.add_log(
            user_id=user.id,
            action='change_password',
            details={'username': user.username},
            success=True,
            ip_address=request.remote_addr
        )

        flash('密码修改成功，下次请使用新密码登录', 'success')
        return redirect(url_for('chat.chat_page'))

    return render_template('change_password.html')