from datetime import datetime, timezone
from app.extensions import db


class TimestampMixin:
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class TenantMixin:
    __abstract__ = True

    empresa_id = db.Column(
        db.BigInteger,
        db.ForeignKey("empresas.id"),
        nullable=False,
        index=True
    )


class BaseModel(db.Model, TimestampMixin):
    __abstract__ = True

    id = db.Column(db.BigInteger, primary_key=True)