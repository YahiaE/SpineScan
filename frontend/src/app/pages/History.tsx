import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { formatDistanceToNow } from "date-fns";
import { History, ScanLine, AlertCircle } from "lucide-react";
import { useAppContext } from "../store";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";

type ImportHistoryEntry = {
  id: number;
  folder_id: number;
  folder_name?: string | null;
  added_count: number;
  failed_count: number;
  created_at: string;
};

type ImportHistoryResponse = {
  imports: ImportHistoryEntry[];
};

export function HistoryPage() {
  const navigate = useNavigate();
  const { scanHistory } = useAppContext();
  const [imports, setImports] = useState<ImportHistoryEntry[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const loadHistory = async () => {
      setLoadingHistory(true);

      try {
        const res = await apiFetch(`${API_BASE}/discogs/import-history`, {
          method: "GET",
        });

        if (!res.ok) {
          throw new Error("Failed to load import history");
        }

        const payload = (await res.json()) as ImportHistoryResponse;
        if (!cancelled) {
          setImports(payload.imports ?? []);
        }
      } catch {
        if (!cancelled) {
          setImports([]);
        }
      } finally {
        if (!cancelled) {
          setLoadingHistory(false);
        }
      }
    };

    void loadHistory();

    return () => {
      cancelled = true;
    };
  }, []);

  const hasDurableHistory = imports.length > 0;
  const entries = hasDurableHistory
    ? imports.map((item) => ({
        key: String(item.id),
        count: item.added_count,
        failedCount: item.failed_count,
        folderName: item.folder_name ?? undefined,
        date: item.created_at,
      }))
    : scanHistory.map((scan, index) => ({
        key: `${scan.date}-${index}`,
        count: scan.count,
        failedCount: scan.failedCount,
        folderName: scan.folderName,
        date: scan.date,
      }));
  const shouldShowEmpty = !loadingHistory && entries.length === 0;

  return (
    <div className="flex flex-col h-full bg-neutral-950 p-6 overflow-y-auto">
      <div className="space-y-2 mb-6">
        <div className="flex items-center gap-2 text-neutral-300">
          <History className="w-5 h-5" />
          <h1 className="text-2xl font-bold text-white">Scan History</h1>
        </div>
        <p className="text-neutral-400">Review your recent scan activity.</p>
      </div>

      {shouldShowEmpty ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center border border-neutral-800 border-dashed rounded-2xl p-8 gap-4">
          <ScanLine className="w-10 h-10 text-neutral-600" />
          <div>
            <p className="text-white font-medium">No scan history yet</p>
            <p className="text-neutral-500 text-sm mt-1">
              Your recent scans will appear here.
            </p>
          </div>
          <button
            onClick={() => navigate("/scan")}
            className="bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-3 rounded-xl transition-colors"
          >
            Start a Scan
          </button>
        </div>
      ) : loadingHistory && entries.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center border border-neutral-800 border-dashed rounded-2xl p-8 gap-4">
          <p className="text-neutral-500">Loading scan history...</p>
        </div>
      ) : (
        <div className="space-y-3 pb-6">
          {entries.map((scan) => (
            <div
              key={scan.key}
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
