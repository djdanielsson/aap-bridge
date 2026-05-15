from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_app_state, get_db
from aap_migration.api.models import Connection, Job
from aap_migration.api.services.analysis_service import AnalysisService

router = APIRouter(tags=["analysis"])


class AnalysisRunRequest(BaseModel):
    connection_id: str


class AnalysisJobResponse(BaseModel):
    job_id: str


@router.post("/analysis/run", response_model=AnalysisJobResponse)
def run_analysis(data: AnalysisRunRequest, db: Session = Depends(get_db)) -> AnalysisJobResponse:
    conn = db.query(Connection).filter(Connection.id == data.connection_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    state = get_app_state()
    svc = AnalysisService(state.job_service, state.db_session_factory, state.loop)
    job_id = svc.start_analysis(conn)
    return AnalysisJobResponse(job_id=job_id)


@router.get("/analysis/{job_id}")
def get_analysis_result(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = {
        "job_id": job.id,
        "status": job.status,
        "error": job.error,
    }

    if job.status == "completed" and job.job_metadata:
        result["data"] = job.job_metadata
    elif job.status == "running" and job.job_metadata and "progress" in job.job_metadata:
        result["progress"] = job.job_metadata["progress"]

    return result


@router.get("/analysis/{job_id}/export/json")
def export_analysis_json(job_id: str, db: Session = Depends(get_db)):
    """Export analysis results as downloadable JSON."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.job_metadata:
        raise HTTPException(status_code=400, detail="Analysis not completed")

    return JSONResponse(
        content=job.job_metadata,
        headers={"Content-Disposition": f"attachment; filename=analysis-{job_id[:8]}.json"},
    )


@router.get("/analysis/{job_id}/export/markdown")
def export_analysis_markdown(job_id: str, db: Session = Depends(get_db)):
    """Export analysis results as downloadable Markdown report."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.job_metadata:
        raise HTTPException(status_code=400, detail="Analysis not completed")

    data = job.job_metadata
    lines: list[str] = []
    lines.append("# Dependency Analysis Report\n")
    lines.append(f"- **Source:** {data.get('source_url', 'N/A')}")
    lines.append(f"- **Date:** {data.get('analysis_date', 'N/A')}")
    lines.append(f"- **Organizations:** {data.get('total_organizations', 0)}\n")

    if data.get("independent_orgs"):
        lines.append("## Independent Organizations (no cross-org deps)\n")
        for org in data["independent_orgs"]:
            lines.append(f"- {org}")
        lines.append("")

    if data.get("dependent_orgs"):
        lines.append("## Organizations with Cross-Org Dependencies\n")
        for org in data["dependent_orgs"]:
            lines.append(f"- {org}")
        lines.append("")

    if data.get("migration_order"):
        lines.append("## Recommended Migration Order\n")
        for i, org in enumerate(data["migration_order"], 1):
            lines.append(f"{i}. {org}")
        lines.append("")

    orgs = data.get("organizations", {})
    if orgs:
        lines.append("## Organization Details\n")
        for org_name, org_data in orgs.items():
            rc = org_data.get("resource_count", 0)
            standalone = "Yes" if org_data.get("can_migrate_standalone") else "No"
            lines.append(f"### {org_name}\n")
            lines.append(f"- Resources: {rc}")
            lines.append(f"- Can migrate standalone: {standalone}")
            deps = org_data.get("dependencies", {})
            if deps:
                lines.append("- Dependencies:")
                for dep_org, dep_list in deps.items():
                    lines.append(f"  - **{dep_org}**: {len(dep_list)} resource(s)")
            lines.append("")

    content = "\n".join(lines)
    return JSONResponse(
        content={"markdown": content},
        headers={"Content-Disposition": f"attachment; filename=analysis-{job_id[:8]}.md"},
    )


@router.get("/analysis/{job_id}/export/html")
def export_analysis_html(job_id: str, db: Session = Depends(get_db)):
    """Export analysis results as downloadable HTML mind map report."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.job_metadata:
        raise HTTPException(status_code=400, detail="Analysis not completed")

    try:
        from datetime import datetime

        from aap_migration.analysis.dependency_analyzer import (
            GlobalDependencyReport,
            OrgDependencyReport,
            ResourceDependency,
        )
        from aap_migration.analysis.html_report import generate_html_report

        data = job.job_metadata
        org_reports = {}
        for org_name, org_data in data.get("organizations", {}).items():
            deps = {}
            for dep_org, dep_list in org_data.get("dependencies", {}).items():
                deps[dep_org] = [
                    ResourceDependency(
                        org_name=dep_org,
                        resource_type=d["resource_type"],
                        resource_id=d["resource_id"],
                        resource_name=d["resource_name"],
                        required_by=d.get("required_by", []),
                    )
                    for d in dep_list
                ]
            org_reports[org_name] = OrgDependencyReport(
                org_name=org_name,
                org_id=org_data.get("org_id", 0),
                resource_count=org_data.get("resource_count", 0),
                has_cross_org_deps=org_data.get("has_cross_org_deps", False),
                can_migrate_standalone=org_data.get("can_migrate_standalone", True),
                required_migrations_before=org_data.get("required_migrations_before", []),
                dependencies=deps,
                resources={},
            )

        report = GlobalDependencyReport(
            analysis_date=datetime.fromisoformat(data["analysis_date"])
            if data.get("analysis_date")
            else datetime.now(),
            source_url=data.get("source_url", ""),
            total_organizations=data.get("total_organizations", 0),
            analyzed_organizations=data.get("analyzed_organizations", []),
            independent_orgs=data.get("independent_orgs", []),
            dependent_orgs=data.get("dependent_orgs", []),
            org_reports=org_reports,
            migration_order=data.get("migration_order", []),
            migration_phases=data.get("migration_phases", []),
        )

        html_content = generate_html_report(report)
        return HTMLResponse(
            content=html_content,
            headers={"Content-Disposition": f"attachment; filename=analysis-{job_id[:8]}.html"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate HTML report: {e}") from e
