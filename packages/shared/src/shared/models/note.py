from sqlalchemy import ARRAY, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


class Note(Base):
    __tablename__ = "notes"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id"))
    dataset_id = Column(String, nullable=False)
    reference = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(ARRAY(String))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="notes")
