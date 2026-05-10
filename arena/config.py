from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str
    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.cn/v1"
    environment: str = "development"

    # Supabase Postgres pooler URL
    # Format: postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
    database_url: str = ""

    # Resend email
    resend_api_key: str = ""
    resend_from: str = "CodeArena <onboarding@resend.dev>"

    # App
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    secret_key: str = "change-me-in-production-32-bytes-min"

    class Config:
        env_file = ".env"


settings = Settings()
