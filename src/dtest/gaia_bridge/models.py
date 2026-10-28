"""Which chat session a gaia conversation continues."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.dtest.core.db import Base, Timestamped
from src.dtest.core.models import ID


class GaiaSession(Timestamped, Base):
    __tablename__ = "gaia_sessions"
    # the gaia caller's employee id is part of the key: a session id sent
    # by another user never reaches this user's session
    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("users.id"), primary_key=True
    )
    gaia_session_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    session_id: Mapped[str] = mapped_column(ID, ForeignKey("sessions.id"))
