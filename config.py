# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ----- 基础配置 -----
    DEBUG = True
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-secret-key-change-in-production'
    HOST = '0.0.0.0'
    PORT = 8081

    # ----- 数据库配置 -----
    # 默认使用 SQLite 存储系统数据（用户、配置、日志、记忆）
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'data', 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ----- 会话配置 -----
    # 永久会话有效期（秒），设置为 1 小时
    PERMANENT_SESSION_LIFETIME = 3600

    # ----- 文件输出路径 -----
    OUTPUT_FOLDER = os.path.join(basedir, 'static', 'outputs')
    # 生成文件的下载链接有效期（秒），默认 1 小时
    OUTPUT_URL_TIMEOUT = 3600

    # ----- LLM 基础配置 -----
    LLM_MODE = os.environ.get('LLM_MODE', 'api')  # 'api' 或 'ollama'

    # OpenAI 兼容 API 配置
    LLM_API_URL = os.environ.get('LLM_API_URL', 'https://api.openai.com/v1')
    LLM_API_KEY = os.environ.get('LLM_API_KEY', 'your-api-key-here')
    LLM_API_CHAT_MODEL = 'gpt-4o'
    LLM_API_EMBEDDING_MODEL = 'text-embedding-3-small'

    # Ollama 配置
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_CHAT_MODEL = 'llama3.1:latest'
    OLLAMA_EMBEDDING_MODEL = 'nomic-embed-text'

    # ----- LLM 可调参数（默认值，可在管理页面修改并存入数据库）-----
    LLM_SYSTEM_PROMPT = "你是一个企业级数据分析助手，能够理解复杂业务逻辑，生成准确的SQL或代码。"
    LLM_SIMILARITY_THRESHOLD = 0.75       # 向量相似度阈值
    LLM_SIMILARITY_WEIGHT = 0.8           # 向量相似度权重（与关键词匹配结合时）
    LLM_TOP_N = 5                         # 向量检索返回的 top N 条记忆
    LLM_TEMPERATURE = 0.1                 # 生成温度
    LLM_TOP_P = 0.9                       # 核采样
    LLM_PRESENCE_PENALTY = 0.0
    LLM_FREQUENCY_PENALTY = 0.0
    LLM_MAX_TOKENS = 2048
    LLM_ENABLE_LONG_TERM_MEMORY = True
    LLM_SHORT_TERM_MEMORY_ROUNDS = 10     # 短期记忆保留的最大对话轮数

    # ----- 沙箱代码执行配置 -----
    CODE_EXEC_TIMEOUT = 30                # 代码最大执行时间（秒）
    CODE_EXEC_MEMORY_MB = 512             # 最大内存限制
    CODE_ALLOWED_MODULES = [              # 白名单模块
        'pandas', 'numpy', 'matplotlib', 'seaborn', 'scipy', 'sklearn',
        'json', 'datetime', 'math', 'statistics'
    ]

    # ----- 知识图谱配置 -----
    # 是否在启动时自动扫描目标数据库元数据并导入知识图谱
    AUTO_SYNC_METADATA = False

    # ----- 日志配置 -----
    LOG_LEVEL = 'DEBUG'
    LOG_FILE = os.path.join(basedir, 'logs', 'app.log')
    LOG_MAX_BYTES = 10 * 1024 * 1024      # 10 MB
    LOG_BACKUP_COUNT = 10

    # ----- 其他 -----
    # 验证码长度
    CAPTCHA_LENGTH = 4
    # 文件上传大小限制（可选）
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB