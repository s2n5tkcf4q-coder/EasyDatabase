# knowledge_graph.py
import json
import logging
from typing import List, Dict, Optional, Union, Callable

from sqlalchemy import or_

from models import db, TableMeta, ColumnMeta, Metric, BusinessTerm, DatabaseConnection
# 延迟导入，避免循环依赖
# from llm_client import LLMClient

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """企业知识图谱：管理表/字段/指标/业务术语，并提供智能检索"""

    def __init__(self, llm_client=None):
        """
        :param llm_client: LLMClient 实例（用于向量化检索），可选
        """
        self.llm = llm_client

    # ----------------------------------------------------------------------
    # 表与列管理
    # ----------------------------------------------------------------------
    def get_all_tables_with_columns(self, database_id: Optional[int] = None) -> List[Dict]:
        """
        获取所有表及其列信息，可选择指定数据库连接
        :return: [{"table": "table_name", "database_id": id, "columns": [{"name":..., "type":..., "business_name":...}, ...]}, ...]
        """
        query = TableMeta.query
        if database_id:
            query = query.filter_by(database_id=database_id)
        tables = query.all()
        result = []
        for tbl in tables:
            cols = ColumnMeta.query.filter_by(table_id=tbl.id).all()
            result.append({
                "table": tbl.table_name,
                "database_id": tbl.database_id,
                "business_name": tbl.business_name,
                "description": tbl.description,
                "columns": [{
                    "name": col.column_name,
                    "type": col.data_type,
                    "business_name": col.business_name,
                    "description": col.description,
                    "is_primary_key": col.is_primary_key,
                    "is_dimension": col.is_dimension,
                    "is_date": col.is_date,
                    "is_aggregatable": col.is_aggregatable
                } for col in cols]
            })
        logger.debug(f"返回 {len(result)} 个表信息")
        return result

    def get_table_by_name(self, table_name: str) -> Optional[TableMeta]:
        """根据表名获取 TableMeta 对象"""
        return TableMeta.query.filter_by(table_name=table_name).first()

    def add_table(self, database_id: int, table_name: str,
                  business_name: Optional[str] = None,
                  description: Optional[str] = None) -> TableMeta:
        """添加一张表到知识图谱（若已存在则更新）"""
        existing = TableMeta.query.filter_by(database_id=database_id, table_name=table_name).first()
        if existing:
            existing.business_name = business_name or existing.business_name
            existing.description = description or existing.description
            db.session.commit()
            logger.info(f"更新表元数据: {table_name}")
            return existing
        tbl = TableMeta(
            database_id=database_id,
            table_name=table_name,
            business_name=business_name,
            description=description
        )
        db.session.add(tbl)
        db.session.commit()
        logger.info(f"添加表: {table_name}")
        return tbl

    def delete_table(self, table_id: int):
        """删除表及其所有列"""
        table = TableMeta.query.get_or_404(table_id)
        ColumnMeta.query.filter_by(table_id=table_id).delete()
        db.session.delete(table)
        db.session.commit()
        logger.info(f"删除表 ID={table_id}")

    def add_column(self, table_id: int, column_info: Dict) -> ColumnMeta:
        """添加或更新列信息"""
        existing = ColumnMeta.query.filter_by(table_id=table_id, column_name=column_info['column_name']).first()
        if existing:
            for key, value in column_info.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            db.session.commit()
            return existing
        col = ColumnMeta(
            table_id=table_id,
            column_name=column_info['column_name'],
            data_type=column_info.get('data_type'),
            business_name=column_info.get('business_name'),
            description=column_info.get('description'),
            is_primary_key=column_info.get('is_primary_key', False),
            is_foreign_key=column_info.get('is_foreign_key', False),
            is_aggregatable=column_info.get('is_aggregatable', True),
            is_dimension=column_info.get('is_dimension', False),
            is_date=column_info.get('is_date', False),
            sample_values=json.dumps(column_info.get('sample_values', [])) if column_info.get('sample_values') else None
        )
        db.session.add(col)
        db.session.commit()
        logger.info(f"添加列: {column_info['column_name']} 到表 ID={table_id}")
        return col

    def get_table_columns(self, table_name: str) -> List[Dict]:
        """获取指定表的所有列信息"""
        tbl = self.get_table_by_name(table_name)
        if not tbl:
            return []
        cols = ColumnMeta.query.filter_by(table_id=tbl.id).all()
        return [{
            "name": col.column_name,
            "type": col.data_type,
            "business_name": col.business_name,
            "description": col.description,
            "is_primary_key": col.is_primary_key,
            "is_dimension": col.is_dimension,
            "is_date": col.is_date,
            "is_aggregatable": col.is_aggregatable
        } for col in cols]

    # ----------------------------------------------------------------------
    # 指标管理
    # ----------------------------------------------------------------------
    def add_metric(self, name: str, description: str = None, formula: str = None,
                   related_columns: List[str] = None, created_by: str = None) -> Metric:
        """添加或更新一个指标"""
        metric = Metric.query.filter_by(name=name).first()
        if metric:
            metric.description = description or metric.description
            metric.formula = formula or metric.formula
            metric.related_columns = json.dumps(related_columns) if related_columns else metric.related_columns
            metric.created_by = created_by or metric.created_by
            db.session.commit()
            logger.info(f"更新指标: {name}")
            return metric
        metric = Metric(
            name=name,
            description=description,
            formula=formula,
            related_columns=json.dumps(related_columns) if related_columns else None,
            created_by=created_by
        )
        db.session.add(metric)
        db.session.commit()
        logger.info(f"添加指标: {name}")
        return metric

    def get_all_metrics(self) -> List[Metric]:
        return Metric.query.all()

    def get_metric_by_name(self, name: str) -> Optional[Metric]:
        return Metric.query.filter_by(name=name).first()

    def delete_metric(self, metric_id: int):
        Metric.query.filter_by(id=metric_id).delete()
        db.session.commit()
        logger.info(f"删除指标 ID={metric_id}")

    # ----------------------------------------------------------------------
    # 业务术语管理
    # ----------------------------------------------------------------------
    def add_business_term(self, term: str, definition: str = None,
                          mapping_logic: str = None, examples: str = None) -> BusinessTerm:
        existing = BusinessTerm.query.filter_by(term=term).first()
        if existing:
            existing.definition = definition or existing.definition
            existing.mapping_logic = mapping_logic or existing.mapping_logic
            existing.examples = examples or existing.examples
            db.session.commit()
            logger.info(f"更新业务术语: {term}")
            return existing
        bt = BusinessTerm(term=term, definition=definition, mapping_logic=mapping_logic, examples=examples)
        db.session.add(bt)
        db.session.commit()
        logger.info(f"添加业务术语: {term}")
        return bt

    def get_all_terms(self) -> List[BusinessTerm]:
        return BusinessTerm.query.all()

    def get_term_by_name(self, term: str) -> Optional[BusinessTerm]:
        return BusinessTerm.query.filter_by(term=term).first()

    def search_terms(self, keyword: str) -> List[BusinessTerm]:
        """关键词模糊搜索术语"""
        pattern = f"%{keyword}%"
        return BusinessTerm.query.filter(
            or_(BusinessTerm.term.ilike(pattern), BusinessTerm.definition.ilike(pattern))
        ).all()

    def delete_term(self, term_id: int):
        BusinessTerm.query.filter_by(id=term_id).delete()
        db.session.commit()
        logger.info(f"删除业务术语 ID={term_id}")

    # ----------------------------------------------------------------------
    # 智能检索（基于向量或关键词）
    # ----------------------------------------------------------------------
    def retrieve_relevant_tables(self, query: str, top_n: int = 5) -> List[Dict]:
        """
        根据自然语言查询找到最相关的表。
        如果未配置 LLM（向量检索），则退化为关键词匹配。
        """
        if self.llm:
            return self._vector_search(query, top_n, target='table')
        else:
            return self._keyword_search_tables(query, top_n)

    def retrieve_relevant_columns(self, query: str, top_n: int = 5) -> List[Dict]:
        """语义搜索相关列"""
        if self.llm:
            return self._vector_search(query, top_n, target='column')
        else:
            return self._keyword_search_columns(query, top_n)

    def retrieve_similar_terms(self, query: str, top_n: int = 5, threshold: float = 0.7) -> List[Dict]:
        """语义搜索业务术语"""
        if self.llm:
            return self._vector_search_terms(query, top_n, threshold)
        else:
            # 退化为关键词搜索
            terms = self.search_terms(query)[:top_n]
            return [{'term': t.term, 'definition': t.definition, 'mapping_logic': t.mapping_logic} for t in terms]

    # ---------- 内部向量搜索实现 ----------
    def _vector_search(self, query: str, top_n: int, target: str) -> List[Dict]:
        """对表或列的元数据进行向量相似度检索"""
        try:
            query_vec = self.llm.embed(query)
            if isinstance(query_vec, list) and len(query_vec) > 0 and isinstance(query_vec[0], list):
                query_vec = query_vec[0]
        except Exception as e:
            logger.error(f"获取查询向量失败: {e}")
            return []

        import numpy as np
        query_vec = np.array(query_vec)

        # 收集所有候选对象并计算嵌入（这里假设我们预先计算了表的嵌入，但 knowledge_graph 没有存储嵌入，
        # 为了简单，我们动态计算每个表/列的嵌入，但这样效率低下。实际应该预存储嵌入。
        # 作为简化，这里仍用关键词搜索回退，或者从 Memory 表中获取预先嵌入的元数据描述。
        # 鉴于 KnowledgeGraph 表没有嵌入字段，回退到关键词。
        logger.warning("向量检索暂未实现预存储嵌入，回退到关键词搜索")
        return self._keyword_search_tables(query, top_n) if target == 'table' else self._keyword_search_columns(query, top_n)

    def _vector_search_terms(self, query: str, top_n: int, threshold: float) -> List[Dict]:
        """对业务术语进行向量相似度检索（术语通常有预存嵌入？同样没有，回退关键词）"""
        logger.warning("术语向量检索回退到关键词")
        terms = self.search_terms(query)[:top_n]
        return [{'term': t.term, 'definition': t.definition, 'mapping_logic': t.mapping_logic} for t in terms]

    def _keyword_search_tables(self, query: str, top_n: int) -> List[Dict]:
        """基于表名和业务名/描述的关键词匹配"""
        pattern = f"%{query}%"
        tables = TableMeta.query.filter(
            or_(TableMeta.table_name.ilike(pattern),
                TableMeta.business_name.ilike(pattern),
                TableMeta.description.ilike(pattern))
        ).limit(top_n).all()
        result = []
        for t in tables:
            cols = ColumnMeta.query.filter_by(table_id=t.id).all()
            result.append({
                "table": t.table_name,
                "business_name": t.business_name,
                "description": t.description,
                "columns": [{"name": c.column_name, "business_name": c.business_name} for c in cols]
            })
        return result

    def _keyword_search_columns(self, query: str, top_n: int) -> List[Dict]:
        """基于列名和业务名/描述的关键词匹配"""
        pattern = f"%{query}%"
        cols = ColumnMeta.query.join(TableMeta).filter(
            or_(ColumnMeta.column_name.ilike(pattern),
                ColumnMeta.business_name.ilike(pattern),
                ColumnMeta.description.ilike(pattern))
        ).limit(top_n).all()
        return [{
            "column": f"{col.table.table_name}.{col.column_name}",
            "business_name": col.business_name,
            "description": col.description,
            "type": col.data_type
        } for col in cols]