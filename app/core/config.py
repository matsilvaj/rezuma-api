from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Carrega e valida todas as variáveis de ambiente da aplicação."""

    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # Claude API
    ANTHROPIC_API_KEY: str

    # Resend
    RESEND_API_KEY: str

    # Telegram
    TELEGRAM_BOT_TOKEN: str

    # App
    APP_ENV: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = ""  # URL pública do backend, obrigatório em produção para registrar o webhook

    # Telegram Webhook
    TELEGRAM_WEBHOOK_SECRET: str = ""  # Secret enviado pelo Telegram em cada request ao webhook

    # E-mail, usar onboarding@resend.dev em dev (sem domínio verificado)
    EMAIL_FROM: str = "Rezuma <onboarding@resend.dev>"

    # Alertas operacionais para o desenvolvedor (deixe vazio para desativar)
    ADMIN_EMAIL: str = ""

    # Chave secreta para endpoints administrativos, obrigatório em produção
    ADMIN_SECRET_KEY: str = ""

    # Formulário de contato: as mensagens caem no Telegram de quem mantém.
    # Bot próprio, separado do bot que entrega os resumos, para um não
    # derrubar o outro se precisar trocar o token.
    CONTACT_BOT_TOKEN: str = ""
    CONTACT_CHAT_ID: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # variáveis de ambiente extras não causam erro


# Instância global usada em todo o projeto
settings = Settings()
