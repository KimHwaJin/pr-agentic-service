from fastapi import APIRouter

from src.dtest.api_service.deps import ServicesDep, UserDep
from src.dtest.api_service.schemas.users import ModelList

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelList)
async def list_models(services: ServicesDep, user: UserDep):
    """Chat models users can pick: exactly the ``models`` of the config."""
    return ModelList(items=services.settings.models)
