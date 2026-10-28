"""Shared base of every request/response model."""

from collections.abc import Collection
from typing import Any

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    def changes(
        self, nullable: Collection[str] = (), exclude: Collection[str] = ()
    ) -> dict[str, Any]:
        """The fields a PATCH body set.

        ``null`` clears only the ``nullable`` fields; on any other field it
        leaves the value as it is.
        """
        return {
            key: value
            for key, value in self.model_dump(
                exclude_unset=True, exclude=set(exclude)
            ).items()
            if value is not None or key in nullable
        }
