# text_to_sql.py
import json
import logging
from typing import List, Dict, Optional, Any

import sqlalchemy
from sqlalchemy import create_engine, text

from models import DatabaseConnection, SysConfig
from llm_client import LLMClient
from knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# ---------- SQL 骨架模板 ----------
SQL_TEMPLATES = {
    "aggregate": """
SELECT {select_columns}
FROM {tables}
WHERE {where_clauses}
GROUP BY {group_by}
ORDER BY {order_by}
LIMIT {limit}
""",
    "trend": """
SELECT {time_column}, {select_columns}
FROM {tables}
WHERE {time_filter} AND {where_clauses}
GROUP BY {time_column}, {group_by}
ORDER BY {time_column} ASC
LIMIT {limit}
""",
    "detail": """
SELECT {select_columns}
FROM {tables}
WHERE {where_clauses}
ORDER BY {order_by}
LIMIT {limit}
"""
}

SQL_GENERATION_SYSTEM_PROMPT = """你是一个将自然语言分析需求转换为SQL查询结构的专家。你将收到用户的查询、可用表及字段的信息，你需要输出一个JSON，描述SQL查询的组成部分。

请严格遵循以下JSON格式，不要包含其他文本：
{
  "intent": "aggregate|trend|detail",
  "tables": ["表名1", "表名2"],
  "joins": ["JOIN条件1", "JOIN条件2"],   // 如 "orders.user_id = users.id"
  "select_columns": [
    {"expression": "列名或聚合表达式", "alias": "别名（可选）"}
  ],
  "where_clauses": [
    {"column": "列名", "operator": "= | > | < | LIKE | IN | BETWEEN", "value": "具体值或占位符"}
  ],
  "group_by": ["列名"],
  "order_by": ["列名 ASC|DESC"],
  "time_filter": {
    "column": "时间列名",
    "start": "开始时间（可省略）",
    "end": "结束时间（可省略）"
  },
  "limit": 1000
}

注意：
- 表名和列名必须严格使用下方提供的元数据中的名称，不能编造。
- 如果查询涉及多表，请在 joins 中指定连接条件。
- 对于聚合查询，select_columns 中的表达式可以包含 SUM, COUNT, AVG, MAX, MIN 等函数。
- 时间过滤条件放入 time_filter，不要放在 where_clauses 中。
- 如果用户没有指定 LIMIT，默认设为 1000。
"""


class TextToSQL:
    """负责将自然语言描述转化为 SQL 并执行"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate_and_execute(
        self,
        step: Dict[str, Any],
        kg: KnowledgeGraph,
        metadata_context: Optional[List[Dict]] = None,
        correction: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        根据执行步骤生成并执行 SQL，返回结果字典
        :param step: 任务步骤（包含 description, query, params）
        :param kg: 知识图谱实例，用于查询表/字段元数据（当 metadata_context 为空时使用）
        :param metadata_context: 从知识检索步骤获得的真实表/字段信息列表，
                                 格式: [{"table": "...", "columns": [{"name":...,"type":...}, ...]}, ...]
        :param correction: 反思修正后的结果，若提供则直接使用其中的 SQL
        :return: {"data": 结果列表, "sql": 生成的 SQL, "row_count": 行数, "error": 错误信息或 None}
        """
        try:
            if correction and correction.get("sql"):
                # 使用修正后的 SQL
                sql = correction["sql"]
                logger.info("使用修正后的 SQL")
            else:
                # 正常生成 SQL，传入 metadata_context
                sql = self._generate_sql(step, kg, metadata_context)
                logger.info(f"生成 SQL: {sql[:200]}...")

            # 执行 SQL
            data, row_count = self._execute_sql(sql)
            return {
                "data": data,
                "sql": sql,
                "row_count": row_count,
                "error": None
            }
        except Exception as e:
            logger.error(f"SQL 生成或执行失败: {str(e)}")
            return {
                "data": None,
                "sql": None,
                "row_count": 0,
                "error": str(e)
            }

    def _generate_sql(self,
                      step: Dict[str, Any],
                      kg: KnowledgeGraph,
                      metadata_context: Optional[List[Dict]] = None) -> str:
        """
        使用骨架+插槽方法生成 SQL
        :param metadata_context: 优先使用的表/字段元数据，若为空则从知识图谱获取全量
        """
        # 1. 确定使用的表元数据
        if metadata_context:
            # 使用传入的已检索元数据
            all_tables = metadata_context
            logger.debug(f"使用传入的元数据上下文，包含 {len(all_tables)} 个表")
        else:
            # 回退：从知识图谱获取全量
            all_tables = kg.get_all_tables_with_columns()
            if not all_tables:
                logger.warning("知识图谱为空，无法生成可靠 SQL")
                raise ValueError("知识图谱中没有可用的表元数据，请先同步元数据。")

        # 构造元数据描述文本
        schema_desc = self._build_schema_description(all_tables)

        # 2. 构造 LLM 提示
        user_query = step.get("query") or step.get("description", "")
        messages = [
            {"role": "system", "content": SQL_GENERATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"数据库表结构：\n{schema_desc}\n\n用户分析需求：{user_query}"}
        ]

        # 3. 调用 LLM 获取结构化查询成分
        response = self.llm.chat(messages, temperature=0.1)
        logger.debug(f"LLM SQL 成分响应: {response[:300]}")
        sql_components = self._parse_response(response)

        # 4. 校验表名、列名是否在元数据中，防止注入或幻觉
        self._validate_components(sql_components, all_tables)

        # 5. 根据模板和成分拼接最终 SQL
        sql = self._fill_template(sql_components)
        return sql

    def _build_schema_description(self, tables: List[Dict]) -> str:
        """将表元数据转换为文本"""
        lines = []
        for tbl in tables:
            lines.append(f"表名: {tbl['table']}")
            for col in tbl.get('columns', []):
                lines.append(f"  - {col['name']} ({col.get('type', 'string')}) {col.get('business_name', '')}")
        return "\n".join(lines)

    def _parse_response(self, text: str) -> Dict:
        """从 LLM 响应中提取 JSON"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            # 尝试提取代码块
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if match:
                return json.loads(match.group(1).strip())
            # 提取第一个 { 到最后一个 }
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
            raise ValueError("无法从 LLM 响应中解析 JSON")

    def _validate_components(self, components: Dict, table_meta: List[Dict]):
        """检查表名和列名是否合法"""
        valid_tables = {t['table'] for t in table_meta}
        valid_columns = set()
        for t in table_meta:
            for c in t.get('columns', []):
                valid_columns.add(c['name'])
                # 也允许 "表名.列名" 形式
                valid_columns.add(f"{t['table']}.{c['name']}")

        # 检查 tables
        for table in components.get("tables", []):
            if table not in valid_tables:
                raise ValueError(f"无效的表名: {table}")

        # 检查 select_columns 中的列
        for item in components.get("select_columns", []):
            expr = item.get("expression", "")
            # 简单提取可能的列名（去除聚合函数、括号等）
            cols = self._extract_column_names(expr)
            for col in cols:
                if col not in valid_columns and not col.startswith("*") and not col.isdigit():
                    raise ValueError(f"无效的列名或表达式: {col}")

        # 检查 where_clauses
        for cond in components.get("where_clauses", []):
            col = cond.get("column", "")
            if col and col not in valid_columns:
                raise ValueError(f"WHERE 子句中的无效列名: {col}")

        # 检查 group_by, order_by, time_filter 列
        for col in components.get("group_by", []):
            if col not in valid_columns:
                raise ValueError(f"GROUP BY 中的无效列名: {col}")
        for col in components.get("order_by", []):
            real_col = col.split()[0] if ' ' in col else col
            if real_col not in valid_columns:
                raise ValueError(f"ORDER BY 中的无效列名: {col}")
        time_col = components.get("time_filter", {}).get("column")
        if time_col and time_col not in valid_columns:
            raise ValueError(f"时间过滤列无效: {time_col}")

    def _extract_column_names(self, expression: str) -> List[str]:
        """从 SQL 表达式中提取裸列名（去除函数）"""
        import re
        # 匹配可能的列名（包含表名.列名形式）
        words = re.findall(r'[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)?', expression)
        return words

    def _fill_template(self, components: Dict) -> str:
        """根据组件填充 SQL 骨架"""
        intent = components.get("intent", "detail")
        template = SQL_TEMPLATES.get(intent, SQL_TEMPLATES["detail"])

        # 构建 SELECT 部分
        select_parts = []
        for item in components.get("select_columns", []):
            expr = item.get("expression", "*")
            alias = item.get("alias")
            if alias:
                select_parts.append(f"{expr} AS {alias}")
            else:
                select_parts.append(expr)
        select_str = ", ".join(select_parts) if select_parts else "*"

        # 构建 FROM 部分（含 JOIN）
        tables = components.get("tables", [])
        if not tables:
            raise ValueError("未指定数据表")
        from_str = tables[0]
        joins = components.get("joins", [])
        if joins:
            from_str += " " + " ".join(joins)

        # WHERE 部分
        where_parts = []
        for cond in components.get("where_clauses", []):
            col = cond.get("column")
            op = cond.get("operator", "=")
            val = cond.get("value")
            # 简单加引号（生产中应参数化）
            if isinstance(val, str) and not val.isdigit():
                val_quoted = f"'{val}'"
            else:
                val_quoted = str(val)
            where_parts.append(f"{col} {op} {val_quoted}")
        # 时间过滤
        time_filter = components.get("time_filter")
        if time_filter and time_filter.get("column"):
            col = time_filter["column"]
            start = time_filter.get("start")
            end = time_filter.get("end")
            if start and end:
                where_parts.append(f"{col} BETWEEN '{start}' AND '{end}'")
            elif start:
                where_parts.append(f"{col} >= '{start}'")
            elif end:
                where_parts.append(f"{col} <= '{end}'")
        where_str = " AND ".join(where_parts) if where_parts else "1=1"

        # GROUP BY
        group_by = components.get("group_by", [])
        group_str = ", ".join(group_by) if group_by else "1"

        # ORDER BY
        order_by = components.get("order_by", [])
        order_str = ", ".join(order_by) if order_by else "1"

        # LIMIT
        limit = components.get("limit", 1000)

        # 时间列（趋势模板需要）
        time_column = time_filter.get("column") if time_filter else "id"

        sql = template.format(
            select_columns=select_str,
            tables=from_str,
            where_clauses=where_str,
            group_by=group_str,
            order_by=order_str,
            limit=limit,
            time_column=time_column,
            time_filter=where_str
        )
        # 清理多余空白
        import re
        sql = re.sub(r'\n\s*\n', '\n', sql).strip()
        return sql

    def _execute_sql(self, sql: str) -> (List[Dict], int):
        """执行 SQL 并返回数据列表和行数"""
        # 获取默认数据库连接
        conn_info = DatabaseConnection.query.filter_by(is_active=True).first()
        if not conn_info:
            raise RuntimeError("没有可用的数据库连接，请先配置数据库连接。")

        engine = create_engine(conn_info.connection_string)
        try:
            with engine.connect() as connection:
                result = connection.execute(text(sql))
                rows = result.fetchall()
                # 转换为字典列表
                columns = result.keys()
                data = [dict(zip(columns, row)) for row in rows]
                row_count = len(data)
                logger.info(f"SQL 执行成功，返回 {row_count} 行")
                return data, row_count
        finally:
            engine.dispose()