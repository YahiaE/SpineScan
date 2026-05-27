import { useNavigate } from "react-router";
import { formatDistanceToNow } from "date-fns";
import { History, ScanLine, AlertCircle } from "lucide-react";
import { useAppContext } from "../store";

function getStatusLabel(status?: string) {
  switch (status) {
    case "added":
      return "Imported";
    case "skipped":
      return "Skipped";
    case "failed":
      return "Failed";
    case "rejected":
      return "Rejected";
    default:
      return "Scanned";
  }
}

function getStatusClasses(status?: string) {
  switch (status) {
    case "added":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    case "skipped":
      return "border-amber-500/40 bg-amber-500/10 text-amber-300";
    case "failed":
    case "rejected":
      return "border-red-500/40 bg-red-500/10 text-red-300";
    default:
      return "border-neutral-700 bg-neutral-800/70 text-neutral-300";
  }
}

export function HistoryPage() {
  const navigate = useNavigate();
  const { scanHistory } = useAppContext();
  const entries = scanHistory.map((scan, index) => ({
    key: `${scan.date}-${index}`,
    count: scan.count,
    failedCount: scan.failedCount,
    folderName: scan.folderName,
    date: scan.date,
    scannedEntries: scan.scannedEntries,
  }));
  const shouldShowEmpty = entries.length === 0;

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
      ) : (
        <div className="space-y-3 pb-6">
          {entries.map((scan) => (
            <div
              key={scan.key}
              className="bg-neutral-900 border border-neutral-800 rounded-xl p-4"
            >
              {(() => {
                const statusBreakdown = (scan.scannedEntries ?? []).reduce(
                  (acc, entry) => {
                    if (entry.status === "added") {
                      acc.imported += 1;
                    } else if (entry.status === "skipped") {
                      acc.skipped += 1;
                    } else if (
                      entry.status === "failed" ||
                      entry.status === "rejected"
                    ) {
                      acc.failed += 1;
                    } else {
                      acc.scanned += 1;
                    }
                    return acc;
                  },
                  { imported: 0, skipped: 0, failed: 0, scanned: 0 },
                );

                return (
                  <>
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
                    {!!scan.scannedEntries?.length && (
                      <div className="mt-3 border-t border-neutral-800 pt-3 space-y-1.5">
                        <p className="text-xs uppercase tracking-wide text-neutral-500">
                          Scanned Entries ({scan.scannedEntries.length})
                        </p>
                        <div className="flex flex-wrap gap-2 text-xs text-neutral-300">
                          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-emerald-300">
                            Imported: {statusBreakdown.imported}
                          </span>
                          <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-300">
                            Skipped: {statusBreakdown.skipped}
                          </span>
                          <span className="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-red-300">
                            Failed: {statusBreakdown.failed}
                          </span>
                          {statusBreakdown.scanned > 0 && (
                            <span className="rounded-full border border-neutral-700 bg-neutral-800/70 px-2 py-0.5 text-neutral-300">
                              Scanned only: {statusBreakdown.scanned}
                            </span>
                          )}
                        </div>
                        {scan.scannedEntries.slice(0, 5).map((entry) => (
                          <div
                            key={entry.id}
                            className="flex items-center justify-between gap-2 rounded-md bg-neutral-900/60 px-2 py-1"
                          >
                            <p className="text-sm text-neutral-300 truncate">
                              {entry.artist} — {entry.title}
                            </p>
                            <span
                              className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] ${getStatusClasses(entry.status)}`}
                            >
                              {getStatusLabel(entry.status)}
                            </span>
                          </div>
                        ))}
                        {scan.scannedEntries.length > 5 && (
                          <p className="text-xs text-neutral-500">
                            ...and {scan.scannedEntries.length - 5} more
                          </p>
                        )}
                      </div>
                    )}
                    {!scan.scannedEntries?.length && (
                      <p className="mt-3 text-xs text-neutral-500 border-t border-neutral-800 pt-3">
                        Entry-level details are unavailable for this older scan.
                      </p>
                    )}
                  </>
                );
              })()}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
