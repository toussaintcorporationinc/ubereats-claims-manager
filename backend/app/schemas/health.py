from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


class VersionResponse(BaseModel):
    service: str
    version: str
    environment: str
    build_sha: str | None

