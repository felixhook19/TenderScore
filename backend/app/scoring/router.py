"""Scoring endpoints: calibration, run creation, status, SSE, replay."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.auth.deps import CurrentUser, get_tenant_db, get_tenant_recorder, require_roles
from app.auth.roles import Role
from app.core.db import tenant_session
from app.framework.models import CalibrationBenchmark, Criterion, Procurement
from app.llm_gateway.gateway import LLMGateway
from app.llm_gateway.registry import resolve
from app.scoring import jobs as scoring_jobs
from app.scoring.engine import SCORE_PROMPT_ID, ScoringError
from app.scoring.models import Recommendation, ScoringPass, ScoringRun
from app.scoring.orchestrator import CalibrationGateError, calibrate, create_runs
from app.scoring.replay import ReplayReport, replay_run

router = APIRouter(tags=["scoring"])

_lead_roles = require_roles(Role.ADMIN, Role.PROCUREMENT_LEAD)
_eval_roles = require_roles(
    Role.ADMIN, Role.PROCUREMENT_LEAD, Role.EVALUATOR, Role.MODERATOR, Role.OBSERVER_AUDITOR
)


class BenchmarkRequest(BaseModel):
    criterion_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    answer_text: str = Field(min_length=1)
    buyer_score: int = Field(ge=0, le=10)


class BenchmarkOut(BaseModel):
    id: uuid.UUID
    criterion_id: uuid.UUID
    title: str
    buyer_score: int
    engine_score: int | None
    divergence_accepted: bool


class AcceptDivergenceRequest(BaseModel):
    rationale: str = Field(min_length=10)


class RunsCreated(BaseModel):
    runs_created: int
    runs_blocked: int
    detail: str


class RunStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    criterion_id: uuid.UUID
    bidder_id: uuid.UUID
    pass_count_target: int
    model_version: str
    variance: int | None
    confidence_tier: str | None
    recommended_score: int | None


class RecommendationOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    criterion_id: uuid.UUID
    bidder_id: uuid.UUID
    score: int | None
    band_label: str | None
    justification: str
    citations: list[dict[str, object]]
    requirements: dict[str, list[str]]
    weaknesses: list[str]
    variance: int
    confidence_tier: str


class ReplayOut(BaseModel):
    run_id: str
    passes_replayed: int
    identical: bool
    mismatches: list[str]


def _load_procurement(db: Session, procurement_id: uuid.UUID) -> Procurement:
    procurement = db.get(Procurement, procurement_id)
    if procurement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The procurement was not found."
        )
    return procurement


@router.post(
    "/procurements/{procurement_id}/calibration/benchmarks",
    response_model=BenchmarkOut,
    status_code=status.HTTP_201_CREATED,
)
def add_benchmark(
    procurement_id: uuid.UUID,
    body: BenchmarkRequest,
    user: Annotated[CurrentUser, Depends(_lead_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> BenchmarkOut:
    _load_procurement(db, procurement_id)
    criterion = db.get(Criterion, body.criterion_id)
    if criterion is None or criterion.procurement_id != procurement_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The criterion was not found."
        )
    benchmark = CalibrationBenchmark(
        procurement_id=procurement_id,
        criterion_id=body.criterion_id,
        title=body.title,
        answer_text=body.answer_text,
        buyer_score=body.buyer_score,
    )
    db.add(benchmark)
    db.flush()
    recorder.record(
        "calibration.benchmark_created",
        entity_type="calibration_benchmark",
        entity_id=str(benchmark.id),
    )
    return BenchmarkOut(
        id=benchmark.id,
        criterion_id=benchmark.criterion_id,
        title=benchmark.title,
        buyer_score=benchmark.buyer_score,
        engine_score=benchmark.engine_score,
        divergence_accepted=benchmark.divergence_accepted,
    )


@router.post(
    "/procurements/{procurement_id}/calibration/run",
    response_model=list[BenchmarkOut],
)
def run_calibration(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_lead_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> list[BenchmarkOut]:
    procurement = _load_procurement(db, procurement_id)
    if procurement.status != "locked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lock the framework before running calibration.",
        )
    gateway = LLMGateway(scoring_jobs._adapter())
    prompt = resolve(db, SCORE_PROMPT_ID)
    try:
        benchmarks = calibrate(db, recorder, gateway, prompt, procurement=procurement)
    except CalibrationGateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    return [
        BenchmarkOut(
            id=benchmark.id,
            criterion_id=benchmark.criterion_id,
            title=benchmark.title,
            buyer_score=benchmark.buyer_score,
            engine_score=benchmark.engine_score,
            divergence_accepted=benchmark.divergence_accepted,
        )
        for benchmark in benchmarks
    ]


@router.post(
    "/procurements/{procurement_id}/calibration/benchmarks/{benchmark_id}/accept-divergence",
    status_code=status.HTTP_204_NO_CONTENT,
)
def accept_divergence(
    procurement_id: uuid.UUID,
    benchmark_id: uuid.UUID,
    body: AcceptDivergenceRequest,
    user: Annotated[CurrentUser, Depends(_lead_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> None:
    benchmark = db.get(CalibrationBenchmark, benchmark_id)
    if benchmark is None or benchmark.procurement_id != procurement_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The benchmark was not found."
        )
    benchmark.divergence_accepted = True
    benchmark.acceptance_rationale = body.rationale
    db.flush()
    recorder.record(
        "calibration.divergence_accepted",
        entity_type="calibration_benchmark",
        entity_id=str(benchmark.id),
    )


@router.post(
    "/procurements/{procurement_id}/scoring/runs",
    response_model=RunsCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_scoring(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_lead_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> RunsCreated:
    procurement = _load_procurement(db, procurement_id)
    try:
        runs = create_runs(db, recorder, procurement=procurement, created_by=user.id)
    except (ScoringError, CalibrationGateError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    blocked = sum(1 for run in runs if run.status == "blocked")
    return RunsCreated(
        runs_created=len(runs) - blocked,
        runs_blocked=blocked,
        detail=(
            f"{len(runs) - blocked} scoring run(s) queued; {blocked} blocked by "
            "gate failures."
        ),
    )


@router.get("/scoring/runs/{run_id}", response_model=RunStatusOut)
def get_run(
    run_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_eval_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> RunStatusOut:
    run = db.get(ScoringRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The scoring run was not found."
        )
    recommendation = db.scalar(
        select(Recommendation).where(Recommendation.run_id == run.id)
    )
    return RunStatusOut(
        id=run.id,
        status=run.status,
        criterion_id=run.criterion_id,
        bidder_id=run.bidder_id,
        pass_count_target=run.pass_count_target,
        model_version=run.model_version,
        variance=recommendation.variance if recommendation else None,
        confidence_tier=recommendation.confidence_tier if recommendation else None,
        recommended_score=recommendation.score if recommendation else None,
    )


@router.get("/scoring/runs/{run_id}/replay", response_model=ReplayOut)
def replay(
    run_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_lead_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> ReplayOut:
    run = db.get(ScoringRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The scoring run was not found."
        )
    from app.framework.models import Criterion as CriterionModel
    from app.ingestion.models import QuestionResponse
    from app.scoring.engine import prepare_content

    response = db.get(QuestionResponse, run.question_response_id)
    criterion = db.get(CriterionModel, run.criterion_id)
    if response is None or criterion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The run's response or criterion no longer exists.",
        )
    source_text, _ = prepare_content(db, response, criterion, run.procurement_id)
    report: ReplayReport = replay_run(db, run, source_text=source_text)
    return ReplayOut(
        run_id=report.run_id,
        passes_replayed=report.passes_replayed,
        identical=report.identical,
        mismatches=report.mismatches,
    )


@router.get(
    "/procurements/{procurement_id}/recommendations",
    response_model=list[RecommendationOut],
)
def list_recommendations(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_eval_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> list[RecommendationOut]:
    rows = db.execute(
        select(Recommendation, ScoringRun)
        .join(ScoringRun, ScoringRun.id == Recommendation.run_id)
        .where(ScoringRun.procurement_id == procurement_id)
        .order_by(Recommendation.created_at)
    ).all()
    return [
        RecommendationOut(
            id=recommendation.id,
            run_id=run.id,
            criterion_id=run.criterion_id,
            bidder_id=run.bidder_id,
            score=recommendation.score,
            band_label=recommendation.band_label,
            justification=recommendation.justification,
            citations=recommendation.citations,
            requirements=recommendation.requirements,
            weaknesses=recommendation.weaknesses,
            variance=recommendation.variance,
            confidence_tier=recommendation.confidence_tier,
        )
        for recommendation, run in rows
    ]


@router.get("/procurements/{procurement_id}/scoring/stream")
async def scoring_stream(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_eval_roles)],
) -> StreamingResponse:
    """SSE stream of scoring progress, driven by job status (no token
    streams in scoring paths — whole-response validation is required)."""
    schema = user.tenant_schema

    async def event_stream() -> AsyncIterator[str]:
        for _ in range(120):
            session = tenant_session(schema)
            try:
                rows = session.execute(
                    select(ScoringRun.status, func.count())
                    .where(ScoringRun.procurement_id == procurement_id)
                    .group_by(ScoringRun.status)
                ).all()
                counts: dict[str, int] = {str(row[0]): int(row[1]) for row in rows}
            finally:
                session.close()
            payload = json.dumps({"runs": counts})
            yield f"data: {payload}\n\n"
            pending = counts.get("queued", 0) + counts.get("running", 0)
            if counts and pending == 0:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/scoring/runs/{run_id}/passes")
def list_passes(
    run_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_eval_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> list[dict[str, object]]:
    passes = db.scalars(
        select(ScoringPass)
        .where(ScoringPass.run_id == run_id)
        .order_by(ScoringPass.pass_number, ScoringPass.attempt)
    ).all()
    return [
        {
            "pass_number": scoring_pass.pass_number,
            "attempt": scoring_pass.attempt,
            "validated": scoring_pass.validated,
            "score": scoring_pass.score,
            "validation_failures": scoring_pass.validation_failures,
            "validation_flags": scoring_pass.validation_flags,
            "injection_suspicion": scoring_pass.injection_suspicion,
            "tokens_in": scoring_pass.tokens_in,
            "tokens_out": scoring_pass.tokens_out,
        }
        for scoring_pass in passes
    ]
