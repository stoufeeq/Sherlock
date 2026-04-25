from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    log_level: str = "INFO"

    gitlab_internal_url: str = "http://gitlab:8080"
    gitlab_external_url: str = "http://localhost:8080"
    gitlab_token: str = ""
    gitlab_group: str = "banking"
    # Comma-separated list; when set, overrides gitlab_group and becomes the
    # source of truth for which groups Sherlock discovers + keeps in sync.
    gitlab_groups: str = ""

    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "sherlock-dev"

    cmdb_url: str = "http://cmdb-stub:8000"

    webhook_secret: str = "sherlock-local-dev"

    # Reconciler
    reconcile_enabled: bool = True
    reconcile_interval_seconds: int = 300   # 5 minutes
    reconcile_max_workers: int = 4          # parallelism for new-project scans per reconcile pass
    # Internal URL GitLab will hit when posting webhook events to Sherlock.
    # Used when the reconciler registers hooks on newly-discovered projects.
    sherlock_webhook_url: str = "http://sherlock:8000/webhooks/gitlab"

    # LLM provider (H2 autodoc) — accepts SHERLOCK_LLM_PROVIDER or LLM_PROVIDER
    llm_provider: str = Field(
        default="mock",
        validation_alias=AliasChoices("sherlock_llm_provider", "llm_provider"),
    )
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-06-01"

    # Autodoc
    autodoc_branch_prefix: str = "sherlock/autodoc"
    autodoc_mr_label: str = "sherlock::autodoc"
    autodoc_bot_name: str = "Sherlock Bot"
    autodoc_bot_email: str = "sherlock-bot@ubs.local"

    @property
    def groups_list(self) -> list[str]:
        if self.gitlab_groups.strip():
            return [g.strip() for g in self.gitlab_groups.split(",") if g.strip()]
        return [self.gitlab_group]


settings = Settings()
