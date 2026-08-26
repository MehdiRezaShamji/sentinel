from pydantic import BaseModel, Field


class Scenario(BaseModel):
    area: str = Field(
        ...,
        description="Area where heat mitigation resources should be deployed",
    )

    candidate_locations: list[str] = Field(
        ...,
        min_length=1,
        description="Candidate locations to evaluate",
    )

    available_resources: int = Field(
        ...,
        gt=0,
        description="Number of available intervention resources",
    )

    intervention_options: list[str] = Field(
        ...,
        min_length=1,
        description="Available heat mitigation interventions",
    )
