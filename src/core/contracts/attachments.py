"""Files attached to a chat message (``messages.attachments``).

User messages carry the images they sent; the agent's answer carries the
report and notebook its turn published (the ``artifact`` events).
"""

from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import Field

from core.contracts.hitl import View


class ImageAttachment(View):
    kind: Literal["image"]
    image_id: str = Field(description="GET /images/{image_id}")
    name: str | None = None
    mime_type: str
    width: int
    height: int


class ArtifactAttachment(View):
    """Also the data of an ``artifact`` event."""

    kind: Literal["report", "notebook"]
    artifact_id: str = Field(description="/view/artifacts/{artifact_id}")
    title: str
    lab_url: str | None = Field(
        None, description="노트북을 JupyterLab에서 여는 링크 (리포트는 null)"
    )


ATTACHMENTS: dict[str, Any] = {
    "image": ImageAttachment,
    "artifact": ArtifactAttachment,
}

if TYPE_CHECKING:
    Attachment = Any
else:
    Attachment = Annotated[
        Union[tuple(ATTACHMENTS.values())],  # noqa: UP007
        Field(discriminator="kind"),
    ]
