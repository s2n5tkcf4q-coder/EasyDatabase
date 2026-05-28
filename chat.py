# chat.py
import uuid
import json
from datetime import datetime
from typing import Dict, List, Optional

from flask import (
    Blueprint, render_template, request, jsonify,
    current_app, session, url_for
)
from flask_login import login_required, current_user

from models import db, ChatHistory, SystemLog
from task_planner import TaskPlanner
from text_to_sql import TextToSQL
from reflection import Reflection
from code_executor import CodeExecutor
from output_generator import OutputGenerator
from memory_manager import MemoryManager
from knowledge_graph import KnowledgeGraph
from llm_client import LLMClient

chat_bp = Blueprint('chat', __name__)


# ---------- 工具函数 ----------
def get_or_create_session_id():
    """获取当前对话的 session_id，若不存在则新建"""
    if 'chat_session_id' not in session:
        session['chat_session_id'] = str(uuid.uuid4())
    return session['chat_session_id']


def build_context(session_id, max_rounds=10):
    """从 ChatHistory 构建短期对话上下文"""
    messages = ChatHistory.query \
        .filter_by(user_id=current_user.id, session_id=session_id) \
        .order_by(ChatHistory.timestamp.asc()) \
        .limit(max_rounds * 2) \
        .all()
    return [{'role': msg.role, 'content': msg.content} for msg in messages]


def _retrieve_metadata(kg: KnowledgeGraph, query: str) -> List[Dict]:
    """
    辅助函数：根据用户查询意图，从知识图谱中检索相关表和列信息。
    返回格式：[{"table": "...", "columns": [{"name": "...", "type": "...", ...}, ...]}, ...]
    """
    # 首先尝试语义/关键词检索相关表
    related_tables = kg.retrieve_relevant_tables(query, top_n=5)
    if related_tables:
        # 进一步获取每张表的完整列信息
        result = []
        for tbl in related_tables:
            table_name = tbl.get("table") or tbl.get("table_name")
            if not table_name:
                continue
            columns = kg.get_table_columns(table_name)
            result.append({
                "table": table_name,
                "business_name": tbl.get("business_name", ""),
                "columns": columns
            })
        return result
    else:
        # 如果没有相关表，返回全量表结构（作为兜底）
        all_tables = kg.get_all_tables_with_columns()
        return [{"table": t["table"], "columns": t["columns"]} for t in all_tables]


# ---------- 页面路由 ----------
@chat_bp.route('/')
@login_required
def chat_page():
    """返回问答主页面"""
    return render_template('chat.html')


# ---------- API 路由 ----------
@chat_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    """接收用户消息，执行智能体流程，返回结果"""
    user_message = request.json.get('message', '').strip()
    if not user_message:
        return jsonify({'error': '消息不能为空'}), 400

    session_id = get_or_create_session_id()
    now = datetime.utcnow()

    # 1. 存储用户消息
    user_chat = ChatHistory(
        user_id=current_user.id,
        session_id=session_id,
        role='user',
        content=user_message,
        timestamp=now
    )
    db.session.add(user_chat)
    db.session.commit()

    # 2. 构建上下文
    context = build_context(session_id)

    # 初始化各模块
    llm = LLMClient()
    planner = TaskPlanner(llm)
    sql_gen = TextToSQL(llm)
    reflector = Reflection(llm)
    executor = CodeExecutor()
    output_gen = OutputGenerator()
    memory_mgr = MemoryManager()
    kg = KnowledgeGraph()

    # 3. 任务规划
    try:
        plan = planner.plan(user_message, context)
        current_app.logger.info(f"任务规划成功: {plan}")
    except Exception as e:
        current_app.logger.error(f"任务规划失败: {str(e)}")
        return jsonify({'error': f'任务规划失败: {str(e)}'}), 500

    # 4. 执行计划，构建思维链
    thinking_chain = []
    final_result = None
    generated_file = None
    error_occurred = False
    metadata_context = None  # 用于存储知识检索获取的真实表/字段信息

    for step in plan['steps']:
        step_info = {
            'step_id': step['id'],
            'description': step['description'],
            'status': 'pending',
            'detail': ''
        }
        thinking_chain.append(step_info)

        try:
            if step['tool'] == 'knowledge_retrieval':
                # 调用知识图谱检索表结构（相关表）
                metadata_context = _retrieve_metadata(kg, step.get('query', user_message))
                if not metadata_context:
                    step_info['detail'] += "未检索到相关表，将使用全量表结构。"
                else:
                    table_names = [t['table'] for t in metadata_context]
                    step_info['detail'] += f"检索到相关表: {', '.join(table_names)}"
                step_info['status'] = 'success'

            elif step['tool'] == 'text_to_sql':
                # 将检索到的元数据上下文传递给 SQL 生成器（如果存在）
                # 注意：text_to_sql.py 的 generate_and_execute 需要支持 metadata_context 参数
                sql_result = sql_gen.generate_and_execute(
                    step, kg,
                    metadata_context=metadata_context,
                    correction=None
                )
                if sql_result.get('error'):
                    # 进入反思修正流程，最多3轮
                    for attempt in range(3):
                        current_app.logger.info(f"SQL错误，尝试修正第{attempt+1}轮")
                        correction = reflector.self_correct(
                            sql_result['error'], user_message, step, sql_result.get('sql')
                        )
                        step_info['detail'] += f"修正尝试 {attempt+1}: {correction['analysis']}\n"
                        sql_result = sql_gen.generate_and_execute(
                            step, kg,
                            metadata_context=metadata_context,
                            correction=correction
                        )
                        if not sql_result.get('error'):
                            break
                    if sql_result.get('error'):
                        raise Exception(f"SQL执行多次修正后仍失败: {sql_result['error']}")
                step_info['status'] = 'success'
                step_info['detail'] += f"SQL: {sql_result.get('sql')}\n结果行数: {sql_result.get('row_count')}"
                final_result = sql_result.get('data')

            elif step['tool'] == 'code_executor':
                code = step.get('code') or plan.get('code_snippet')
                if not code:
                    # 如果没有提供代码，可以尝试让 LLM 基于上一步结果生成绘图代码（此处暂略）
                    raise Exception("代码执行步骤缺少代码")
                exec_result = executor.execute(code)
                if exec_result['error']:
                    raise Exception(f"代码执行错误: {exec_result['error']}")
                step_info['status'] = 'success'
                step_info['detail'] += f"代码执行成功，输出: {exec_result.get('output')}"
                # 如果生成了图表文件，可以从 exec_result['files'] 中获取路径
                if exec_result.get('files'):
                    step_info['detail'] += f"\n生成文件: {exec_result['files']}"
                final_result = exec_result.get('data')  # 若是表格数据则保存

            else:
                raise ValueError(f"未知工具: {step['tool']}")

        except Exception as e:
            step_info['status'] = 'failed'
            step_info['detail'] += f"失败: {str(e)}"
            error_occurred = True
            current_app.logger.error(f"步骤 {step['id']} 执行失败: {str(e)}")
            break

    # 5. 整合最终答案
    if error_occurred:
        answer = "抱歉，处理过程中出现错误，请查看智能体Agent详情。"
    else:
        # 如果有最终结果数据集，默认生成 Excel
        output_format = session.get('output_format', 'excel')  # 可从用户偏好读取
        if final_result is not None and isinstance(final_result, list):
            try:
                generated_file = output_gen.generate(
                    final_result,
                    format=output_format,
                    context=f"用户问题: {user_message}"
                )
            except Exception as e:
                answer = f"数据已生成，但导出文件失败: {str(e)}"
                current_app.logger.error(f"文件生成失败: {str(e)}")
        # 使用 LLM 将最终结果概括为自然语言
        try:
            summary_prompt = f"用户问题: {user_message}\n分析结果摘要: {json.dumps(final_result, ensure_ascii=False)[:500]}"
            answer = llm.chat([{'role': 'system', 'content': '总结分析结果，给出业务见解，总结分析结果时请使用 Markdown 格式，包括标题、列表、加粗等，但不要包含代码块。'}] + context[-4:] + [
                {'role': 'user', 'content': summary_prompt}
            ])
        except Exception as e:
            answer = "分析完成，详见智能体Agent和数据文件。"
            current_app.logger.warning(f"LLM总结失败: {str(e)}")

    # 6. 构建额外信息（思维链 JSON）
    extra_info = json.dumps({
        'thinking_chain': thinking_chain,
        'steps': len(thinking_chain),
        'file_url': url_for('static', filename=f'outputs/{generated_file}') if generated_file else None,
        'file_name': generated_file
    })

    # 7. 存储助手回复
    assistant_chat = ChatHistory(
        user_id=current_user.id,
        session_id=session_id,
        role='assistant',
        content=answer,
        extra_info=extra_info,
        timestamp=datetime.utcnow()
    )
    db.session.add(assistant_chat)
    db.session.commit()

    # 自动学习长期记忆
    try:
        memory_mgr.learn_from_interaction(
            user_id=current_user.id,
            user_message=user_message,
            assistant_response=answer
        )
    except Exception as e:
        current_app.logger.warning(f"长期记忆学习失败: {e}")

    # 8. 记录日志
    SystemLog.add_log(
        user_id=current_user.id,
        action='chat_query',
        details={'message': user_message, 'success': not error_occurred},
        success=not error_occurred,
        ip_address=request.remote_addr
    )

    # 9. 构建响应
    response = {
        'answer': answer,
        'thinking_chain': thinking_chain,
        'file_url': url_for('static', filename=f'outputs/{generated_file}') if generated_file else None,
        'file_name': generated_file,
        'session_id': session_id
    }
    return jsonify(response)


# ---------- 历史相关接口 ----------
@chat_bp.route('/history', methods=['GET'])
@login_required
def get_history():
    """获取当前用户的所有会话摘要"""
    sessions = db.session.query(
        ChatHistory.session_id,
        db.func.max(ChatHistory.timestamp).label('last_time'),
        db.func.substr(
            db.func.group_concat(ChatHistory.content, ' | '), 1, 80
        ).label('summary')
    ).filter_by(user_id=current_user.id) \
     .group_by(ChatHistory.session_id) \
     .order_by(db.text('last_time DESC')) \
     .all()

    history = []
    for s in sessions:
        history.append({
            'session_id': s.session_id,
            'last_time': s.last_time.isoformat(),
            'summary': s.summary[:80] + ('...' if s.summary and len(s.summary) > 80 else '')
        })
    return jsonify(history)


@chat_bp.route('/history/<session_id>', methods=['GET'])
@login_required
def get_session_messages(session_id):
    """获取指定会话的所有消息"""
    messages = ChatHistory.query \
        .filter_by(user_id=current_user.id, session_id=session_id) \
        .order_by(ChatHistory.timestamp.asc()) \
        .all()
    return jsonify([msg.to_dict() for msg in messages])


@chat_bp.route('/history/<session_id>/delete', methods=['POST'])
@login_required
def delete_session(session_id):
    """删除指定会话的所有消息"""
    ChatHistory.query \
        .filter_by(user_id=current_user.id, session_id=session_id) \
        .delete()
    db.session.commit()
    if session.get('chat_session_id') == session_id:
        session.pop('chat_session_id', None)
    return jsonify({'success': True})


@chat_bp.route('/new_session', methods=['POST'])
@login_required
def new_session():
    """开启新会话"""
    session.pop('chat_session_id', None)
    return jsonify({'session_id': get_or_create_session_id()})