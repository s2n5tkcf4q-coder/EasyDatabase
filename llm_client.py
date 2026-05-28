# llm_client.py
import json
import logging
from typing import List, Dict, Optional, Union

import requests
from flask import current_app

from models import SysConfig

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """LLM 客户端异常"""
    pass


class BaseLLMBackend:
    """后端基类，定义接口"""
    def chat(self, messages: List[Dict], **kwargs) -> str:
        raise NotImplementedError

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        raise NotImplementedError

    def test_connection(self) -> (bool, str):
        raise NotImplementedError


class APIBackend(BaseLLMBackend):
    """OpenAI 兼容 API 后端"""
    def __init__(self, base_url: str, api_key: str, chat_model: str, embedding_model: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.chat_endpoint = f"{self.base_url}/chat/completions"
        self.embed_endpoint = f"{self.base_url}/embeddings"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def chat(self, messages: List[Dict], **kwargs) -> str:
        # 合并传入参数与数据库全局参数
        params = self._get_chat_params()
        # kwargs 可以覆盖部分参数（如 temperature 等，但通常由调用方传入）
        params.update(kwargs)
        payload = {
            "model": self.chat_model,
            "messages": messages,
            **params
        }
        try:
            resp = requests.post(self.chat_endpoint, headers=self._headers(), json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return data['choices'][0]['message']['content']
        except requests.exceptions.RequestException as e:
            logger.error(f"API 聊天请求失败: {e}")
            raise LLMClientError(f"API 请求失败: {str(e)}")
        except (KeyError, IndexError) as e:
            logger.error(f"API 响应格式错误: {e}")
            raise LLMClientError("API 返回格式异常")

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]
        payload = {
            "model": self.embedding_model,
            "input": texts
        }
        try:
            resp = requests.post(self.embed_endpoint, headers=self._headers(), json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            # 按输入顺序返回向量
            embeddings = sorted(data['data'], key=lambda x: x['index'])
            return [item['embedding'] for item in embeddings]
        except requests.exceptions.RequestException as e:
            logger.error(f"Embedding 请求失败: {e}")
            raise LLMClientError(f"Embedding 请求失败: {str(e)}")
        except (KeyError, IndexError) as e:
            logger.error(f"Embedding 响应格式错误: {e}")
            raise LLMClientError("Embedding 响应格式异常")

    def test_connection(self) -> (bool, str):
        """发送简单消息测试连接"""
        test_messages = [{"role": "user", "content": "ping"}]
        try:
            params = self._get_chat_params()
            payload = {
                "model": self.chat_model,
                "messages": test_messages,
                "max_tokens": 10,
                **params
            }
            resp = requests.post(self.chat_endpoint, headers=self._headers(), json=payload, timeout=20)
            if resp.status_code == 200:
                return True, "连接成功"
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    def _get_chat_params(self) -> Dict:
        """从数据库获取调参参数（不覆盖 messages），用于 chat 和 test"""
        # 注意：这里动态读取，每次调用可能略有延迟，但可确保实时配置生效
        try:
            temperature = float(SysConfig.get_config('LLM_TEMPERATURE', '0.1'))
            top_p = float(SysConfig.get_config('LLM_TOP_P', '0.9'))
            presence_penalty = float(SysConfig.get_config('LLM_PRESENCE_PENALTY', '0.0'))
            frequency_penalty = float(SysConfig.get_config('LLM_FREQUENCY_PENALTY', '0.0'))
            max_tokens = int(SysConfig.get_config('LLM_MAX_TOKENS', '2048'))
        except Exception as e:
            logger.warning(f"读取 LLM 参数失败，使用默认值: {e}")
            temperature = 0.1
            top_p = 0.9
            presence_penalty = 0.0
            frequency_penalty = 0.0
            max_tokens = 2048

        return {
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
            "max_tokens": max_tokens
        }


class OllamaBackend(BaseLLMBackend):
    """Ollama 本地后端"""
    def __init__(self, base_url: str, chat_model: str, embedding_model: str):
        self.base_url = base_url.rstrip('/')
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.chat_endpoint = f"{self.base_url}/api/chat"
        self.embed_endpoint = f"{self.base_url}/api/embeddings"

    def chat(self, messages: List[Dict], **kwargs) -> str:
        params = self._get_chat_params()
        # Ollama 的 chat 接口格式略有不同，需要将 messages 转换成其格式
        # 这里我们简化：直接发送 messages（假设 Ollama 最新版本支持 OpenAI 兼容格式）
        # 但 Ollama 原生 /api/chat 使用 "messages" 字段，和 OpenAI 一致
        payload = {
            "model": self.chat_model,
            "messages": messages,
            "stream": False,
            "options": params
        }
        # 移除 Ollama 不支持的参数
        for key in ['presence_penalty', 'frequency_penalty']:
            payload['options'].pop(key, None)
        try:
            resp = requests.post(self.chat_endpoint, json=payload, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            return data['message']['content']
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama 聊天请求失败: {e}")
            raise LLMClientError(f"Ollama 请求失败: {str(e)}")
        except (KeyError, IndexError) as e:
            logger.error(f"Ollama 响应格式错误: {e}")
            raise LLMClientError("Ollama 返回格式异常")

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]
        # Ollama embed API
        embeddings = []
        for text in texts:
            payload = {
                "model": self.embedding_model,
                "prompt": text  # Ollama 使用 prompt 字段
            }
            try:
                resp = requests.post(self.embed_endpoint, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                embeddings.append(data['embedding'])
            except requests.exceptions.RequestException as e:
                logger.error(f"Ollama Embedding 请求失败: {e}")
                raise LLMClientError(f"Ollama Embedding 请求失败: {str(e)}")
            except KeyError as e:
                logger.error(f"Ollama Embedding 响应格式错误: {e}")
                raise LLMClientError("Ollama Embedding 响应格式异常")
        return embeddings

    def test_connection(self) -> (bool, str):
        test_messages = [{"role": "user", "content": "ping"}]
        try:
            payload = {
                "model": self.chat_model,
                "messages": test_messages,
                "stream": False,
                "options": {"max_tokens": 5}
            }
            resp = requests.post(self.chat_endpoint, json=payload, timeout=300)
            if resp.status_code == 200:
                return True, "连接成功"
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    def _get_chat_params(self) -> Dict:
        try:
            temperature = float(SysConfig.get_config('LLM_TEMPERATURE', '0.1'))
            top_p = float(SysConfig.get_config('LLM_TOP_P', '0.9'))
            max_tokens = int(SysConfig.get_config('LLM_MAX_TOKENS', '2048'))
        except Exception as e:
            logger.warning(f"读取参数失败: {e}")
            temperature = 0.1
            top_p = 0.9
            max_tokens = 2048

        return {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": max_tokens
        }


class LLMClient:
    """统一的 LLM 客户端，根据数据库配置选择后端"""

    def __init__(self, config_override: Optional[Dict] = None):
        """
        初始化客户端，读取当前配置（支持从数据库动态读取）
        :param config_override: 可选，字典形式的配置覆盖，用于测试时绕过数据库
        """
        self._backend = None
        self._config_override = config_override

    def _get_config(self, key, default=None):
        # 优先使用传入的覆盖配置
        if self._config_override and key in self._config_override:
            return self._config_override[key]
        # 否则尝试从数据库读，最后回退到应用配置
        try:
            db_val = SysConfig.get_config(key)
            if db_val is not None:
                return db_val
        except Exception:
            pass
        try:
            return current_app.config.get(key, default)
        except RuntimeError:
            # 不在 Flask 应用上下文中，返回默认
            return default

    @property
    def backend(self) -> BaseLLMBackend:
        if self._backend is None:
            mode = self._get_config('LLM_MODE', 'api')
            if mode == 'api':
                api_url = self._get_config('LLM_API_URL', '')
                api_key = self._get_config('LLM_API_KEY', '')
                chat_model = self._get_config('LLM_API_CHAT_MODEL', 'gpt-4o')
                embedding_model = self._get_config('LLM_API_EMBEDDING_MODEL', 'text-embedding-3-small')
                self._backend = APIBackend(api_url, api_key, chat_model, embedding_model)
            elif mode == 'ollama':
                base_url = self._get_config('OLLAMA_BASE_URL', 'http://localhost:11434')
                chat_model = self._get_config('OLLAMA_CHAT_MODEL', 'llama3.1')
                embedding_model = self._get_config('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text')
                self._backend = OllamaBackend(base_url, chat_model, embedding_model)
            else:
                raise LLMClientError(f"不支持的 LLM 模式: {mode}")
        return self._backend

    def chat(self, messages: List[Dict], **kwargs) -> str:
        """调用聊天模型，返回文本响应"""
        return self.backend.chat(messages, **kwargs)

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """调用嵌入模型，返回向量列表"""
        return self.backend.embed(texts)

    def test_connection(self) -> (bool, str):
        """测试当前后端连接"""
        return self.backend.test_connection()

    def clear_backend(self):
        """强制清除后端实例，以便下次重新读取配置"""
        self._backend = None