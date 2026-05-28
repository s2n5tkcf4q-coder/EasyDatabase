# models.py
import json
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ---------- 用户与权限 ----------
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='normal')  # 'admin' 或 'normal'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

    # 关联
    preferences = db.relationship('UserPreference', backref='user', uselist=False, lazy='joined')
    chat_histories = db.relationship('ChatHistory', backref='user', lazy='dynamic')
    memories = db.relationship('Memory', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }

    def __repr__(self):
        return f'<User {self.username}>'


class UserPreference(db.Model):
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    default_output_format = db.Column(db.String(20), default='excel')  # excel, html, word, ppt
    rfm_definition = db.Column(db.Text)  # 用户自定义 RFM 阈值
    term_mappings = db.Column(db.Text)   # JSON 字符串，存储业务术语到逻辑的映射
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------- 系统配置（动态参数） ----------
class SysConfig(db.Model):
    __tablename__ = 'sys_config'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_config(key, default=None):
        entry = SysConfig.query.filter_by(key=key).first()
        if entry:
            return entry.value
        return default

    @staticmethod
    def set_config(key, value, description=None):
        entry = SysConfig.query.filter_by(key=key).first()
        if not entry:
            entry = SysConfig(key=key, value=value, description=description)
            db.session.add(entry)
        else:
            entry.value = value
            if description:
                entry.description = description
            entry.updated_at = datetime.utcnow()
        db.session.commit()


# ---------- 外部数据库连接配置 ----------
class DatabaseConnection(db.Model):
    __tablename__ = 'database_connections'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    db_type = db.Column(db.String(20), nullable=False)  # mysql, postgresql, sqlite, etc.
    host = db.Column(db.String(255))
    port = db.Column(db.Integer)
    database = db.Column(db.String(255))
    username = db.Column(db.String(255))
    password = db.Column(db.String(255))   # 实际部署应加密存储
    extra_params = db.Column(db.Text)      # 额外连接参数（JSON）
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关联的知识图谱元数据
    tables = db.relationship('TableMeta', backref='database', lazy='dynamic')

    @property
    def connection_string(self):
        """根据类型生成 SQLAlchemy 连接字符串"""
        if self.db_type == 'sqlite':
            return f'sqlite:///{self.database}'
        elif self.db_type == 'mysql':
            return f'mysql+pymysql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}'
        elif self.db_type == 'postgresql':
            return f'postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}'
        else:
            raise ValueError(f'Unsupported database type: {self.db_type}')


# ---------- 知识图谱 ----------
class TableMeta(db.Model):
    __tablename__ = 'table_meta'

    id = db.Column(db.Integer, primary_key=True)
    database_id = db.Column(db.Integer, db.ForeignKey('database_connections.id'), nullable=False)
    table_name = db.Column(db.String(255), nullable=False)
    business_name = db.Column(db.String(255))    # 业务中文名
    description = db.Column(db.Text)
    sync_time = db.Column(db.DateTime, default=datetime.utcnow)

    columns = db.relationship('ColumnMeta', backref='table', lazy='dynamic')

    def __repr__(self):
        return f'<TableMeta {self.table_name}>'


class ColumnMeta(db.Model):
    __tablename__ = 'column_meta'

    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('table_meta.id'), nullable=False)
    column_name = db.Column(db.String(255), nullable=False)
    data_type = db.Column(db.String(50))
    business_name = db.Column(db.String(255))
    description = db.Column(db.Text)
    is_primary_key = db.Column(db.Boolean, default=False)
    is_foreign_key = db.Column(db.Boolean, default=False)
    is_aggregatable = db.Column(db.Boolean, default=True)
    is_dimension = db.Column(db.Boolean, default=False)
    is_date = db.Column(db.Boolean, default=False)
    sample_values = db.Column(db.Text)  # JSON 列表

    def __repr__(self):
        return f'<ColumnMeta {self.table.table_name}.{self.column_name}>'


class Metric(db.Model):
    __tablename__ = 'metrics'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    description = db.Column(db.Text)
    formula = db.Column(db.Text)          # 计算逻辑描述或 SQL 片段
    related_columns = db.Column(db.Text)  # JSON 数组存储关联的 ColumnMeta.id
    created_by = db.Column(db.String(80))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BusinessTerm(db.Model):
    __tablename__ = 'business_terms'

    id = db.Column(db.Integer, primary_key=True)
    term = db.Column(db.String(255), nullable=False, unique=True)
    definition = db.Column(db.Text)
    mapping_logic = db.Column(db.Text)   # 如 SQL 条件片段：sum(amount)>10000 and recency<30
    examples = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------- 聊天与记忆 ----------
class ChatHistory(db.Model):
    __tablename__ = 'chat_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    session_id = db.Column(db.String(100), nullable=False, index=True)  # 会话标识
    role = db.Column(db.String(20), nullable=False)                     # 'user', 'assistant', 'system'
    content = db.Column(db.Text, nullable=False)
    # 思维链等额外信息（JSON 字符串）
    extra_info = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        extra = None
        if self.extra_info:
            try:
                extra = json.loads(self.extra_info)
            except (json.JSONDecodeError, TypeError):
                extra = None  # 解析失败则忽略
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'extra_info': extra,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


class Memory(db.Model):
    """长期记忆存储，供向量检索使用"""
    __tablename__ = 'memories'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    memory_type = db.Column(db.String(50))                 # 如 'analysis_framework', 'term_mapping', 'preference'
    content = db.Column(db.Text, nullable=False)            # 原始文本
    embedding = db.Column(db.Text)                          # JSON 格式的向量，或存储路径
    metadata_ = db.Column('metadata', db.Text)              # 额外信息（JSON）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_accessed = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'memory_type': self.memory_type,
            'content': self.content,
            'metadata': json.loads(self.metadata_) if self.metadata_ else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ---------- 系统日志 ----------
class SystemLog(db.Model):
    __tablename__ = 'system_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)       # 操作类型：login, sql_generation, file_export, config_change
    details = db.Column(db.Text)                             # 详情（JSON 或自由文本）
    success = db.Column(db.Boolean, default=True)
    ip_address = db.Column(db.String(45))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def add_log(user_id, action, details=None, success=True, ip_address=None):
        log = SystemLog(
            user_id=user_id,
            action=action,
            details=json.dumps(details) if isinstance(details, dict) else details,
            success=success,
            ip_address=ip_address
        )
        db.session.add(log)
        db.session.commit()