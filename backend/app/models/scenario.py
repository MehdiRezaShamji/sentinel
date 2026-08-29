from pydantic import BaseModel, Field


class Worker(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    task: str
    exposure_minutes: int = Field(default=0, ge=0)
    status: str = "working"
    buddy_id: str | None = None
    phone: str | None = None
    check_in_status: str | None = None
    check_in_sent_at: str | None = None
    check_in_timeout_seconds: int = 300
    buddy_verification_status: str | None = None
    buddy_notified_at: str | None = None


class Incident(BaseModel):
    id: str
    worker_id: str
    type: str
    status: str = "active"
    actions_taken: list[str] = Field(default_factory=list)


class SafetyState(BaseModel):
    workers: list[Worker] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)
    agent_actions: list[str] = Field(default_factory=list)
