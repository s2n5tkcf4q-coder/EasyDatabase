# utils.py
import os
import io
import random
import string
import logging
import shutil
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from flask import current_app

from models import db, TableMeta, ColumnMeta, DatabaseConnection

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# 验证码生成（供 auth 蓝图使用）
# ----------------------------------------------------------------------
def generate_captcha(code_length: int = 4) -> (Image.Image, str):
    """
    生成验证码图片和文本
    :param code_length: 验证码长度
    :return: (PIL Image, 验证码字符串)
    """
    chars = string.digits + string.ascii_uppercase
    code = ''.join(random.choices(chars, k=code_length))

    width, height = 120, 50
    image = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype('arial.ttf', 36)
    except IOError:
        font = ImageFont.load_default()

    for i, ch in enumerate(code):
        x = 10 + i * 25
        y = random.randint(2, 8)
        draw.text((x, y), ch, font=font,
                  fill=(random.randint(0, 128), random.randint(0, 128), random.randint(0, 128)))

    for _ in range(random.randint(3, 6)):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)],
                  fill=(random.randint(0, 128), random.randint(0, 128), random.randint(0, 128)))

    for _ in range(100):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(0, 128), random.randint(0, 128), random.randint(0, 128)))

    image = image.filter(ImageFilter.BLUR)
    return image, code


# ----------------------------------------------------------------------
# 元数据同步
# ----------------------------------------------------------------------
def sync_metadata(conn: DatabaseConnection, sample_rows: int = 3):
    """
    从目标数据库同步表/列元数据到知识图谱
    :param conn: DatabaseConnection 实例
    :param sample_rows: 每列采样行数（用于记录示例值）
    """
    from sqlalchemy import create_engine, inspect, MetaData
    from sqlalchemy.exc import SQLAlchemyError

    logger.info(f"开始同步元数据，连接名称: {conn.name}")

    try:
        engine = create_engine(conn.connection_string)
        inspector = inspect(engine)

        # 获取所有表名
        table_names = inspector.get_table_names()
        logger.info(f"发现 {len(table_names)} 个表: {', '.join(table_names)}")

        # 逐一处理
        for table_name in table_names:
            # 创建或更新 TableMeta
            table_meta = TableMeta.query.filter_by(
                database_id=conn.id,
                table_name=table_name
            ).first()

            if not table_meta:
                table_meta = TableMeta(
                    database_id=conn.id,
                    table_name=table_name,
                    business_name=table_name  # 默认为表名，后续可手动修改
                )
                db.session.add(table_meta)
                db.session.flush()  # 获取 id
            else:
                table_meta.sync_time = datetime.utcnow()

            logger.debug(f"处理表: {table_name} (id={table_meta.id})")

            # 获取列信息
            columns = inspector.get_columns(table_name)
            pk_cols = inspector.get_pk_constraint(table_name).get('constrained_columns', [])
            fk_cols = inspector.get_foreign_keys(table_name)

            # 收集外键列名
            foreign_key_column_names = set()
            for fk in fk_cols:
                foreign_key_column_names.update(fk['constrained_columns'])

            # 获取列样本数据（可选，可能较慢）
            sample_data = {}
            if sample_rows > 0:
                try:
                    with engine.connect() as connection:
                        # 使用 LIMIT 语句获取前几行
                        sample_query = f"SELECT * FROM {table_name} LIMIT {sample_rows}"
                        rows = connection.execute(sample_query).fetchall()
                        if rows:
                            # 转置为列 -> 值列表
                            col_keys = rows[0].keys()
                            sample_data = {k: [] for k in col_keys}
                            for row in rows:
                                for k in col_keys:
                                    sample_data[k].append(str(row[k]))
                except Exception as e:
                    logger.warning(f"获取表 {table_name} 样本数据失败: {e}")

            for col_info in columns:
                col_name = col_info['name']
                col_type = str(col_info['type'])
                nullable = col_info.get('nullable', True)
                is_pk = col_name in pk_cols
                is_fk = col_name in foreign_key_column_names

                # 判断是否可聚合（数值类型或日期类型）
                type_upper = col_type.upper()
                numeric_types = ('INTEGER', 'INT', 'BIGINT', 'SMALLINT', 'NUMERIC', 'DECIMAL', 'FLOAT', 'DOUBLE', 'REAL')
                is_numeric = any(t in type_upper for t in numeric_types)
                is_date = any(kw in type_upper for kw in ('DATE', 'TIME', 'TIMESTAMP'))
                is_aggregatable = is_numeric or is_date

                # 假设所有列都可以作为维度（实际可能需要业务确认）
                is_dimension = True

                # 获取样本值
                sample_vals = sample_data.get(col_name, [])

                # 创建或更新 ColumnMeta
                existing_col = ColumnMeta.query.filter_by(
                    table_id=table_meta.id,
                    column_name=col_name
                ).first()

                col_data = {
                    'data_type': col_type,
                    'business_name': col_name,  # 默认
                    'description': '',
                    'is_primary_key': is_pk,
                    'is_foreign_key': is_fk,
                    'is_aggregatable': is_aggregatable,
                    'is_dimension': is_dimension,
                    'is_date': is_date,
                    'sample_values': sample_vals if sample_vals else None
                }

                if existing_col:
                    # 更新现有列
                    for key, value in col_data.items():
                        setattr(existing_col, key, value)
                else:
                    new_col = ColumnMeta(
                        table_id=table_meta.id,
                        column_name=col_name,
                        **col_data
                    )
                    db.session.add(new_col)

            db.session.commit()  # 每张表提交一次

        engine.dispose()
        logger.info(f"元数据同步完成，共处理 {len(table_names)} 个表")
        return len(table_names)

    except SQLAlchemyError as e:
        logger.error(f"同步元数据失败: {e}")
        db.session.rollback()
        raise
    except Exception as e:
        logger.error(f"同步元数据时发生未知错误: {e}")
        raise


# ----------------------------------------------------------------------
# 文件清理
# ----------------------------------------------------------------------
def cleanup_output_files(max_age_hours: float = 1.0):
    """
    清理超过指定时长的生成文件
    :param max_age_hours: 文件最大保留时间（小时）
    """
    output_dir = current_app.config['OUTPUT_FOLDER']
    if not os.path.exists(output_dir):
        return

    now = time.time()
    cut_off = now - max_age_hours * 3600
    cleaned = 0
    for fname in os.listdir(output_dir):
        fpath = os.path.join(output_dir, fname)
        if os.path.isfile(fpath):
            mtime = os.path.getmtime(fpath)
            if mtime < cut_off:
                try:
                    os.remove(fpath)
                    cleaned += 1
                    logger.debug(f"清理过期文件: {fname}")
                except OSError as e:
                    logger.warning(f"无法删除文件 {fname}: {e}")
    if cleaned:
        logger.info(f"已清理 {cleaned} 个过期输出文件")


# ----------------------------------------------------------------------
# 安全工具
# ----------------------------------------------------------------------
def safe_filename(filename: str) -> str:
    """去除文件名中的非法字符，保留字母、数字、下划线、点和横线"""
    import re
    return re.sub(r'[^\w\.\-]', '_', filename).strip('_')


def sanitize_input(text: str) -> str:
    """简单清理用户输入（去除首尾空白，可扩展 XSS 过滤）"""
    if not isinstance(text, str):
        return ''
    return text.strip()


# ----------------------------------------------------------------------
# 配置读取辅助
# ----------------------------------------------------------------------
def get_config_value(key: str, default=None):
    """
    尝试从数据库动态配置读取，失败则使用应用默认配置
    """
    try:
        from models import SysConfig
        db_val = SysConfig.get_config(key)
        if db_val is not None:
            return db_val
    except Exception:
        pass
    try:
        return current_app.config.get(key, default)
    except RuntimeError:
        return default