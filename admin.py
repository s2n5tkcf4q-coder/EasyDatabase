# admin.py
import json
from datetime import datetime

from flask import (
    Blueprint, render_template, redirect, url_for, request,
    flash, jsonify, current_app
)
from flask_login import login_required, current_user
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from models import (
    db, User, SysConfig, DatabaseConnection,
    TableMeta, ColumnMeta, SystemLog, Memory
)
from llm_client import LLMClient
import utils

admin_bp = Blueprint('admin', __name__)


# ---------- 权限装饰器 ----------
def admin_required(f):
    """只允许管理员访问的装饰器"""
    @login_required
    def decorated_view(*args, **kwargs):
        if current_user.role != 'admin':
            flash('您没有访问此页面的权限', 'danger')
            return redirect(url_for('chat.chat_page'))
        return f(*args, **kwargs)
    decorated_view.__name__ = f.__name__
    return decorated_view


# ---------- 工具函数 ----------
def get_dynamic_config(key, default=None):
    """从数据库获取配置，若不存在则使用 config.py 的默认值"""
    val = SysConfig.get_config(key)
    if val is not None:
        return val
    return current_app.config.get(key, default)


def set_dynamic_config(key, value, description=None):
    SysConfig.set_config(key, value, description)


# ---------- 系统设置 ----------
@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        # 获取表单数据
        llm_mode = request.form.get('llm_mode', 'api')
        api_url = request.form.get('api_url', '')
        api_key = request.form.get('api_key', '')
        api_chat_model = request.form.get('api_chat_model', '')
        api_embedding_model = request.form.get('api_embedding_model', '')
        ollama_base_url = request.form.get('ollama_base_url', '')
        ollama_chat_model = request.form.get('ollama_chat_model', '')
        ollama_embedding_model = request.form.get('ollama_embedding_model', '')
        system_prompt = request.form.get('system_prompt', '')
        similarity_threshold = request.form.get('similarity_threshold', '0.75')
        similarity_weight = request.form.get('similarity_weight', '0.8')
        top_n = request.form.get('top_n', '5')
        temperature = request.form.get('temperature', '0.1')
        top_p = request.form.get('top_p', '0.9')
        presence_penalty = request.form.get('presence_penalty', '0.0')
        frequency_penalty = request.form.get('frequency_penalty', '0.0')
        max_tokens = request.form.get('max_tokens', '2048')
        enable_long_term = 'enable_long_term' in request.form
        short_term_rounds = request.form.get('short_term_rounds', '10')

        # 保存所有配置到数据库
        config_map = {
            'LLM_MODE': llm_mode,
            'LLM_API_URL': api_url,
            'LLM_API_KEY': api_key,
            'LLM_API_CHAT_MODEL': api_chat_model,
            'LLM_API_EMBEDDING_MODEL': api_embedding_model,
            'OLLAMA_BASE_URL': ollama_base_url,
            'OLLAMA_CHAT_MODEL': ollama_chat_model,
            'OLLAMA_EMBEDDING_MODEL': ollama_embedding_model,
            'LLM_SYSTEM_PROMPT': system_prompt,
            'LLM_SIMILARITY_THRESHOLD': similarity_threshold,
            'LLM_SIMILARITY_WEIGHT': similarity_weight,
            'LLM_TOP_N': top_n,
            'LLM_TEMPERATURE': temperature,
            'LLM_TOP_P': top_p,
            'LLM_PRESENCE_PENALTY': presence_penalty,
            'LLM_FREQUENCY_PENALTY': frequency_penalty,
            'LLM_MAX_TOKENS': max_tokens,
            'LLM_ENABLE_LONG_TERM_MEMORY': 'true' if enable_long_term else 'false',
            'LLM_SHORT_TERM_MEMORY_ROUNDS': short_term_rounds,
        }

        for key, val in config_map.items():
            set_dynamic_config(key, val)

        # 记录日志
        SystemLog.add_log(
            user_id=current_user.id,
            action='update_settings',
            details={'updated_keys': list(config_map.keys())},
            success=True,
            ip_address=request.remote_addr
        )

        flash('系统设置已保存', 'success')

        # 处理测试连接请求（通过表单中的 action）
        if 'test_connection' in request.form:
            # 使用刚保存的配置测试
            try:
                client = LLMClient()
                success, message = client.test_connection()
                flash(f'测试结果：{message}', 'success' if success else 'danger')
                SystemLog.add_log(
                    user_id=current_user.id,
                    action='test_llm_connection',
                    details={'result': message},
                    success=success,
                    ip_address=request.remote_addr
                )
            except Exception as e:
                flash(f'测试失败：{str(e)}', 'danger')
                SystemLog.add_log(
                    user_id=current_user.id,
                    action='test_llm_connection',
                    details={'error': str(e)},
                    success=False,
                    ip_address=request.remote_addr
                )

        return redirect(url_for('admin.settings'))

    # GET 请求：从数据库加载当前配置（若无则使用 config 默认值）
    config_data = {
        'llm_mode': get_dynamic_config('LLM_MODE', current_app.config['LLM_MODE']),
        'api_url': get_dynamic_config('LLM_API_URL', current_app.config['LLM_API_URL']),
        'api_key': get_dynamic_config('LLM_API_KEY', current_app.config['LLM_API_KEY']),
        'api_chat_model': get_dynamic_config('LLM_API_CHAT_MODEL', current_app.config['LLM_API_CHAT_MODEL']),
        'api_embedding_model': get_dynamic_config('LLM_API_EMBEDDING_MODEL', current_app.config['LLM_API_EMBEDDING_MODEL']),
        'ollama_base_url': get_dynamic_config('OLLAMA_BASE_URL', current_app.config['OLLAMA_BASE_URL']),
        'ollama_chat_model': get_dynamic_config('OLLAMA_CHAT_MODEL', current_app.config['OLLAMA_CHAT_MODEL']),
        'ollama_embedding_model': get_dynamic_config('OLLAMA_EMBEDDING_MODEL', current_app.config['OLLAMA_EMBEDDING_MODEL']),
        'system_prompt': get_dynamic_config('LLM_SYSTEM_PROMPT', current_app.config['LLM_SYSTEM_PROMPT']),
        'similarity_threshold': get_dynamic_config('LLM_SIMILARITY_THRESHOLD', '0.75'),
        'similarity_weight': get_dynamic_config('LLM_SIMILARITY_WEIGHT', '0.8'),
        'top_n': get_dynamic_config('LLM_TOP_N', '5'),
        'temperature': get_dynamic_config('LLM_TEMPERATURE', '0.1'),
        'top_p': get_dynamic_config('LLM_TOP_P', '0.9'),
        'presence_penalty': get_dynamic_config('LLM_PRESENCE_PENALTY', '0.0'),
        'frequency_penalty': get_dynamic_config('LLM_FREQUENCY_PENALTY', '0.0'),
        'max_tokens': get_dynamic_config('LLM_MAX_TOKENS', '2048'),
        'enable_long_term': get_dynamic_config('LLM_ENABLE_LONG_TERM_MEMORY', 'true') == 'true',
        'short_term_rounds': get_dynamic_config('LLM_SHORT_TERM_MEMORY_ROUNDS', '10'),
    }

    return render_template('admin/settings.html', config=config_data)


# ---------- 用户管理 ----------
@admin_bp.route('/users')
@admin_required
def user_list():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/add', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = 'normal'

    if not username or not password:
        flash('用户名和密码不能为空', 'danger')
        return redirect(url_for('admin.user_list'))

    if User.query.filter_by(username=username).first():
        flash(f'用户 {username} 已存在', 'danger')
        return redirect(url_for('admin.user_list'))

    if len(password) < 6:
        flash('密码长度至少6位', 'danger')
        return redirect(url_for('admin.user_list'))

    new_user = User(username=username, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    SystemLog.add_log(
        user_id=current_user.id,
        action='add_user',
        details={'new_user': username},
        success=True,
        ip_address=request.remote_addr
    )

    flash(f'用户 {username} 创建成功', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/reset_password/<int:user_id>', methods=['POST'])
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()

    if not new_password:
        flash('新密码不能为空', 'danger')
        return redirect(url_for('admin.user_list'))

    if len(new_password) < 6:
        flash('密码长度至少6位', 'danger')
        return redirect(url_for('admin.user_list'))

    user.set_password(new_password)
    db.session.commit()

    SystemLog.add_log(
        user_id=current_user.id,
        action='reset_password',
        details={'target_user': user.username},
        success=True,
        ip_address=request.remote_addr
    )

    flash(f'用户 {user.username} 的密码已重置', 'success')
    return redirect(url_for('admin.user_list'))


# ---------- 数据库连接设置 ----------
@admin_bp.route('/database', methods=['GET', 'POST'])
@admin_required
def database_settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            db_type = request.form.get('db_type', 'mysql')
            host = request.form.get('host', '')
            port = request.form.get('port', 3306)
            database = request.form.get('database', '')
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            extra_params = request.form.get('extra_params', '')

            if not name or not database:
                flash('名称和数据库名不能为空', 'danger')
                return redirect(url_for('admin.database_settings'))

            if DatabaseConnection.query.filter_by(name=name).first():
                flash(f'连接 {name} 已存在', 'danger')
                return redirect(url_for('admin.database_settings'))

            conn = DatabaseConnection(
                name=name,
                db_type=db_type,
                host=host,
                port=int(port),
                database=database,
                username=username,
                password=password,
                extra_params=extra_params
            )
            db.session.add(conn)
            db.session.commit()

            SystemLog.add_log(
                user_id=current_user.id,
                action='add_database_connection',
                details={'name': name},
                success=True,
                ip_address=request.remote_addr
            )
            flash('数据库连接已添加', 'success')

        elif action == 'edit':
            conn_id = request.form.get('conn_id')
            conn = DatabaseConnection.query.get_or_404(conn_id)
            conn.name = request.form.get('name', conn.name).strip()
            conn.db_type = request.form.get('db_type', conn.db_type)
            conn.host = request.form.get('host', conn.host)
            conn.port = int(request.form.get('port', conn.port))
            conn.database = request.form.get('database', conn.database)
            conn.username = request.form.get('username', conn.username)
            conn.password = request.form.get('password', conn.password)
            conn.extra_params = request.form.get('extra_params', conn.extra_params)
            db.session.commit()

            SystemLog.add_log(
                user_id=current_user.id,
                action='edit_database_connection',
                details={'name': conn.name},
                success=True,
                ip_address=request.remote_addr
            )
            flash('数据库连接已更新', 'success')

        elif action == 'delete':
            conn_id = request.form.get('conn_id')
            conn = DatabaseConnection.query.get_or_404(conn_id)
            db.session.delete(conn)
            db.session.commit()

            SystemLog.add_log(
                user_id=current_user.id,
                action='delete_database_connection',
                details={'name': conn.name},
                success=True,
                ip_address=request.remote_addr
            )
            flash('数据库连接已删除', 'success')

        elif action == 'test':
            conn_id = request.form.get('conn_id')
            conn = DatabaseConnection.query.get_or_404(conn_id)
            try:
                engine = create_engine(conn.connection_string)
                with engine.connect() as c:
                    c.execute(text('SELECT 1'))
                flash(f'连接 {conn.name} 测试成功', 'success')
                SystemLog.add_log(
                    user_id=current_user.id,
                    action='test_database_connection',
                    details={'name': conn.name, 'result': 'success'},
                    success=True,
                    ip_address=request.remote_addr
                )
            except Exception as e:
                flash(f'连接失败：{str(e)}', 'danger')
                SystemLog.add_log(
                    user_id=current_user.id,
                    action='test_database_connection',
                    details={'name': conn.name, 'error': str(e)},
                    success=False,
                    ip_address=request.remote_addr
                )

        elif action == 'sync_metadata':
            conn_id = request.form.get('conn_id')
            conn = DatabaseConnection.query.get_or_404(conn_id)
            try:
                utils.sync_metadata(conn)
                flash(f'元数据同步完成', 'success')
                SystemLog.add_log(
                    user_id=current_user.id,
                    action='sync_metadata',
                    details={'name': conn.name},
                    success=True,
                    ip_address=request.remote_addr
                )
            except Exception as e:
                flash(f'同步失败：{str(e)}', 'danger')
                SystemLog.add_log(
                    user_id=current_user.id,
                    action='sync_metadata',
                    details={'name': conn.name, 'error': str(e)},
                    success=False,
                    ip_address=request.remote_addr
                )

        return redirect(url_for('admin.database_settings'))

    connections = DatabaseConnection.query.order_by(DatabaseConnection.created_at.desc()).all()
    return render_template('admin/database.html', connections=connections)


# ---------- 长期记忆管理 ----------
@admin_bp.route('/memories')
@admin_required
def memories():
    """显示所有长期记忆，支持关键词搜索"""
    keyword = request.args.get('keyword', '').strip()
    query = Memory.query
    if keyword:
        query = query.filter(
            db.or_(
                Memory.content.ilike(f'%{keyword}%'),
                Memory.memory_type.ilike(f'%{keyword}%')
            )
        )
    memories = query.order_by(Memory.created_at.desc()).all()
    users = User.query.all()   # 新增：获取所有用户供下拉菜单使用
    return render_template('admin/memories.html',
                           memories=memories,
                           keyword=keyword,
                           users=users)


@admin_bp.route('/memories/delete/<int:memory_id>', methods=['POST'])
@admin_required
def delete_memory(memory_id):
    """删除指定的长期记忆"""
    mem = db.session.get(Memory, memory_id)
    if mem:
        db.session.delete(mem)
        db.session.commit()
        flash('记忆已删除', 'success')
        SystemLog.add_log(
            user_id=current_user.id,
            action='delete_memory',
            details={'memory_id': memory_id},
            success=True,
            ip_address=request.remote_addr
        )
    else:
        flash('记忆不存在', 'danger')
    return redirect(url_for('admin.memories'))


@admin_bp.route('/memories/add', methods=['POST'])
@admin_required
def add_memory():
    """手动添加长期记忆"""
    user_id = request.form.get('user_id', 1, type=int)
    memory_type = request.form.get('memory_type', 'term_mapping')
    content = request.form.get('content', '').strip()

    if not content:
        flash('记忆内容不能为空', 'danger')
        return redirect(url_for('admin.memories'))

    mem = Memory(
        user_id=user_id,
        memory_type=memory_type,
        content=content
    )
    db.session.add(mem)
    db.session.commit()
    flash('记忆已添加', 'success')
    SystemLog.add_log(
        user_id=current_user.id,
        action='add_memory',
        details={'target_user_id': user_id, 'type': memory_type},
        success=True,
        ip_address=request.remote_addr
    )
    return redirect(url_for('admin.memories'))