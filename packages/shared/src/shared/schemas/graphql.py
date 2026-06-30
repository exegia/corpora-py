"""
Main Strawberry GraphQL Schema

Defines the GraphQL API schema for Exegia.
"""

from typing import List, Optional
from uuid import UUID

import strawberry
from strawberry.fastapi import GraphQLRouter

from exegia_graphql.types.corpus import (
    BookInfo,
    ChapterInfo,
    ComparePassagesInput,
    CorpusMetadata,
    CorpusQueryInput,
    CorpusQueryResult,
    CorpusStats,
    CrossReference,
    GetBooksInput,
    GetChapterInfoInput,
    GetPassageInput,
    GetPassagesInput,
    GetVerseRangeInput,
    ParallelPassage,
    Passage,
    SearchCorpusInput,
    SearchResults,
    Verse,
    VerseRange,
    WordStudy,
    WordStudyInput,
)
from exegia_graphql.types.dataset import (
    Dataset,
    DatasetCategory,
    DatasetDownloadResult,
    DatasetInfo,
    DatasetList,
    DatasetUploadResult,
    DeleteDatasetInput,
    DownloadDatasetInput,
    LocalDataset,
    LocalDatasetList,
    SyncDatasetInput,
    UploadDatasetInput,
)
from exegia_graphql.types.user import (
    Comment,
    CommentsFilterInput,
    CommentsList,
    CreateCommentInput,
    CreateFavoriteInput,
    CreateNoteInput,
    DeleteCommentInput,
    DeleteFavoriteInput,
    DeleteNoteInput,
    Favorite,
    FavoritesFilterInput,
    FavoritesList,
    Note,
    NotesFilterInput,
    NotesList,
    UpdateCommentInput,
    UpdateNoteInput,
    UpdateUserProfileInput,
    User,
    UserDataset,
    UserDatasetsList,
)


@strawberry.type
class Query:
    """Root Query type."""

    # ========================================================================
    # Dataset Queries
    # ========================================================================

    @strawberry.field
    async def datasets(
        self,
        category: Optional[DatasetCategory] = None,
        search: Optional[str] = None,
    ) -> DatasetList:
        """
        List available datasets from Supabase Storage.

        Args:
            category: Filter by category (bibles, books, lexicons, dictionaries)
            search: Search term to filter dataset names

        Returns:
            List of available datasets
        """
        from exegia_graphql.resolvers.datasets import resolve_datasets

        return await resolve_datasets(category, search)

    @strawberry.field
    async def dataset(
        self, dataset_id: str, category: DatasetCategory
    ) -> Optional[DatasetInfo]:
        """
        Get detailed information about a specific dataset.

        Args:
            dataset_id: Dataset identifier
            category: Dataset category

        Returns:
            Dataset information or None if not found
        """
        from exegia_graphql.resolvers.datasets import resolve_dataset

        return await resolve_dataset(dataset_id, category)

    @strawberry.field
    async def local_datasets(
        self, category: Optional[DatasetCategory] = None
    ) -> LocalDatasetList:
        """
        List datasets stored locally on the filesystem.

        Args:
            category: Filter by category

        Returns:
            List of local datasets
        """
        from exegia_graphql.resolvers.datasets import resolve_local_datasets

        return await resolve_local_datasets(category)

    @strawberry.field
    async def local_dataset(
        self, dataset_id: str, category: DatasetCategory
    ) -> Optional[LocalDataset]:
        """
        Get information about a local dataset.

        Args:
            dataset_id: Dataset identifier
            category: Dataset category

        Returns:
            Local dataset information or None if not found
        """
        from exegia_graphql.resolvers.datasets import resolve_local_dataset

        return await resolve_local_dataset(dataset_id, category)

    # ========================================================================
    # User Data Queries
    # ========================================================================

    @strawberry.field
    async def my_profile(self, info: strawberry.Info) -> Optional[User]:
        """
        Get the authenticated user's profile.

        Returns:
            User profile or None if not authenticated
        """
        from exegia_graphql.resolvers.users import resolve_my_profile

        return await resolve_my_profile(info)

    @strawberry.field
    async def my_notes(
        self,
        info: strawberry.Info,
        filters: Optional[NotesFilterInput] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> NotesList:
        """
        Get the authenticated user's notes.

        Args:
            filters: Optional filters
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of user's notes
        """
        from exegia_graphql.resolvers.users import resolve_my_notes

        return await resolve_my_notes(info, filters, limit, offset)

    @strawberry.field
    async def my_favorites(
        self,
        info: strawberry.Info,
        filters: Optional[FavoritesFilterInput] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> FavoritesList:
        """
        Get the authenticated user's favorites.

        Args:
            filters: Optional filters
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of user's favorites
        """
        from exegia_graphql.resolvers.users import resolve_my_favorites

        return await resolve_my_favorites(info, filters, limit, offset)

    @strawberry.field
    async def my_comments(
        self,
        info: strawberry.Info,
        filters: Optional[CommentsFilterInput] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CommentsList:
        """
        Get the authenticated user's comments.

        Args:
            filters: Optional filters
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of user's comments
        """
        from exegia_graphql.resolvers.users import resolve_my_comments

        return await resolve_my_comments(info, filters, limit, offset)

    @strawberry.field
    async def my_datasets(self, info: strawberry.Info) -> UserDatasetsList:
        """
        Get the authenticated user's downloaded datasets.

        Returns:
            List of user's downloaded datasets
        """
        from exegia_graphql.resolvers.users import resolve_my_datasets

        return await resolve_my_datasets(info)

    # ========================================================================
    # Corpus Queries
    # ========================================================================

    @strawberry.field
    async def corpus_metadata(self, dataset_id: str) -> Optional[CorpusMetadata]:
        """
        Get metadata about a Text-Fabric corpus.

        Args:
            dataset_id: Dataset identifier

        Returns:
            Corpus metadata or None if not loaded
        """
        from exegia_graphql.resolvers.corpus import resolve_corpus_metadata

        return await resolve_corpus_metadata(dataset_id)

    @strawberry.field
    async def corpus_stats(self, dataset_id: str) -> Optional[CorpusStats]:
        """
        Get statistics about a corpus.

        Args:
            dataset_id: Dataset identifier

        Returns:
            Corpus statistics or None if not loaded
        """
        from exegia_graphql.resolvers.corpus import resolve_corpus_stats

        return await resolve_corpus_stats(dataset_id)

    @strawberry.field
    async def search_corpus(self, input: SearchCorpusInput) -> SearchResults:
        """
        Search within a corpus for matching verses.

        Args:
            input: Search parameters

        Returns:
            Search results with matching verses
        """
        from exegia_graphql.resolvers.corpus import resolve_search_corpus

        return await resolve_search_corpus(input)

    @strawberry.field
    async def get_passage(self, input: GetPassageInput) -> Optional[Passage]:
        """
        Get a biblical passage by reference.

        Args:
            input: Passage reference and options

        Returns:
            Passage or None if not found
        """
        from exegia_graphql.resolvers.corpus import resolve_get_passage

        return await resolve_get_passage(input)

    @strawberry.field
    async def get_passages(self, input: GetPassagesInput) -> List[Passage]:
        """
        Get multiple passages by references.

        Args:
            input: Passage references and options

        Returns:
            List of passages
        """
        from exegia_graphql.resolvers.corpus import resolve_get_passages

        return await resolve_get_passages(input)

    @strawberry.field
    async def get_verse(self, dataset_id: str, reference: str) -> Optional[Verse]:
        """
        Get a single verse by reference.

        Args:
            dataset_id: Dataset identifier
            reference: Verse reference (e.g., "John 3:16")

        Returns:
            Verse or None if not found
        """
        from exegia_graphql.resolvers.corpus import resolve_get_verse

        return await resolve_get_verse(dataset_id, reference)

    @strawberry.field
    async def get_verse_range(self, input: GetVerseRangeInput) -> List[Verse]:
        """
        Get a range of verses.

        Args:
            input: Verse range parameters

        Returns:
            List of verses in the range
        """
        from exegia_graphql.resolvers.corpus import resolve_get_verse_range

        return await resolve_get_verse_range(input)

    @strawberry.field
    async def word_study(self, input: WordStudyInput) -> Optional[WordStudy]:
        """
        Perform a word study (find all occurrences of a word).

        Args:
            input: Word study parameters

        Returns:
            Word study results
        """
        from exegia_graphql.resolvers.corpus import resolve_word_study

        return await resolve_word_study(input)

    @strawberry.field
    async def compare_passages(self, input: ComparePassagesInput) -> ParallelPassage:
        """
        Compare a passage across multiple datasets.

        Args:
            input: Comparison parameters

        Returns:
            Parallel passage data
        """
        from exegia_graphql.resolvers.corpus import resolve_compare_passages

        return await resolve_compare_passages(input)

    @strawberry.field
    async def get_books(self, input: GetBooksInput) -> List[BookInfo]:
        """
        Get list of books in a corpus.

        Args:
            input: Book list parameters

        Returns:
            List of books
        """
        from exegia_graphql.resolvers.corpus import resolve_get_books

        return await resolve_get_books(input)

    @strawberry.field
    async def get_chapter_info(
        self, input: GetChapterInfoInput
    ) -> Optional[ChapterInfo]:
        """
        Get information about a chapter.

        Args:
            input: Chapter info parameters

        Returns:
            Chapter information
        """
        from exegia_graphql.resolvers.corpus import resolve_get_chapter_info

        return await resolve_get_chapter_info(input)


@strawberry.type
class Mutation:
    """Root Mutation type."""

    # ========================================================================
    # Dataset Mutations
    # ========================================================================

    @strawberry.mutation
    async def download_dataset(
        self, info: strawberry.Info, input: DownloadDatasetInput
    ) -> DatasetDownloadResult:
        """
        Download a dataset from Supabase Storage to local filesystem.

        Args:
            input: Download parameters

        Returns:
            Download result with success status and local path
        """
        from exegia_graphql.resolvers.datasets import resolve_download_dataset

        return await resolve_download_dataset(info, input)

    @strawberry.mutation
    async def upload_dataset(
        self, info: strawberry.Info, input: UploadDatasetInput
    ) -> DatasetUploadResult:
        """
        Upload a dataset from local filesystem to Supabase Storage.

        Args:
            input: Upload parameters

        Returns:
            Upload result with success status
        """
        from exegia_graphql.resolvers.datasets import resolve_upload_dataset

        return await resolve_upload_dataset(info, input)

    @strawberry.mutation
    async def delete_dataset(
        self, info: strawberry.Info, input: DeleteDatasetInput
    ) -> bool:
        """
        Delete a dataset from Supabase Storage.

        Args:
            input: Delete parameters

        Returns:
            True if deleted successfully
        """
        from exegia_graphql.resolvers.datasets import resolve_delete_dataset

        return await resolve_delete_dataset(info, input)

    @strawberry.mutation
    async def sync_dataset(
        self, info: strawberry.Info, input: SyncDatasetInput
    ) -> bool:
        """
        Sync a dataset between local and Supabase Storage.

        Args:
            input: Sync parameters

        Returns:
            True if synced successfully
        """
        from exegia_graphql.resolvers.datasets import resolve_sync_dataset

        return await resolve_sync_dataset(info, input)

    # ========================================================================
    # User Data Mutations
    # ========================================================================

    @strawberry.mutation
    async def update_profile(
        self, info: strawberry.Info, input: UpdateUserProfileInput
    ) -> User:
        """
        Update the authenticated user's profile.

        Args:
            input: Profile update data

        Returns:
            Updated user profile
        """
        from exegia_graphql.resolvers.users import resolve_update_profile

        return await resolve_update_profile(info, input)

    @strawberry.mutation
    async def create_note(self, info: strawberry.Info, input: CreateNoteInput) -> Note:
        """
        Create a new note.

        Args:
            input: Note data

        Returns:
            Created note
        """
        from exegia_graphql.resolvers.users import resolve_create_note

        return await resolve_create_note(info, input)

    @strawberry.mutation
    async def update_note(self, info: strawberry.Info, input: UpdateNoteInput) -> Note:
        """Update an existing note."""
        from exegia_graphql.resolvers.users import resolve_update_note

        return await resolve_update_note(info, input)

    @strawberry.mutation
    async def delete_note(self, info: strawberry.Info, input: DeleteNoteInput) -> bool:
        """Delete a note."""
        from exegia_graphql.resolvers.users import resolve_delete_note

        return await resolve_delete_note(info, input)

    @strawberry.mutation
    async def create_favorite(
        self, info: strawberry.Info, input: CreateFavoriteInput
    ) -> Favorite:
        """Add a passage to favorites."""
        from exegia_graphql.resolvers.users import resolve_create_favorite

        return await resolve_create_favorite(info, input)

    @strawberry.mutation
    async def delete_favorite(
        self, info: strawberry.Info, input: DeleteFavoriteInput
    ) -> bool:
        """Remove a passage from favorites."""
        from exegia_graphql.resolvers.users import resolve_delete_favorite

        return await resolve_delete_favorite(info, input)

    @strawberry.mutation
    async def create_comment(
        self, info: strawberry.Info, input: CreateCommentInput
    ) -> Comment:
        """Create a new comment."""
        from exegia_graphql.resolvers.users import resolve_create_comment

        return await resolve_create_comment(info, input)

    @strawberry.mutation
    async def update_comment(
        self, info: strawberry.Info, input: UpdateCommentInput
    ) -> Comment:
        """Update an existing comment."""
        from exegia_graphql.resolvers.users import resolve_update_comment

        return await resolve_update_comment(info, input)

    @strawberry.mutation
    async def delete_comment(
        self, info: strawberry.Info, input: DeleteCommentInput
    ) -> bool:
        """Delete a comment."""
        from exegia_graphql.resolvers.users import resolve_delete_comment

        return await resolve_delete_comment(info, input)


schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_router = GraphQLRouter(schema, graphql_ide="graphiql")
