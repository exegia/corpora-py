# Database Models Module

SQLAlchemy models and database schema for user data storage.

## Overview

This module defines the database schema for user-specific data: notes, favorites, downloaded datasets, and user profiles.

## Architecture

```
GraphQL/REST Request
    ↓
SQLAlchemy Models (ORM)
    ↓
Database (PostgreSQL via Supabase)
```

## Files

```
app/models/
├── user.py          # User profile model
├── note.py          # Notes model
├── favorite.py      # Favorites model
└── dataset.py       # User downloaded datasets
```

## Database Schema

### Users Table

Managed by Supabase Auth (`auth.users`). Extended by `profiles` table:

```sql
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id),
    username TEXT UNIQUE,
    full_name TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Notes Table

```sql
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL,
    reference TEXT NOT NULL,  -- e.g., "Genesis 1:1", "word_12345"
    content TEXT NOT NULL,
    tags TEXT[],              -- Optional tags
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Indexes
    INDEX idx_notes_user (user_id),
    INDEX idx_notes_dataset (dataset_id),
    INDEX idx_notes_reference (reference)
);

-- Row Level Security
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own notes"
    ON notes FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own notes"
    ON notes FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own notes"
    ON notes FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own notes"
    ON notes FOR DELETE
    USING (auth.uid() = user_id);
```

### Favorites Table

```sql
CREATE TABLE favorites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL,
    reference TEXT NOT NULL,  -- e.g., "John 3:16"
    note TEXT,                -- Optional quick note
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent duplicates
    UNIQUE (user_id, dataset_id, reference),

    -- Indexes
    INDEX idx_favorites_user (user_id),
    INDEX idx_favorites_dataset (dataset_id)
);

-- Row Level Security
ALTER TABLE favorites ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own favorites"
    ON favorites FOR ALL
    USING (auth.uid() = user_id);
```

### User Datasets Table

Tracks which datasets a user has downloaded locally:

```sql
CREATE TABLE user_datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL,
    dataset_type TEXT NOT NULL,  -- 'bible', 'lexicon', 'dictionary', 'book'
    local_path TEXT,             -- Where dataset is stored locally
    version TEXT,                -- Dataset version
    downloaded_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed TIMESTAMPTZ,

    -- Prevent duplicates
    UNIQUE (user_id, dataset_id),

    -- Indexes
    INDEX idx_user_datasets_user (user_id),
    INDEX idx_user_datasets_type (dataset_type)
);

-- Row Level Security
ALTER TABLE user_datasets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own datasets"
    ON user_datasets FOR ALL
    USING (auth.uid() = user_id);
```

## SQLAlchemy Models

### User Model (`user.py`)

see @user

### Note Model (`note.py`)

see @note

### Favorite Model (`favorite.py`)

see @favorite

### UserDataset Model (`dataset.py`)

## Migrations

Database migrations managed with Alembic:

```bash
# Create migration
alembic revision --autogenerate -m "Add notes table"

# Run migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Row Level Security (RLS)

All user data tables use RLS to ensure users can only access their own data:

```sql
-- Enable RLS
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own notes
CREATE POLICY "Users view own notes"
    ON notes FOR SELECT
    USING (auth.uid() = user_id);
```

RLS is enforced at the database level, providing security even if application code has bugs.

## Indexes

Optimized for common queries:

```sql
-- User lookups
CREATE INDEX idx_notes_user ON notes(user_id);
CREATE INDEX idx_favorites_user ON favorites(user_id);

-- Dataset lookups
CREATE INDEX idx_notes_dataset ON notes(dataset_id);
CREATE INDEX idx_notes_reference ON notes(reference);

-- Composite indexes
CREATE INDEX idx_notes_user_dataset ON notes(user_id, dataset_id);
```

## Best Practices

1. **Always use RLS**: Never rely solely on application-level security
2. **Index queried fields**: user_id, dataset_id, reference
3. **Use transactions**: Wrap related operations in transactions
4. **Validate input**: Sanitize user input before database operations
5. **Use CASCADE**: ON DELETE CASCADE for user data cleanup
6. **Timestamp everything**: created_at and updated_at for audit trails
