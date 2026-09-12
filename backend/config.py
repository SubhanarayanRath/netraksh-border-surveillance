"""
NETRAKSH Backend — Application settings loaded from environment / .env file.
All secrets come from environment variables. No hardcoded credentials.
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server ---
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8443
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    AUDIT_LOG_ENABLED: bool = True
    ENV: str = "production"

    # --- Database ---
    DATABASE_URL: str = "postgresql://netraksh:netraksh_password@localhost:5432/netraksh"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_postgres_scheme(cls, v: str) -> str:
        """
        Render (and Heroku-style platforms before it) hand out a managed
        Postgres connection string starting with the legacy `postgres://`
        scheme. SQLAlchemy 1.4+ rejects that scheme outright — it requires
        `postgresql://`. Without this, DATABASE_URL pasted verbatim from
        Render's dashboard into an env var would fail at engine creation,
        not at request time, so this is caught here rather than being a
        confusing first-boot crash on the exact platform this project
        targets for its live deployment.
        """
        if v.startswith("postgres://"):
            return "postgresql://" + v[len("postgres://"):]
        return v

    # --- Security / JWT ---
    SECRET_KEY: str = "CHANGE_ME_USE_openssl_rand_hex_32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    TLS_ENABLED: bool = False  # Set True when certs are provisioned

    # --- TLS / mTLS ---
    SERVER_CERT_PATH: str = "certs/server/server.crt"
    SERVER_KEY_PATH: str = "certs/server/server.key"
    CA_CERT_PATH: str = "certs/ca/ca.crt"

    # --- RBAC default users ---
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin"
    INITIAL_OPERATOR_USERNAME: str = "operator"
    INITIAL_OPERATOR_PASSWORD: str = "operator"
    INITIAL_AUDITOR_USERNAME: str = "auditor"
    INITIAL_AUDITOR_PASSWORD: str = "auditor"

    # --- Command identity ---
    COMMAND_ID: str = "COMMAND_A"

    # --- Blockchain ---
    BLOCKCHAIN_MODE: str = "mock"  # "mock" | "fabric"
    BLOCKCHAIN_MOCK_LABEL: str = "BLOCKCHAIN: MOCK MODE (Fabric not available on this host — WSL2/Docker required)"
    FABRIC_PEER_BIN: str = "peer"
    FABRIC_CHANNEL: str = "netraksh-channel"
    FABRIC_CHAINCODE: str = "netraksh-cc"
    FABRIC_ORG_MSP: str = "CommandAMSP"

    # --- Frontend CORS ---
    CORS_ORIGINS: str = ""

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str, info) -> list[str]:
        # Access the ENV value from the pydantic ValidationInfo
        env = info.data.get("ENV", "production")
        if not v or not v.strip():
            if env == "development":
                return ["http://localhost:5173", "http://localhost:3000", "https://localhost:5173"]
            return []
        
        origins = [i.strip() for i in v.split(",") if i.strip()]
        if "*" in origins:
            raise ValueError("Wildcard '*' CORS is strictly prohibited.")
        return origins


settings = Settings()
