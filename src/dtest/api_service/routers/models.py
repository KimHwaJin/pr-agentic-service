from fastapi import APIRouter

from src.dtest.api_service.deps import ServicesDep, UserOrServiceDep
from src.dtest.api_service.schemas.users import ModelList

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelList)
async def list_models(services: ServicesDep, _user: UserOrServiceDep):
    """Chat models users can pick: exactly the ``models`` of the config.

    Key callers may leave out ``X-User-Id``: the list is no one's.
    """
    return ModelList(items=services.settings.models)
