from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id"))
    dataset_id = Column(String, nullable=False)
    reference = Column(String, nullable=False)
    note = Column(Text)
    created_at = Column(DateTime)

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "dataset_id", "reference", name="uq_user_dataset_ref"),
    )

    # Relationships
    user = relationship("User", back_populates="favorites")
