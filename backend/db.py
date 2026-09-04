from __future__ import annotations

import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ApiKey(db.Model):
    __tablename__ = "api_keys"

    session_uid = db.Column(db.String(64), primary_key=True)
    provider = db.Column(db.String(32), nullable=False, default="gemini")
    encrypted_key = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
