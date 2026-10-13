from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api_service.deps import ServicesDep, UserDep, session_for

router = APIRouter(tags=["images"])


@router.get("/images/{image_id}")
async def get_image(image_id: str, services: ServicesDep, user: UserDep):
    """An image a user sent (message ``attachments[].image_id``)."""
    image = await services.images.get(image_id)
    if image is None:
        raise HTTPException(404, "Image not found.")
    await session_for(services, user, image.session_id)
    path = services.images.file(image)
    if not path.is_file():
        raise HTTPException(404, "Image not found.")
    return FileResponse(
        path,
        media_type=image.mime_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )
