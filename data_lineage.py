# data_lineage.py
"""
数据血缘追溯模块

通过分析知识图谱中表与列的元数据、外键关系以及指标的公式定义，
构建数据依赖关系图，提供指标和字段的血缘追溯功能，
从而解释分析结果的可信度和来源。
"""

import json
import logging
from typing import Dict, List, Optional, Set, Tuple, Any

from models import db, TableMeta, ColumnMeta, Metric, BusinessTerm
from knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class DataLineage:
    """数据血缘追溯器"""

    def __init__(self, knowledge_graph: KnowledgeGraph):
        """
        :param knowledge_graph: 知识图谱实例，用于查询元数据
        """
        self.kg = knowledge_graph

    # ------------------------------------------------------------------
    # 指标血缘追溯
    # ------------------------------------------------------------------
    def trace_metric(self, metric_name: str) -> Dict[str, Any]:
        """
        查询某个指标的血缘关系
        :param metric_name: 指标名称（精确匹配）
        :return: 血缘信息字典
            {
                "metric": str,
                "description": str,
                "formula": str,
                "upstream_tables": [{"table": str, "columns": [str]}],
                "lineage_path": [{"step": str, "detail": str}]
            }
        """
        metric = Metric.query.filter_by(name=metric_name).first()
        if not metric:
            logger.warning(f"指标 '{metric_name}' 不存在")
            return {"error": f"指标 '{metric_name}' 未找到"}

        # 解析关联列
        related_col_ids = []
        if metric.related_columns:
            try:
                related_col_ids = json.loads(metric.related_columns)
            except json.JSONDecodeError:
                logger.error(f"指标 {metric_name} 的 related_columns 不是有效 JSON")
                related_col_ids = []

        # 收集直接依赖的列信息
        upstream_tables = {}
        columns_detail = []
        for col_id in related_col_ids:
            col = ColumnMeta.query.get(col_id)
            if not col:
                continue
            tbl = TableMeta.query.get(col.table_id)
            if tbl:
                table_name = tbl.table_name
                if table_name not in upstream_tables:
                    upstream_tables[table_name] = []
                upstream_tables[table_name].append(col.column_name)
                columns_detail.append({
                    "column": col.column_name,
                    "table": table_name,
                    "business_name": col.business_name,
                    "data_type": col.data_type
                })

        # 构建血缘路径：指标 -> 直接关联列 -> 表
        lineage_path = [{
            "step": "指标定义",
            "detail": f"指标名称: {metric_name}， 公式: {metric.formula or '未指定'}"
        }]
        for table, cols in upstream_tables.items():
            lineage_path.append({
                "step": f"使用表 {table}",
                "detail": f"依赖字段: {', '.join(cols)}"
            })

        # 尝试通过外键向上追溯（第一层）
        for col_detail in columns_detail:
            col = ColumnMeta.query.filter_by(
                table_id=TableMeta.query.filter_by(table_name=col_detail["table"]).first().id,
                column_name=col_detail["column"]
            ).first()
            if col and col.is_foreign_key:
                # 查找该外键关联的父表列（通过同名字段或注释，这里简化：假设同名字段存在于其他表）
                # 真实场景需要记录外键引用关系，这里仅做示意
                parent_refs = self._find_possible_parent(col)
                if parent_refs:
                    for p in parent_refs:
                        lineage_path.append({
                            "step": "外键引用",
                            "detail": f"字段 {col.column_name} 可能引用 {p['table']}.{p['column']}"
                        })

        result = {
            "metric": metric_name,
            "description": metric.description,
            "formula": metric.formula,
            "upstream_tables": [{"table": k, "columns": v} for k, v in upstream_tables.items()],
            "lineage_path": lineage_path
        }
        logger.info(f"指标血缘查询: {metric_name} -> 涉及表 {list(upstream_tables.keys())}")
        return result

    def _find_possible_parent(self, fk_column: ColumnMeta) -> List[Dict]:
        """通过列名猜测可能的外键父表列（简单实现）"""
        # 假设外键列名去掉 '_id' 后缀即为关联表名，且该表有同名字段或 'id'
        possible_parents = []
        col_name = fk_column.column_name
        if col_name.endswith('_id'):
            parent_table_name = col_name[:-3]  # 例如 user_id -> user
            parent_tbl = TableMeta.query.filter_by(table_name=parent_table_name).first()
            if parent_tbl:
                possible_parents.append({"table": parent_tbl.table_name, "column": "id"})
        return possible_parents

    # ------------------------------------------------------------------
    # 列血缘追溯（基于外键关系）
    # ------------------------------------------------------------------
    def trace_column(self, table_name: str, column_name: str) -> Dict[str, Any]:
        """
        查询某个列的血缘来源
        :return: 包含上游表和列的字典
        """
        tbl = TableMeta.query.filter_by(table_name=table_name).first()
        if not tbl:
            return {"error": f"表 {table_name} 不存在"}
        col = ColumnMeta.query.filter_by(table_id=tbl.id, column_name=column_name).first()
        if not col:
            return {"error": f"列 {table_name}.{column_name} 不存在"}

        lineage = {
            "table": table_name,
            "column": column_name,
            "is_foreign_key": col.is_foreign_key,
            "upstream": []
        }

        if col.is_foreign_key:
            parents = self._find_possible_parent(col)
            lineage["upstream"] = parents

        logger.info(f"列血缘查询: {table_name}.{column_name} -> 外键:{col.is_foreign_key}")
        return lineage

    # ------------------------------------------------------------------
    # 表级别依赖图
    # ------------------------------------------------------------------
    def build_table_dependency_graph(self) -> Dict[str, List[str]]:
        """
        基于外键关系构建表间依赖图（表 -> 其依赖的父表列表）
        """
        graph = {}
        all_tables = TableMeta.query.all()
        for tbl in all_tables:
            graph[tbl.table_name] = []
            fk_cols = ColumnMeta.query.filter_by(table_id=tbl.id, is_foreign_key=True).all()
            for fk in fk_cols:
                parents = self._find_possible_parent(fk)
                for p in parents:
                    if p["table"] not in graph[tbl.table_name]:
                        graph[tbl.table_name].append(p["table"])
        logger.info(f"生成表依赖图: {graph}")
        return graph

    def get_table_lineage(self, table_name: str, direction: str = "upstream") -> List[str]:
        """
        获取指定表的血缘关系
        :param direction: "upstream" 上游依赖，"downstream" 下游引用
        """
        graph = self.build_table_dependency_graph()
        if direction == "upstream":
            # 返回当前表直接依赖的父表
            return graph.get(table_name, [])
        elif direction == "downstream":
            # 返回所有依赖当前表的子表
            downstream = []
            for child, parents in graph.items():
                if table_name in parents:
                    downstream.append(child)
            return downstream
        else:
            raise ValueError("direction 必须为 'upstream' 或 'downstream'")

    # ------------------------------------------------------------------
    # 业务术语的血缘（映射逻辑中引用的表和列）
    # ------------------------------------------------------------------
    def trace_business_term(self, term: str) -> Dict[str, Any]:
        """
        分析业务术语对应的计算逻辑中涉及的数据表/字段
        """
        bt = BusinessTerm.query.filter_by(term=term).first()
        if not bt:
            return {"error": f"业务术语 '{term}' 不存在"}

        # mapping_logic 中可能包含表名和列名的文本，用简单解析提取
        logic = bt.mapping_logic or ""
        tables_used = set()
        columns_used = set()
        # 尝试查找所有 "表名.列名" 或单独单词（可能是列名）
        import re
        # 匹配 table.column 模式
        matches = re.findall(r'(\w+)\.(\w+)', logic)
        for tbl, col in matches:
            tables_used.add(tbl)
            columns_used.add(f"{tbl}.{col}")
        # 匹配独立单词作为潜在列名（粗略）
        words = re.findall(r'\b\w+\b', logic)
        for w in words:
            # 如果词存在于某个表的列中，也视为依赖
            col = ColumnMeta.query.filter_by(column_name=w).first()
            if col:
                tbl = TableMeta.query.get(col.table_id)
                if tbl:
                    tables_used.add(tbl.table_name)
                    columns_used.add(f"{tbl.table_name}.{w}")

        return {
            "term": term,
            "definition": bt.definition,
            "mapping_logic": logic,
            "tables": list(tables_used),
            "columns": list(columns_used)
        }

    # ------------------------------------------------------------------
    # 完整分析报告
    # ------------------------------------------------------------------
    def generate_lineage_report(self, metric_names: List[str]) -> List[Dict]:
        """为一组指标生成完整的血缘报告"""
        report = []
        for name in metric_names:
            report.append(self.trace_metric(name))
        return report