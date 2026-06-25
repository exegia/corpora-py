from watchfiles import Change, watch


def observe(
    dir: str,
    handler=lambda change_type, file_path: print(
        f"{change_type.name.upper()}: {file_path}"
    ),
) -> None:
    print("👁️ Watching current directory...")
    for changes in watch(dir):
        for change_type, file_path in changes:
            # change_type is a Change enum: Change.added, Change.modified, or Change.deleted
            handler(change_type, file_path)
