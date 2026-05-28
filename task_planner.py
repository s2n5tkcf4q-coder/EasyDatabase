# task_planner.py
import json
import logging
from typing import List, Dict, Optional

from llm_client import LLMClient

logger = logging.getLogger(__name__)

# 任务规划系统提示词，指导 LLM 输出符合要求的步骤 JSON
PLANNER_SYSTEM_PROMPT = """你是一个企业数据分析任务规划专家。你的职责是接收用户的自然语言分析需求，并将其分解为有序的执行步骤。

【重要规则】
1. 如果任务涉及查询数据库（text_to_sql），必须在所有查询步骤之前，先使用 knowledge_retrieval 工具检索相关表、字段和指标定义。
2. 后续的 text_to_sql 步骤中，表名、字段名必须严格使用 knowledge_retrieval 返回的真实名称，严禁编造表名或字段名。如果查询描述中包含了具体表名，也应通过 knowledge_retrieval 确认是否存在。
3. 如果 knowledge_retrieval 未能找到相关元数据，应生成一个步骤提示用户确认或补充元数据。
4. 每个 text_to_sql 步骤的 depends_on 列表必须包含至少一个 knowledge_retrieval 步骤的 id（可以是间接依赖），以确保元数据已经获取。

每个步骤需要指定以下字段：
- id: 步骤序号 (整数，从1开始)
- description: 该步骤的中文描述
- tool: 使用的工具，可选值: "text_to_sql" (生成并执行SQL查询), "code_executor" (执行Python代码进行统计或绘图), "knowledge_retrieval" (从知识图谱获取信息，如表结构、指标口径)
- query: 当工具为 knowledge_retrieval 时，表示对知识图谱的查询内容；当工具为 text_to_sql 时，表示简化的查询意图描述；当工具为 code_executor 时可为空
- depends_on: 依赖的步骤id列表 (若无依赖则为空数组)
- params: 附加参数字典，如指定数据源、时间范围等。

输出必须是一个严格的 JSON 对象，包含 "steps" 数组，不要包含其他文字。

示例：
用户：分析近三年双11的复购率趋势
输出：
{
  "steps": [
    {"id": 1, "description": "获取近三年双11的具体日期", "tool": "knowledge_retrieval", "query": "近三年双11日期", "depends_on": [], "params": {}},
    {"id": 2, "description": "计算每年双11期间的新客户数量", "tool": "text_to_sql", "query": "统计每年双11期间首次购买的用户数", "depends_on": [1], "params": {"time_range": "双11日期"}},
    {"id": 3, "description": "计算每年双11期间的复购率", "tool": "text_to_sql", "query": "计算每年双11期间复购用户占比", "depends_on": [2], "params": {}},
    {"id": 4, "description": "生成复购率趋势图", "tool": "code_executor", "query": "", "depends_on": [3], "params": {"chart_type": "line"}}
  ]
}
"""


class TaskPlanner:
    """任务规划器，将用户问题分解为执行计划"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def plan(self, user_message: str, context: Optional[List[Dict]] = None) -> Dict:
        """
        根据用户消息和对话上下文生成步骤计划
        :param user_message: 用户最新问题
        :param context: 之前的对话上下文 (role/content 列表)
        :return: 包含 'steps' 键的字典
        """
        messages = [{"role": "system", "content": PLANNER_SYSTEM_PROMPT}]

        # 如果提供了上下文，可选择性加入最近几轮，帮助理解指代消解
        if context:
            # 取最后6条上下文（3轮对话）
            recent_context = context[-6:]
            messages.extend(recent_context)

        # 添加用户当前问题
        messages.append({"role": "user", "content": user_message})

        try:
            response = self.llm.chat(messages, temperature=0.2)  # 较低温度确保稳定输出
            logger.debug(f"任务规划 LLM 响应: {response[:500]}...")

            # 尝试提取 JSON
            plan = self._parse_response(response)
            self._validate_plan(plan)
            return plan
        except Exception as e:
            logger.error(f"任务规划失败: {str(e)}")
            # 返回一个默认的简单计划，避免系统完全不可用
            fallback_plan = {
                "steps": [
                    {
                        "id": 1,
                        "description": "直接查询相关数据",
                        "tool": "text_to_sql",
                        "query": user_message,
                        "depends_on": [],
                        "params": {}
                    }
                ]
            }
            return fallback_plan

    def _parse_response(self, text: str) -> Dict:
        """从 LLM 响应中提取 JSON 计划"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取被代码块包裹的 JSON
        import re
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试提取第一个 { 到最后一个 } 的内容
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        raise ValueError("无法从 LLM 响应中解析出有效的 JSON 计划")

    def _validate_plan(self, plan: Dict):
        """验证计划格式，并确保数据库查询步骤依赖知识检索"""
        if not isinstance(plan, dict) or "steps" not in plan:
            raise ValueError("计划必须包含 'steps' 键")

        steps = plan["steps"]
        if not isinstance(steps, list) or len(steps) == 0:
            raise ValueError("计划中的 'steps' 必须是非空列表")

        # 收集所有步骤的 id 和工具信息
        step_map = {s["id"]: s for s in steps}
        knowledge_step_ids = {s["id"] for s in steps if s["tool"] == "knowledge_retrieval"}

        # 基本字段校验
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("每个步骤必须是字典")
            required_keys = {"id", "description", "tool", "depends_on"}
            if not required_keys.issubset(step.keys()):
                raise ValueError(f"步骤缺少必要字段: {required_keys - set(step.keys())}")
            if step["tool"] not in ["text_to_sql", "code_executor", "knowledge_retrieval"]:
                raise ValueError(f"不支持的工具: {step['tool']}")

        # 检查是否有 text_to_sql 但没有任何 knowledge_retrieval 步骤
        has_text_to_sql = any(s["tool"] == "text_to_sql" for s in steps)
        if has_text_to_sql and not knowledge_step_ids:
            raise ValueError("包含数据库查询的任务必须至少有一个知识检索步骤获取表结构")

        # 检查每个 text_to_sql 步骤是否显式依赖至少一个 knowledge_retrieval 步骤
        for step in steps:
            if step["tool"] == "text_to_sql":
                # 直接依赖中包含 knowledge 步骤的 id？
                direct_dep_has_knowledge = any(
                    dep_id in knowledge_step_ids for dep_id in step.get("depends_on", [])
                )
                if not direct_dep_has_knowledge:
                    # 允许间接依赖：递归检查所有依赖的依赖中是否包含 knowledge 步骤
                    visited = set()
                    stack = list(step.get("depends_on", []))
                    indirect_has_knowledge = False
                    while stack:
                        dep_id = stack.pop()
                        if dep_id in visited:
                            continue
                        visited.add(dep_id)
                        if dep_id in knowledge_step_ids:
                            indirect_has_knowledge = True
                            break
                        dep_step = step_map.get(dep_id)
                        if dep_step:
                            stack.extend(dep_step.get("depends_on", []))
                    if not indirect_has_knowledge:
                        raise ValueError(
                            f"步骤 {step['id']} ({step['description']}) 没有显式或间接依赖任何知识检索步骤，"
                            "必须先将 knowledge_retrieval 步骤加入依赖列表"
                        )

        # 校验依赖的有效性（引用的 id 必须存在）
        for step in steps:
            for dep_id in step.get("depends_on", []):
                if dep_id not in step_map:
                    raise ValueError(f"步骤 {step['id']} 依赖的步骤 {dep_id} 不存在")