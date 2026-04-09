from extensions import supabase


def list_import_history(discogs_username, limit=50):
    response = (
        supabase.table("imports")
        .select(
            "id, discogs_username, folder_id, folder_name, status, added_count, "
            "skipped_count, failed_count, results_json, created_at"
        )
        .eq("discogs_username", discogs_username)
        .order("created_at", desc=True)
        .limit(max(1, int(limit)))
        .execute()
    )

    return getattr(response, "data", None) or []


def create_import_history_entry(
    discogs_username,
    folder_id,
    folder_name,
    status,
    added_count,
    skipped_count,
    failed_count,
    results,
):
    response = (
        supabase.table("imports")
        .insert(
            {
                "discogs_username": discogs_username,
                "folder_id": int(folder_id),
                "folder_name": folder_name,
                "status": status,
                "added_count": int(added_count),
                "skipped_count": int(skipped_count),
                "failed_count": int(failed_count),
                "results_json": results,
            }
        )
        .execute()
    )

    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None
