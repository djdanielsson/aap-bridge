from fastapi import APIRouter
from pydantic import BaseModel, Field

from aap_migration.sizing.calculator import AAP26SizingCalculator

router = APIRouter(tags=["sizing"])


class SizingRequest(BaseModel):
    managed_hosts: int = Field(..., ge=1)
    playbooks_per_day_peak: int = Field(..., ge=1)
    job_duration_hours: float = Field(default=0.5, ge=0.01)
    tasks_per_job: int = Field(default=50, ge=1)
    forks_observed: int = Field(default=10, ge=1)
    verbosity_level: int = Field(default=1, ge=0, le=4)
    allowed_hours_per_day: float = Field(default=8, ge=1, le=24)
    peak_pattern: str = Field(default="business_hours")
    # Advanced inputs
    num_controllers: int = Field(default=2, ge=1, description="Number of controller nodes")
    concurrent_jobs: int = Field(default=0, ge=0, description="Max concurrent jobs (0=auto)")
    pending_jobs: int = Field(default=0, ge=0, description="Typical pending job count")
    job_retention_hours: int = Field(
        default=720, ge=24, description="Job history retention in hours"
    )
    fact_retention_hours: int = Field(
        default=720, ge=24, description="Fact cache retention in hours"
    )
    hub_nodes: int = Field(default=1, ge=0, description="Automation Hub nodes (0=disabled)")
    eda_nodes: int = Field(default=0, ge=0, description="EDA controller nodes (0=disabled)")


class SizingResponse(BaseModel):
    input: dict
    execution_nodes: dict
    controller: dict
    database: dict
    automation_hub: dict | None = None
    gateway: dict | None = None
    eda: dict | None = None
    redis: dict | None = None
    warnings: list[str] = []
    validation_warnings: list[str] = []


@router.post("/sizing/calculate", response_model=SizingResponse)
def calculate_sizing(data: SizingRequest) -> SizingResponse:
    calculator = AAP26SizingCalculator()
    metrics = data.model_dump()

    warnings: list[str] = []
    for key, val in metrics.items():
        if isinstance(val, int | float):
            w = calculator.validate_input(key, val)
            if w:
                warnings.extend(w)

    execution = calculator.calculate_execution_node_resources(metrics)
    controller = calculator.calculate_controller_resources(metrics)
    database = calculator.calculate_database_resources(metrics)

    automation_hub = None
    gateway = None
    eda = None
    redis = None

    try:
        automation_hub = calculator.calculate_automation_hub_resources(metrics)
    except Exception:
        pass

    try:
        gateway = calculator.calculate_gateway_resources(metrics)
    except Exception:
        pass

    if metrics.get("eda_nodes", 0) > 0:
        try:
            eda = calculator.calculate_eda_resources(metrics)
        except Exception:
            pass

    try:
        redis = calculator.calculate_redis_resources(metrics)
    except Exception:
        pass

    # Post-calculation validation
    validation_warnings: list[str] = []
    try:
        all_results = {
            "execution": execution,
            "controller": controller,
            "database": database,
        }
        vw = calculator.validate_results(all_results)
        if vw:
            validation_warnings.extend(vw)
    except Exception:
        pass

    return SizingResponse(
        input=metrics,
        execution_nodes=execution,
        controller=controller,
        database=database,
        automation_hub=automation_hub,
        gateway=gateway,
        eda=eda,
        redis=redis,
        warnings=warnings,
        validation_warnings=validation_warnings,
    )
