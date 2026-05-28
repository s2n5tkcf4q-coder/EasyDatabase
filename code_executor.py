# code_executor.py
import os
import subprocess
import tempfile
import logging
import shlex
import platform
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# 默认白名单模块（可从配置文件覆盖）
DEFAULT_ALLOWED_MODULES = [
    'pandas', 'numpy', 'matplotlib', 'seaborn', 'scipy', 'sklearn',
    'json', 'datetime', 'math', 'statistics', 'os', 'sys', 'io'
]

# 代码执行包装模板，插入模块限制钩子
RESTRICTED_WRAPPER = """
import builtins
_original_import = builtins.__import__
_allowed_modules = {allowed_modules}
def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    top_level = name.split('.')[0]
    if top_level not in _allowed_modules:
        raise ImportError(f"模块 '{{name}}' 不在允许列表中")
    return _original_import(name, globals, locals, fromlist, level)
builtins.__import__ = _restricted_import

# 设置图表输出目录环境变量
import os as _os
_CHART_OUTPUT_DIR = r'{output_dir}'
_os.environ['CHART_OUTPUT_PATH'] = _CHART_OUTPUT_DIR

# 用户代码开始
{user_code}
"""


class CodeExecutor:
    """沙箱代码解释器：安全执行 Python 代码，支持生成图表和统计数据"""

    def __init__(self, allowed_modules: Optional[List[str]] = None,
                 default_timeout: int = 30,
                 default_memory_mb: int = 512):
        self.allowed_modules = allowed_modules or DEFAULT_ALLOWED_MODULES
        self.timeout = default_timeout
        self.memory_mb = default_memory_mb

    def execute(self,
                code: str,
                output_dir: Optional[str] = None,
                timeout: Optional[int] = None,
                memory_mb: Optional[int] = None) -> Dict[str, Any]:
        """
        在沙箱中执行 Python 代码
        :param code: Python 代码字符串
        :param output_dir: 图表输出目录，None 则创建临时目录
        :param timeout: 超时秒数，None 则使用默认值
        :param memory_mb: 内存限制 MB，None 则使用默认值（仅 Linux）
        :return: {"output": stdout, "error": 错误信息, "files": 生成的文件路径列表}
        """
        timeout = timeout or self.timeout
        memory_mb = memory_mb or self.memory_mb

        # 创建输出目录
        if output_dir is None:
            temp_dir = tempfile.mkdtemp(prefix='code_exec_')
            output_dir = temp_dir
        else:
            os.makedirs(output_dir, exist_ok=True)

        # 构造完整的受限脚本
        allowed_modules_str = str(self.allowed_modules)
        wrapped_code = RESTRICTED_WRAPPER.format(
            allowed_modules=allowed_modules_str,
            output_dir=output_dir,
            user_code=code
        )

        # 写入临时脚本文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            script_path = f.name
            f.write(wrapped_code)

        try:
            # 执行子进程
            cmd = [self._get_python_executable(), script_path]
            # 设置内存限制（仅 Unix）
            preexec_fn = None
            if platform.system() != 'Windows' and memory_mb > 0:
                import resource
                def set_limits():
                    # 内存限制（软限制，达到后抛出 MemoryError）
                    mem_bytes = memory_mb * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                preexec_fn = set_limits

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=preexec_fn,
                encoding='utf-8',
                errors='replace'
            )

            stdout = process.stdout
            stderr = process.stderr
            exit_code = process.returncode

            # 收集生成的图表文件
            files = self._collect_output_files(output_dir)

            # 构建返回结果
            result = {
                "output": stdout,
                "error": stderr if stderr and exit_code != 0 else None,
                "exit_code": exit_code,
                "files": files,
                "data": None  # 如果有表格数据可填充，这里暂用 None
            }

            if stderr and exit_code == 0:
                # 非零退出但有 stderr 才报错，否则可能只是警告
                logger.warning(f"代码执行有 stderr 输出（退出码0）: {stderr[:200]}")
            if exit_code != 0:
                result["error"] = stderr.strip() if stderr else f"进程退出码 {exit_code}"
                logger.error(f"代码执行失败: {result['error']}")

            return result

        except subprocess.TimeoutExpired:
            return {"output": "", "error": f"代码执行超时 ({timeout} 秒)", "exit_code": -1, "files": [], "data": None}
        except Exception as e:
            logger.exception("代码执行异常")
            return {"output": "", "error": str(e), "exit_code": -2, "files": [], "data": None}
        finally:
            # 清理临时脚本
            try:
                os.unlink(script_path)
            except OSError:
                pass
            # 如果 output_dir 是临时目录且无文件，则清理
            if output_dir and output_dir.startswith(tempfile.gettempdir()):
                if not os.listdir(output_dir):
                    try:
                        os.rmdir(output_dir)
                    except OSError:
                        pass

    @staticmethod
    def _get_python_executable() -> str:
        """获取 Python 解释器路径（与当前相同的解释器）"""
        return shlex.quote(sys.executable) if hasattr(sys, 'executable') else 'python'

    @staticmethod
    def _collect_output_files(directory: str) -> List[str]:
        """收集指定目录下的所有生成文件（如图片）"""
        files = []
        if os.path.exists(directory):
            for fname in os.listdir(directory):
                filepath = os.path.join(directory, fname)
                if os.path.isfile(filepath):
                    files.append(filepath)
        return files