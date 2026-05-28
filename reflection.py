# reflection.py
import json
import logging
from typing import Dict, Optional

from llm_client import LLMClient

logger = logging.getLogger(__name__)

REFLECTION_SYSTEM_PROMPT = """你是一个数据库查询调试专家。用户的 SQL 查询执行后出现了错误或者没有得到预期结果。
你的任务是：
1. 分析错误原因，可能是语法错误、表名/字段名错误、逻辑错误、数据类型不匹配等。
2. 根据原始业务问题、错误信息和失败的 SQL，生成一条修正后的 SQL 查询。

请严格按如下 JSON 格式返回，不要包含其他文字：
{
  "analysis": "对错误原因的分析说明",
  "sql": "修正后的完整 SQL 语句"
}

如果无法确定修正方案，可以将 "sql" 设为空字符串，并在 "analysis" 中说明原因。
"""


class Reflection:
    """反思与修正器，负责分析 SQL 执行错误并尝试自动修正"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def self_correct(self,
                     error_message: str,
                     user_question: str,
                     step: dict,
                     sql: str) -> Dict[str, str]:
        """
        根据错误信息、用户问题和失败的 SQL，生成修正后的 SQL 和分析

        :param error_message: 执行错误描述（如异常信息或结果异常提示）
        :param user_question: 用户原始问题
        :param step: 当前执行步骤的字典（包含 id, description, tool, params 等）
        :param sql: 失败的 SQL 语句
        :return: 字典，包含 'analysis' 和 'sql'
        """
        context_info = f"""用户原始问题: {user_question}
当前步骤: {step.get('description', '未知')}
工具: {step.get('tool', 'text_to_sql')}
步骤参数: {json.dumps(step.get('params', {}), ensure_ascii=False)}
失败的 SQL 语句:
{sql}

错误信息:
{error_message}
"""
        messages = [
            {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
            {"role": "user", "content": context_info}
        ]

        try:
            response = self.llm.chat(messages, temperature=0.3)
            logger.debug(f"反思修正 LLM 响应: {response[:500]}...")

            correction = self._parse_response(response)
            logger.info(f"修正分析: {correction.get('analysis', '')[:200]}")
            return correction
        except Exception as e:
            logger.error(f"反思修正失败: {str(e)}")
            # 返回一个安全回退，不提供 SQL，交由后续逻辑处理
            return {
                "analysis": f"自动修正失败: {str(e)}",
                "sql": ""
            }

    def _parse_response(self, text: str) -> Dict[str, str]:
        """从 LLM 响应中提取 JSON 修正结果"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取代码块中的 JSON
            import re
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1).strip())
                except json.JSONDecodeError:
                    # 尝试提取第一个 { 到最后一个 }
                    start = text.find('{')
                    end = text.rfind('}')
                    if start != -1 and end != -1:
                        try:
                            data = json.loads(text[start:end+1])
                        except json.JSONDecodeError:
                            raise ValueError("无法解析反思修正结果为 JSON")
                    else:
                        raise ValueError("响应中未找到 JSON 对象")
            else:
                start = text.find('{')
                end = text.rfind('}')
                if start != -1 and end != -1:
                    try:
                        data = json.loads(text[start:end+1])
                    except json.JSONDecodeError:
                        raise ValueError("无法解析反思修正结果为 JSON")
                else:
                    raise ValueError("响应中未找到 JSON 对象")

        if not isinstance(data, dict):
            raise ValueError("修正结果必须是字典")
        if "analysis" not in data:
            data["analysis"] = "未提供分析"
        if "sql" not in data:
            data["sql"] = ""
        return data