from extensions import supabase


def normalize_discogs_username(discogs_username):
    return str(discogs_username or "").strip().lower()


def list_import_history(discogs_username, limit=50):
    normalized_username = normalize_discogs_username(discogs_username)

    response = (
        supabase.table("imports")
        .select(
            "id, discogs_username, folder_id, folder_name, status, added_count, "
            "skipped_count, failed_count, results_json, created_at"
        )
        .ilike("discogs_username", normalized_username)
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
    normalized_username = normalize_discogs_username(discogs_username)

    response = (
        supabase.table("imports")
        .insert(
            {
                "discogs_username": normalized_username,
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
