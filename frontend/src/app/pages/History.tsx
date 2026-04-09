import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { formatDistanceToNow } from "date-fns";
import {
  History,
  ScanLine,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  SkipForward,
} from "lucide-react";
import { useAppContext } from "../store";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";

type ImportHistoryEntry = {
  id: number;
  folder_id: number;
  folder_name?: string | null;
  status: string;
  added_count: number;
  skipped_count: number;
  failed_count: number;
  created_at: string;
  results_json?: Array<{
    id: string;
    status: "added" | "failed" | "rejected" | "skipped";
    artist: string;
    title: string;
    release_id?: number;
    message?: string;
  }>;
};

type ImportHistoryResponse = {
  imports: ImportHistoryEntry[];
};

export function HistoryPage() {
  const navigate = useNavigate();
  const { scanHistory } = useAppContext();
  const [imports, setImports] = useState<ImportHistoryEntry[]>([]);
  const [expandedImportIds, setExpandedImportIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadHistory = async () => {
      setLoading(true);
      setLoadError(null);

      try {
        const res = await apiFetch(`${API_BASE}/discogs/import-history`, {
          method: "GET",
        });

        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          throw new Error(payload?.error ?? "Failed to load import history");
        }

        const payload = (await res.json()) as ImportHistoryResponse;
        if (!cancelled) {
          setImports(payload.imports ?? []);
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(
            error instanceof Error
              ? error.message
              : "Failed to load import history",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadHistory();

    return () => {
      cancelled = true;
    };
  }, []);

  const hasDurableHistory = imports.length > 0;
  const hasLocalHistory = scanHistory.length > 0;
  const shouldShowEmpty = !loading && !hasDurableHistory && !hasLocalHistory;

  const toggleExpandedImport = (importId: number) => {
    setExpandedImportIds((current) =>
      current.includes(importId)
        ? current.filter((id) => id !== importId)
        : [...current, importId],
    );
  };

  const renderResultIcon = (status: string) => {
    if (status === "added") {
      return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    }

    if (status === "skipped") {
      return <SkipForward className="w-4 h-4 text-amber-300" />;
    }

    return <AlertCircle className="w-4 h-4 text-red-400" />;
  };

  return (
    <div className="flex flex-col h-full bg-neutral-950 p-6 overflow-y-auto">
      <div className="space-y-2 mb-6">
        <div className="flex items-center gap-2 text-neutral-300">
          <History className="w-5 h-5" />
          <h1 className="text-2xl font-bold text-white">Scan History</h1>
        </div>
        <p className="text-neutral-400">Review your recent Discogs imports.</p>
      </div>

      {loading ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center border border-neutral-800 border-dashed rounded-2xl p-8 gap-4">
          <p className="text-neutral-400">Loading import history...</p>
        </div>
      ) : shouldShowEmpty ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center border border-neutral-800 border-dashed rounded-2xl p-8 gap-4">
          <ScanLine className="w-10 h-10 text-neutral-600" />
          <div>
            <p className="text-white font-medium">No import history yet</p>
            <p className="text-neutral-500 text-sm mt-1">
              Your successful imports will appear here.
            </p>
          </div>
          <button
            onClick={() => navigate("/scan")}
            className="bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-3 rounded-xl transition-colors"
          >
            Start a Scan
          </button>
        </div>
      ) : (
        <div className="space-y-3 pb-6">
          {loadError && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {loadError}
            </div>
          )}

          {hasDurableHistory
            ? imports.map((item) => (
                <div
                  key={item.id}
                  className="bg-neutral-900 border border-neutral-800 rounded-xl p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-white font-medium">
                        {item.added_count} Albums Added
                      </p>
                      <p className="text-sm text-neutral-500 mt-1">
                        Imported{" "}
                        {formatDistanceToNow(new Date(item.created_at), {
                          addSuffix: true,
                        })}
                      </p>
                    </div>
                    {item.failed_count > 0 && (
                      <div className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs text-amber-300">
                        <AlertCircle className="w-3.5 h-3.5" />
                        {item.failed_count} failed
                      </div>
                    )}
                  </div>
                  {(item.folder_name || item.skipped_count > 0) && (
                    <div className="mt-3 space-y-1 text-sm text-neutral-400">
                      {item.folder_name && (
                        <p>Collection: {item.folder_name}</p>
                      )}
                      {item.skipped_count > 0 && (
                        <p>Skipped duplicates: {item.skipped_count}</p>
                      )}
                    </div>
                  )}

                  {(item.results_json?.length ?? 0) > 0 && (
                    <div className="mt-4 border-t border-neutral-800 pt-4">
                      <button
                        onClick={() => toggleExpandedImport(item.id)}
                        className="flex w-full items-center justify-between text-left text-sm text-neutral-300 hover:text-white transition-colors"
                      >
                        <span>
                          {expandedImportIds.includes(item.id)
                            ? "Hide entries"
                            : `Show entries (${item.results_json?.length ?? 0})`}
                        </span>
                        {expandedImportIds.includes(item.id) ? (
                          <ChevronUp className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                      </button>

                      {expandedImportIds.includes(item.id) && (
                        <div className="mt-3 space-y-2">
                          {item.results_json?.map((result) => (
                            <div
                              key={`${item.id}-${result.id}`}
                              className="flex items-start gap-3 rounded-lg border border-neutral-800 bg-neutral-950/70 p-3"
                            >
                              <div className="mt-0.5 shrink-0">
                                {renderResultIcon(result.status)}
                              </div>
                              <div className="min-w-0 flex-1">
                                <p className="text-sm font-medium text-white">
                                  {result.artist} — {result.title}
                                </p>
                                <p className="mt-1 text-xs text-neutral-500">
                                  {result.status === "added"
                                    ? "Added to Discogs"
                                    : result.status === "skipped"
                                      ? "Skipped"
                                      : "Not imported"}
                                </p>
                                {result.message && (
                                  <p className="mt-1 text-xs text-neutral-400">
                                    {result.message}
                                  </p>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))
            : scanHistory.map((scan, index) => (
                <div
                  key={`${scan.date}-${index}`}
                  className="bg-neutral-900 border border-neutral-800 rounded-xl p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-white font-medium">
                        {scan.count} Albums Added
                      </p>
                      <p className="text-sm text-neutral-500 mt-1">
                        Imported{" "}
                        {formatDistanceToNow(new Date(scan.date), {
                          addSuffix: true,
                        })}
                      </p>
                    </div>
                    {scan.failedCount > 0 && (
                      <div className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs text-amber-300">
                        <AlertCircle className="w-3.5 h-3.5" />
                        {scan.failedCount} failed
                      </div>
                    )}
                  </div>
                  {scan.folderName && (
                    <p className="text-sm text-neutral-400 mt-3">
                      Collection: {scan.folderName}
                    </p>
                  )}
                </div>
              ))}
        </div>
      )}
    </div>
  );
}
