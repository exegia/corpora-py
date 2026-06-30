from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


class User(Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True)
    username = Column(String, unique=True)
    full_name = Column(String)
    avatar_url = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # Relationships
    notes = relationship("Note", back_populates="user")
    favorites = relationship("Favorite", back_populates="user")
    datasets = relationship("UserDataset", back_populates="user")
