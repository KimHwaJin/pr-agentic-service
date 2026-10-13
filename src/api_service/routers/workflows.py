from fastapi import APIRouter, HTTPException, Response

from api_service.deps import ServicesDep, UserDep
from api_service.schemas import WorkflowClone, WorkflowCreate, WorkflowRead, WorkflowSearch, WorkflowUpdate
from core.workflows.service import WorkflowError

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _error(exc: WorkflowError) -> HTTPException:
    return HTTPException(exc.status, {"message": str(exc), "errors": exc.details} if exc.details else str(exc))


def _validated(services, document: dict) -> dict:
    return services.workflows.validate(document, services.skills("analysis"), services.tool_catalog())


@router.post("", response_model=WorkflowRead, status_code=201)
async def create_workflow(body: WorkflowCreate, services: ServicesDep, user: UserDep):
    """Registers a candidate (visible to the author only until promoted)."""
    try:
        return await services.workflows.create(
            author_id=user.id,
            document=_validated(services, body.document),
            user_queries=body.user_queries,
            tags=body.tags,
            source_run_id=body.source_run_id,
        )
    except WorkflowError as exc:
        raise _error(exc) from None


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    services: ServicesDep, user: UserDep, lifecycle: str | None = None, q: str | None = None, tag: str | None = None
):
    return await services.workflows.browse(user.id, lifecycle=lifecycle, q=q, tag=tag)


@router.post("/validate")
async def validate_workflow(document: dict, services: ServicesDep, user: UserDep):
    try:
        return {"valid": True, "document": _validated(services, document)}
    except WorkflowError as exc:
        return {"valid": False, "errors": exc.details}


@router.post("/search")
async def search_workflows(body: WorkflowSearch, services: ServicesDep, user: UserDep):
    hits = await services.workflows.search(body.query, limit=services.settings.plan_candidates)
    return {
        "items": [
            {
                "workflow": WorkflowRead.model_validate(h["workflow"]),
                "similarity": h["similarity"],
                "matched_query": h["matched_query"],
            }
            for h in hits
        ]
    }


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(workflow_id: str, services: ServicesDep, user: UserDep):
    try:
        return await services.workflows.readable(workflow_id, user.id)
    except WorkflowError as exc:
        raise _error(exc) from None


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(workflow_id: str, body: WorkflowUpdate, services: ServicesDep, user: UserDep):
    try:
        changes = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
        if "document" in changes:
            changes["document"] = _validated(services, changes["document"])
        return await services.workflows.update(
            workflow_id, user.id, expected_revision=body.expected_revision, **changes
        )
    except WorkflowError as exc:
        raise _error(exc) from None


@router.post("/{workflow_id}/promote", response_model=WorkflowRead)
async def promote_workflow(workflow_id: str, services: ServicesDep, user: UserDep):
    """Candidate -> template: searchable and recommendable for every user."""
    try:
        return await services.workflows.promote(workflow_id, user.id)
    except WorkflowError as exc:
        raise _error(exc) from None


@router.post("/{workflow_id}/clone", response_model=WorkflowRead, status_code=201)
async def clone_workflow(workflow_id: str, body: WorkflowClone, services: ServicesDep, user: UserDep):
    try:
        return await services.workflows.clone(workflow_id, user.id, body.name)
    except WorkflowError as exc:
        raise _error(exc) from None


@router.post("/{workflow_id}/reindex", response_model=WorkflowRead)
async def reindex_workflow(workflow_id: str, services: ServicesDep, user: UserDep):
    try:
        return await services.workflows.reindex(workflow_id, user.id)
    except WorkflowError as exc:
        raise _error(exc) from None


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str, services: ServicesDep, user: UserDep):
    try:
        await services.workflows.delete(workflow_id, user.id)
    except WorkflowError as exc:
        raise _error(exc) from None
    return Response(status_code=204)
