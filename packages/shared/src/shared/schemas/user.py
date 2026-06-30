"""
GraphQL Types for User Data

Defines Strawberry GraphQL types for user profiles, notes, favorites, and comments.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

import strawberry


@strawberry.type
class User:
    """User profile information."""

    id: UUID
    email: str
    display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class Note:
    """User note on a biblical text."""

    id: UUID
    user_id: UUID
    dataset_id: str
    reference: str
    content: str
    tags: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class Favorite:
    """User favorite biblical passage."""

    id: UUID
    user_id: UUID
    dataset_id: str
    reference: str
    created_at: datetime


@strawberry.type
class Comment:
    """User comment on a biblical text."""

    id: UUID
    user_id: UUID
    dataset_id: str
    reference: str
    content: str
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class UserDataset:
    """User's downloaded dataset tracking."""

    id: UUID
    user_id: UUID
    dataset_id: str
    category: str
    local_path: Optional[str] = None
    downloaded_at: datetime
    last_accessed: Optional[datetime] = None


@strawberry.type
class NotesList:
    """Paginated list of notes."""

    notes: List[Note]
    total: int


@strawberry.type
class FavoritesList:
    """Paginated list of favorites."""

    favorites: List[Favorite]
    total: int


@strawberry.type
class CommentsList:
    """Paginated list of comments."""

    comments: List[Comment]
    total: int


@strawberry.type
class UserDatasetsList:
    """List of user's downloaded datasets."""

    datasets: List[UserDataset]
    total: int


@strawberry.type
class NoteWithUser:
    """Note with user information."""

    note: Note
    user: User


@strawberry.type
class CommentWithUser:
    """Comment with user information."""

    comment: Comment
    user: User
    replies: Optional[List["CommentWithUser"]] = None


# Input Types


@strawberry.input
class CreateNoteInput:
    """Input for creating a note."""

    dataset_id: str
    reference: str
    content: str
    tags: Optional[List[str]] = None


@strawberry.input
class UpdateNoteInput:
    """Input for updating a note."""

    id: UUID
    content: Optional[str] = None
    tags: Optional[List[str]] = None


@strawberry.input
class DeleteNoteInput:
    """Input for deleting a note."""

    id: UUID


@strawberry.input
class CreateFavoriteInput:
    """Input for creating a favorite."""

    dataset_id: str
    reference: str


@strawberry.input
class DeleteFavoriteInput:
    """Input for deleting a favorite."""

    id: UUID


@strawberry.input
class CreateCommentInput:
    """Input for creating a comment."""

    dataset_id: str
    reference: str
    content: str
    parent_id: Optional[UUID] = None


@strawberry.input
class UpdateCommentInput:
    """Input for updating a comment."""

    id: UUID
    content: str


@strawberry.input
class DeleteCommentInput:
    """Input for deleting a comment."""

    id: UUID


@strawberry.input
class UpdateUserProfileInput:
    """Input for updating user profile."""

    display_name: Optional[str] = None


@strawberry.input
class NotesFilterInput:
    """Filter input for querying notes."""

    dataset_id: Optional[str] = None
    reference: Optional[str] = None
    search: Optional[str] = None
    tags: Optional[List[str]] = None


@strawberry.input
class FavoritesFilterInput:
    """Filter input for querying favorites."""

    dataset_id: Optional[str] = None
    reference: Optional[str] = None


@strawberry.input
class CommentsFilterInput:
    """Filter input for querying comments."""

    dataset_id: Optional[str] = None
    reference: Optional[str] = None
    parent_id: Optional[UUID] = None
