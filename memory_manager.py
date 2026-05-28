# memory_manager.py
import json
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import numpy as np

from models import db, Memory, UserPreference, ChatHistory
from llm_client import LLMClient

logger = logging.getLogger(__name__)


class MemoryManager:
    """记忆管理器：管理短期记忆（对话上下文）和长期记忆（向量检索）"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    # ---------- 短期记忆 ----------
    def get_short_term_context(self,
                               user_id: int,
                               session_id: str,
                               max_rounds: int = 10) -> List[Dict]:
        """
        获取当前会话的短期记忆（最近几轮对话）
        :param user_id: 用户ID
        :param session_id: 会话ID
        :param max_rounds: 最大保留轮数
        :return: 消息列表，格式 [{"role": "...", "content": "..."}, ...]
        """
        messages = ChatHistory.query \
            .filter_by(user_id=user_id, session_id=session_id) \
            .order_by(ChatHistory.timestamp.desc()) \
            .limit(max_rounds * 2) \
            .all()

        # 按时间正序排列
        messages = list(reversed(messages))
        context = [{"role": m.role, "content": m.content} for m in messages]
        logger.debug(f"短期记忆加载完毕，消息数: {len(context)}")
        return context

    def add_short_term_message(self,
                               user_id: int,
                               session_id: str,
                               role: str,
                               content: str,
                               extra_info: Optional[Dict] = None):
        """
        添加一条消息到短期记忆（写入 ChatHistory）
        """
        chat = ChatHistory(
            user_id=user_id,
            session_id=session_id,
            role=role,
            content=content,
            extra_info=json.dumps(extra_info) if extra_info else None
        )
        db.session.add(chat)
        db.session.commit()
        logger.debug(f"短期记忆已添加: role={role}, len={len(content)}")

    # ---------- 长期记忆 ----------
    def add_long_term_memory(self,
                             user_id: int,
                             memory_type: str,
                             content: str,
                             metadata: Optional[Dict] = None):
        """
        添加一条长期记忆，自动计算嵌入向量
        :param user_id: 用户ID
        :param memory_type: 记忆类型（如 'analysis_framework', 'term_mapping', 'user_preference'）
        :param content: 文本内容
        :param metadata: 附加元数据
        """
        # 计算嵌入向量
        try:
            embedding = self.llm.embed(content)
            if isinstance(embedding, list) and len(embedding) > 0 and isinstance(embedding[0], list):
                # 如果返回列表的列表，取第一个
                embedding = embedding[0]
        except Exception as e:
            logger.error(f"计算嵌入向量失败: {e}")
            embedding = []

        memory = Memory(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            embedding=json.dumps(embedding) if embedding else None,
            metadata_=json.dumps(metadata) if metadata else None
        )
        db.session.add(memory)
        db.session.commit()
        logger.info(f"长期记忆已添加: type={memory_type}, len={len(content)}")

    def retrieve_similar_memories(self,
                                  user_id: int,
                                  query: str,
                                  top_n: int = 5,
                                  threshold: float = 0.75) -> List[Dict]:
        """
        通过语义相似度检索长期记忆
        :param user_id: 用户ID
        :param query: 查询文本
        :param top_n: 返回条数
        :param threshold: 相似度阈值（余弦相似度）
        :return: 相似记忆列表
        """
        # 获取所有有嵌入向量的记忆
        memories = Memory.query \
            .filter(Memory.user_id == user_id, Memory.embedding.isnot(None)) \
            .all()

        if not memories:
            return []

        # 计算查询向量
        try:
            query_emb = self.llm.embed(query)
            if isinstance(query_emb, list) and len(query_emb) > 0 and isinstance(query_emb[0], list):
                query_emb = query_emb[0]
            query_vec = np.array(query_emb)
        except Exception as e:
            logger.error(f"查询向量计算失败: {e}")
            return []

        # 计算相似度
        scored = []
        for mem in memories:
            try:
                mem_vec = np.array(json.loads(mem.embedding))
                # 余弦相似度
                dot = np.dot(query_vec, mem_vec)
                norm = np.linalg.norm(query_vec) * np.linalg.norm(mem_vec)
                if norm == 0:
                    sim = 0.0
                else:
                    sim = float(dot / norm)
                if sim >= threshold:
                    scored.append((sim, mem))
            except Exception as e:
                logger.warning(f"向量计算异常: {e}")
                continue

        # 按相似度降序排序
        scored.sort(key=lambda x: x[0], reverse=True)
        top_memories = scored[:top_n]

        # 更新访问时间
        for _, mem in top_memories:
            mem.last_accessed = datetime.utcnow()
        db.session.commit()

        results = [mem.to_dict() for _, mem in top_memories]
        logger.debug(f"长期记忆检索完成，命中 {len(results)} 条")
        return results

    def retrieve_all_by_type(self, user_id: int, memory_type: str) -> List[Dict]:
        """获取某类型的所有长期记忆（无向量检索）"""
        memories = Memory.query \
            .filter_by(user_id=user_id, memory_type=memory_type) \
            .order_by(Memory.created_at.desc()) \
            .all()
        return [mem.to_dict() for mem in memories]

    def delete_memory(self, memory_id: int, user_id: int) -> bool:
        """删除一条长期记忆"""
        mem = Memory.query.filter_by(id=memory_id, user_id=user_id).first()
        if mem:
            db.session.delete(mem)
            db.session.commit()
            logger.info(f"长期记忆已删除: id={memory_id}")
            return True
        return False

    # ---------- 分析框架管理 ----------
    def save_framework(self, user_id: int, name: str, definition: str):
        """
        保存一个分析框架（如RFM模型定义）
        """
        metadata = {"name": name, "type": "analysis_framework"}
        self.add_long_term_memory(
            user_id=user_id,
            memory_type="analysis_framework",
            content=definition,
            metadata=metadata
        )

    def get_relevant_frameworks(self, user_id: int, query: str, top_n: int = 3) -> List[Dict]:
        """
        获取与分析问题相关的分析框架
        """
        memories = self.retrieve_similar_memories(
            user_id=user_id,
            query=query,
            top_n=top_n,
            threshold=0.6
        )
        return [m for m in memories if m.get('memory_type') == 'analysis_framework']

    # ---------- 用户偏好管理 ----------
    def get_user_preferences(self, user_id: int) -> Dict:
        """
        获取用户偏好，若无则返回默认值
        """
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            return {
                "default_output_format": "excel",
                "rfm_definition": None,
                "term_mappings": {}
            }
        return {
            "default_output_format": pref.default_output_format or "excel",
            "rfm_definition": pref.rfm_definition,
            "term_mappings": json.loads(pref.term_mappings) if pref.term_mappings else {}
        }

    def update_user_preference(self,
                               user_id: int,
                               key: str,
                               value) -> bool:
        """
        更新用户偏好中的某个字段
        """
        pref = UserPreference.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id)
            db.session.add(pref)

        if key == "default_output_format":
            pref.default_output_format = value
        elif key == "rfm_definition":
            pref.rfm_definition = value
        elif key == "term_mappings":
            pref.term_mappings = json.dumps(value) if isinstance(value, dict) else value
        else:
            return False

        pref.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info(f"用户偏好已更新: user_id={user_id}, key={key}")
        return True

    def learn_from_interaction(self,
                               user_id: int,
                               user_message: str,
                               assistant_response: str,
                               extra_info: Optional[Dict] = None):
        """
        从交互中学习，自动提取并存储可能的长期记忆
        简单策略：如果用户消息中包含明确的业务术语定义，自动记录
        """
        # 检测是否包含术语定义句式，如 "xx 是指 ...", "xx 就是 ..."
        import re
        term_pattern = r'["\']?([^"\']+?)["\']?\s*(?:是|指|就是|定义[为为])\s*["\']?(.+?)["\']?(?:[，。\.]|$)'
        matches = re.findall(term_pattern, user_message)
        for term, meaning in matches:
            if len(term.strip()) > 1 and len(meaning.strip()) > 1:
                content = f"术语: {term.strip()} -> 含义: {meaning.strip()}"
                self.add_long_term_memory(
                    user_id=user_id,
                    memory_type="term_mapping",
                    content=content,
                    metadata={"term": term.strip(), "meaning": meaning.strip()}
                )
                logger.info(f"自动学习术语映射: {term.strip()} = {meaning.strip()}")