"""
GraphQL Types for Datasets

Defines Strawberry GraphQL types for dataset management.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

import strawberry


@strawberry.enum
class DatasetCategory(str, Enum):
    """Dataset category enumeration."""

    BIBLES = "bibles"
    BOOKS = "books"
    LEXICONS = "lexicons"
    DICTIONARIES = "dictionaries"


@strawberry.type
class DatasetMetadata:
    """Dataset metadata from storage."""

    size: Optional[int] = None
    content_type: Optional[str] = None
    cache_control: Optional[str] = None
    last_modified: Optional[datetime] = None


@strawberry.type
class Dataset:
    """Dataset information."""

    id: str
    name: str
    category: DatasetCategory
    bucket: str
    size: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Optional[strawberry.scalars.JSON] = None
    public_url: Optional[str] = None


@strawberry.type
class LocalDataset:
    """Locally stored dataset information."""

    id: str
    category: DatasetCategory
    path: str
    file_count: int
    size: int
    is_loaded: bool = False


@strawberry.type
class DatasetDownloadProgress:
    """Dataset download progress information."""

    dataset_id: str
    category: DatasetCategory
    status: str
    progress: float
    total_bytes: Optional[int] = None
    downloaded_bytes: Optional[int] = None
    message: Optional[str] = None


@strawberry.type
class DatasetDownloadResult:
    """Result of dataset download operation."""

    success: bool
    dataset_id: str
    category: DatasetCategory
    local_path: Optional[str] = None
    error_message: Optional[str] = None


@strawberry.type
class DatasetUploadResult:
    """Result of dataset upload operation."""

    success: bool
    dataset_id: str
    category: DatasetCategory
    file_name: str
    size: int
    uploaded: bool
    error_message: Optional[str] = None


@strawberry.type
class DatasetInfo:
    """Detailed dataset information."""

    id: str
    name: str
    category: DatasetCategory
    size: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_local: bool = False
    local_path: Optional[str] = None
    is_loaded: bool = False
    public_url: Optional[str] = None


@strawberry.type
class DatasetList:
    """Paginated list of datasets."""

    datasets: List[Dataset]
    total: int
    category: Optional[DatasetCategory] = None


@strawberry.type
class LocalDatasetList:
    """List of local datasets."""

    datasets: List[LocalDataset]
    total: int


# Input Types


@strawberry.input
class DownloadDatasetInput:
    """Input for downloading a dataset."""

    dataset_id: str
    category: DatasetCategory
    extract: bool = True
    custom_path: Optional[str] = None


@strawberry.input
class UploadDatasetInput:
    """Input for uploading a dataset."""

    dataset_id: str
    category: DatasetCategory
    local_path: str
    compress: bool = True


@strawberry.input
class DeleteDatasetInput:
    """Input for deleting a dataset."""

    dataset_id: str
    category: DatasetCategory
    delete_local: bool = False


@strawberry.input
class SyncDatasetInput:
    """Input for syncing a dataset."""

    dataset_id: str
    category: DatasetCategory
    direction: str  # "download" or "upload"
