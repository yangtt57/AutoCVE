from pathlib import Path
from typing import List, Optional, Union

from pydantic import AnyHttpUrl, validator
from pydantic_settings import BaseSettings


DEFAULT_MANAGED_PROJECTS_ROOT = str(Path(__file__).resolve().parents[3] / "projects")


class Settings(BaseSettings):
    PROJECT_NAME: str = "AutoCVE"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = "changethis_in_production_to_a_long_random_string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8

    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [item.strip() for item in v.split(",")]
        if isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    POSTGRES_SERVER: str = "db"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "autocve"
    DATABASE_URL: str | None = None

    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: str | None, values: dict[str, object]) -> str:
        if isinstance(v, str):
            return v
        return (
            f"postgresql+asyncpg://{values.get('POSTGRES_USER')}:{values.get('POSTGRES_PASSWORD')}"
            f"@{values.get('POSTGRES_SERVER')}/{values.get('POSTGRES_DB')}"
        )

    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: Optional[str] = None
    LLM_BASE_URL: Optional[str] = None
    LLM_TIMEOUT: int = 150
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096
    LLM_ENDPOINT_PROTOCOL: str = "openai_chat"
    LLM_TOOL_MESSAGE_FORMAT: str = "auto"
    LLM_FIRST_TOKEN_TIMEOUT: int = 30
    LLM_STREAM_TIMEOUT: int = 60
    SUB_AGENT_TIMEOUT_SECONDS: int = 600
    TOOL_TIMEOUT_SECONDS: int = 60

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None
    QWEN_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    ZHIPU_API_KEY: Optional[str] = None
    MOONSHOT_API_KEY: Optional[str] = None
    BAIDU_API_KEY: Optional[str] = None
    MINIMAX_API_KEY: Optional[str] = None
    DOUBAO_API_KEY: Optional[str] = None
    MIMO_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: Optional[str] = "http://localhost:11434/v1"

    GITHUB_TOKEN: Optional[str] = None
    GITLAB_TOKEN: Optional[str] = None
    GITEA_TOKEN: Optional[str] = None

    MAX_ANALYZE_FILES: int = 0
    MAX_FILE_SIZE_BYTES: int = 200 * 1024
    LLM_CONCURRENCY: int = 3
    LLM_GAP_MS: int = 2000
    ZIP_STORAGE_PATH: str = "./uploads/zip_files"
    PROJECT_SOURCE_STORAGE_PATH: str = "./uploads/project_sources"
    DISCOVERY_STORAGE_PATH: str = "./uploads/discovery_v2"
    DISCOVERY_SCANNER_IMAGE: str = "autocve-static-scanner:latest"
    MANAGED_PROJECTS_ROOT: str = DEFAULT_MANAGED_PROJECTS_ROOT
    OUTPUT_LANGUAGE: str = "zh-CN"

    CHECKMARX_FEATURE_ENABLED: bool = False
    CHECKMARX_BASE_URL: Optional[str] = None
    CHECKMARX_CLIENT_ID: str = "resource_owner_sast_client"
    CHECKMARX_CLIENT_SECRET: Optional[str] = None
    CHECKMARX_SCOPE: str = "access_control_api sast_api"
    CHECKMARX_PRESET_ID: int = 36
    CHECKMARX_FORCE_SCAN: bool = True
    CHECKMARX_IS_INCREMENTAL: bool = False
    CHECKMARX_TIMEOUT_CONNECT: int = 10
    CHECKMARX_TIMEOUT_READ: int = 30
    CHECKMARX_SCAN_UPLOAD_READ_TIMEOUT: int = 300
    CHECKMARX_SCAN_TIMEOUT: int = 3600
    CHECKMARX_SCAN_POLL_INTERVAL: int = 10
    CHECKMARX_SAST_ACCEPT_API_VERSION: str = "default"
    CHECKMARX_HELP_SAST_ACCEPT_API_VERSION: str = "default"
    CHECKMARX_HELP_RESULTS_DELAY: float = 0.25
    CHECKMARX_HELP_RESULTS_429_RETRIES: int = 12
    CHECKMARX_HELP_RESULTS_429_BASE_WAIT: float = 2.0
    CHECKMARX_UPLOAD_DIR: str = "./uploads/checkmarx"
    CHECKMARX_WORKFLOW_ENABLED: bool = True
    WORKFLOW_URL: Optional[str] = None
    WORKFLOW_API_TOKEN: Optional[str] = None
    WORKFLOW_USER: str = "autocve"
    WORKFLOW_TIMEOUT: float = 300.0

    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_BASE_URL: Optional[str] = None
    VECTOR_DB_PATH: str = "./data/vector_db"

    SSH_CONFIG_PATH: str = "./data/ssh"
    SSH_CLONE_TIMEOUT: int = 300
    SSH_TEST_TIMEOUT: int = 15
    SSH_CONNECT_TIMEOUT: int = 10

    AGENT_MAX_ITERATIONS: int = 50
    AGENT_TOKEN_BUDGET: int = 100000
    AGENT_TIMEOUT_SECONDS: int = 1800
    AGENT_EVENT_QUEUE_MAX_SIZE: int = 1000
    AGENT_TOKEN_EVENT_CHUNK_SIZE: int = 20
    AGENT_TOKEN_EVENT_FLUSH_INTERVAL_MS: int = 100
    AGENT_TASK_EXECUTION_MODE: str = "inline"
    AGENT_TASK_QUEUE_NAME: str = "autocve:arq:agent_tasks"
    AGENT_WORKER_CONCURRENCY: int = 2
    AGENT_WORKER_JOB_TIMEOUT_SECONDS: int = 3600
    AGENT_WORKER_MAX_TRIES: int = 2
    AGENT_EVENT_STREAM_ENABLED: bool = False
    AGENT_EVENT_STREAM_MAXLEN: int = 5000
    AGENT_EVENT_STREAM_BLOCK_MS: int = 15000
    ONE_CLICK_CVE_EXECUTION_MODE: str = "inline"
    ONE_CLICK_CVE_QUEUE_NAME: str = "autocve:arq:one_click_cve_batches"
    ONE_CLICK_CVE_WORKER_CONCURRENCY: int = 1
    ONE_CLICK_CVE_WORKER_JOB_TIMEOUT_SECONDS: int = 10800
    ONE_CLICK_CVE_WORKER_MAX_TRIES: int = 1
    ONE_CLICK_CVE_MAX_REPOSITORY_SIZE_KB: int = 512000
    ONE_CLICK_CVE_AGENT_TIMEOUT_SECONDS: int = 3000
    AUDIT_SESSION_RESUME_TIMEOUT_SECONDS: int = 3000
    REDIS_URL: str = "redis://localhost:6379/0"
    FINDING_RUNTIME_STACK_DEFAULT: str = "runtime"
    SANDBOX_IMAGE: str = "autocve-sandbox:latest"
    SANDBOX_MEMORY_LIMIT: str = "512m"
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_TIMEOUT: int = 60
    SANDBOX_NETWORK_MODE: str = "none"
    SANDBOX_CAP_DROP: str = (
        "SYS_ADMIN,NET_ADMIN,SYS_PTRACE,SYS_RAWIO,SYS_MODULE,SYS_BOOT,"
        "MKNOD,AUDIT_WRITE,AUDIT_CONTROL,SETFCAP,MAC_OVERRIDE,MAC_ADMIN"
    )
    SANDBOX_NO_NEW_PRIVILEGES: bool = True

    # ---- 独立动态验证 Agent（Pi，跑在隔离的 Docker 环境里）----
    # 默认为关闭：它需要一台能跑 Docker 的机器，并且会真的构建、运行被审计的项目，
    # 不应该在没准备好的部署里被误触发。
    VERIFICATION_AGENT_ENABLED: bool = False
    # 常驻验证容器名，对应 docker-compose.verify.yml 里的 pi-verifier。
    VERIFICATION_AGENT_CONTAINER: str = "autocve-pi-verifier"
    # 容器内的工作根目录，必须与 verifier-dind 挂载的路径一致。
    VERIFICATION_AGENT_WORKDIR: str = "/verifier/work"
    VERIFICATION_AGENT_RULES_PATH: str = "/opt/verifier/verifier-rules.md"
    VERIFICATION_AGENT_TOOLS: str = "read,write,edit,bash,grep,find,ls"
    # 单次验证的挂钟预算，也是容器内 timeout 的值。
    VERIFICATION_AGENT_TIMEOUT_SECONDS: int = 3600
    # 同一时间允许同时构建/运行几个被测项目环境。默认 1，按机器配置上调。
    VERIFICATION_AGENT_MAX_CONCURRENCY: int = 1
    # 一次验证允许累计暂停多久（秒）。容器内的硬超时会加上这个额度，
    # 所以「暂停」不会白白吃掉验证预算。默认 4 小时。
    VERIFICATION_AGENT_MAX_PAUSE_SECONDS: int = 14400
    VERIFICATION_AGENT_MODEL_PROVIDER: str = "deepseek"
    VERIFICATION_AGENT_MODEL_ID: str = ""
    VERIFICATION_AGENT_THINKING_LEVEL: str = "max"

    RAG_CHUNK_SIZE: int = 1500
    RAG_CHUNK_OVERLAP: int = 50
    RAG_TOP_K: int = 10

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"


settings = Settings()
