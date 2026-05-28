# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # ----- 基础配置 -----
    DEBUG = True
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-secret-key-change-in-production'
    HOST = '0.0.0.0'
    PORT = 5000

    # ----- 数据库配置 -----
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'data', 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ----- 会话配置 -----
    PERMANENT_SESSION_LIFETIME = 3600

    # ----- 文件输出路径 -----
    OUTPUT_FOLDER = os.path.join(basedir, 'static', 'outputs')
    OUTPUT_URL_TIMEOUT = 3600

    # ----- LLM 基础配置 -----
    LLM_MODE = os.environ.get('LLM_MODE', 'api')

    # OpenAI 兼容 API 配置
    LLM_API_URL = os.environ.get('LLM_API_URL', 'https://api.openai.com/v1')
    LLM_API_KEY = os.environ.get('LLM_API_KEY', 'your-api-key-here')
    LLM_API_CHAT_MODEL = 'gpt-4o'
    LLM_API_EMBEDDING_MODEL = 'text-embedding-3-small'

    # Ollama 配置
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_CHAT_MODEL = 'llama3.1:latest'
    OLLAMA_EMBEDDING_MODEL = 'nomic-embed-text'

    # ----- LLM 可调参数 -----
    LLM_SYSTEM_PROMPT = "你是一个企业级数据分析助手，能够理解复杂业务逻辑，生成准确的SQL或代码。"
    LLM_SIMILARITY_THRESHOLD = 0.75
    LLM_SIMILARITY_WEIGHT = 0.8
    LLM_TOP_N = 5
    LLM_TEMPERATURE = 0.1
    LLM_TOP_P = 0.9
    LLM_PRESENCE_PENALTY = 0.0
    LLM_FREQUENCY_PENALTY = 0.0
    LLM_MAX_TOKENS = 2048
    LLM_ENABLE_LONG_TERM_MEMORY = True
    LLM_SHORT_TERM_MEMORY_ROUNDS = 10

    # ----- 沙箱代码执行配置 -----
    CODE_EXEC_TIMEOUT = 30
    CODE_EXEC_MEMORY_MB = 512
    CODE_ALLOWED_MODULES = [
        'pandas', 'numpy', 'matplotlib', 'seaborn', 'scipy', 'sklearn',
        'json', 'datetime', 'math', 'statistics'
    ]

    # ----- 知识图谱配置 -----
    AUTO_SYNC_METADATA = False

    # ----- 日志配置 -----
    LOG_LEVEL = 'DEBUG'
    LOG_FILE = os.path.join(basedir, 'logs', 'app.log')
    LOG_MAX_BYTES = 10 * 1024 * 1024
    LOG_BACKUP_COUNT = 10

    # ----- 其他 -----
    CAPTCHA_LENGTH = 4
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
