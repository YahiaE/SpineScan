import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useAppContext } from "../store";
import { CheckCircle2, Disc3, AlertCircle, SkipForward } from "lucide-react";
import { motion } from "motion/react";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";
const IMPORT_REQUEST_TIMEOUT_MS = 120000;
const FINALIZE_REQUEST_TIMEOUT_MS = 15000;

type ImportResponse = {
  folder_id: number;
  added_count: number;
  skipped_count: number;
  failed_count: number;
  results: Array<{
    id: string;
    status: "added" | "failed" | "rejected" | "skipped";
    artist: string;
    title: string;
    release_id?: number;
    message?: string;
  }>;
};

export function Importing() {
  const navigate = useNavigate();
  const {
    scannedAlbums,
    addHistory,
    capturedImage,
    selectedCollectionId,
    collectionFolders,
    setCapturedImage,
    setLastImportSummary,
  } = useAppContext();
  const [results, setResults] = useState<
    Record<string, ImportResponse["results"][number]>
  >({});
  const [error, setError] = useState<string | null>(null);
  const hasStartedImportRef = useRef(false);

  useEffect(() => {
    if (scannedAlbums.length === 0 || selectedCollectionId === null) {
      navigate("/review");
      return;
    }

    // Prevent duplicate POST /discogs/import calls from effect re-runs.
    if (hasStartedImportRef.current) {
      return;
    }
    hasStartedImportRef.current = true;

    let cancelled = false;

    const runImport = async () => {
      const cleanupPayload = capturedImage ? { path: capturedImage } : {};

      // Do not block the import flow on cleanup calls.
      void (async () => {
        const finalizeController = new AbortController();
        const finalizeTimeoutId = window.setTimeout(
          () => finalizeController.abort(),
          FINALIZE_REQUEST_TIMEOUT_MS,
        );

        try {
          await apiFetch(`${API_BASE}/data/capture/finalize`, {
            method: "POST",

            signal: finalizeController.signal,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(cleanupPayload),
          });
        } catch {
          // Best-effort cleanup should not block or fail imports.
        } finally {
          window.clearTimeout(finalizeTimeoutId);
        }
      })();
      setCapturedImage(null);

      try {
        const controller = new AbortController();
        const timeoutId = window.setTimeout(
          () => controller.abort(),
          IMPORT_REQUEST_TIMEOUT_MS,
        );

        let res: Response;
        try {
          res = await apiFetch(`${API_BASE}/discogs/import`, {
            method: "POST",

            signal: controller.signal,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              folder_id: selectedCollectionId,
              entries: scannedAlbums.map((album) => ({
                id: album.id,
                artist: album.artist,
                title: album.title,
                release_id: album.validation?.releaseId,
              })),
            }),
          });
        } finally {
          window.clearTimeout(timeoutId);
        }

        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          throw new Error(payload?.error ?? "Import failed");
        }

        const payload = (await res.json()) as ImportResponse;
        if (cancelled) return;

        const resultMap = Object.fromEntries(
          payload.results.map((result) => [result.id, result]),
        );
        setResults(resultMap);
        setLastImportSummary({
          folderId: payload.folder_id,
          addedCount: payload.added_count,
          skippedCount: payload.skipped_count,
          failedCount: payload.failed_count,
          results: payload.results,
        });

        const addedCount = payload.results.filter(
          (result) => result.status === "added",
        ).length;
        const selectedFolderName = collectionFolders.find(
          (folder) => folder.id === payload.folder_id,
        )?.name;

        addHistory({
          count: addedCount,
          failedCount: payload.failed_count,
          folderName: selectedFolderName,
        });

        if (payload.failed_count === 0) {
          window.setTimeout(() => navigate("/success"), 900);
        } else {
          setError(
            "Some entries could not be imported. Review the results below.",
          );
        }
      } catch (importError) {
        if (!cancelled) {
          const isTimeoutError =
            importError instanceof DOMException &&
            importError.name === "AbortError";
          setError(
            isTimeoutError
              ? "Import timed out. Please retry; your folder cache warm-up may still be running in the background."
              : importError instanceof Error
                ? importError.message
                : "Import failed",
          );
        }
      }
    };

    runImport();

    return () => {
      cancelled = true;
    };
  }, [
    addHistory,
    collectionFolders,
    capturedImage,
    navigate,
    scannedAlbums,
    selectedCollectionId,
    setCapturedImage,
    setLastImportSummary,
  ]);

  const completedCount = Object.keys(results).length;
  const progress =
    scannedAlbums.length > 0
      ? (completedCount / scannedAlbums.length) * 100
      : 0;

  return (
    <div className="flex flex-col h-full bg-neutral-950 p-6 overflow-hidden">
      <div className="mt-12 mb-8 text-center shrink-0">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="inline-block mb-4"
        >
          <Disc3 className="w-12 h-12 text-emerald-500" />
        </motion.div>
        <h1 className="text-2xl font-bold text-white">
          Adding to collection...
        </h1>
      </div>

      <div className="w-full h-3 bg-neutral-900 rounded-full mb-8 overflow-hidden border border-neutral-800 shrink-0">
        <motion.div
          className="h-full bg-emerald-500 rounded-full"
          initial={{ width: "0%" }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.3 }}
        />
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 pb-8">
        {scannedAlbums.map((album) => {
          if (!album) return null;
          const result = results[album.id];
          const isDone = Boolean(result);
          const isAdded = result?.status === "added";
          const isSkipped = result?.status === "skipped";
          const isFailed =
            result?.status === "failed" || result?.status === "rejected";

          return (
            <motion.div
              key={album.id}
              initial={{ opacity: 0.3 }}
              animate={{ opacity: isDone ? 1 : 0.3, x: isDone ? 0 : -5 }}
              className="flex items-start gap-3 p-3 bg-neutral-900/50 rounded-xl border border-neutral-800/50"
            >
              <div className="w-6 flex justify-center shrink-0">
                {isAdded ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                ) : isSkipped ? (
                  <SkipForward className="w-5 h-5 text-amber-400" />
                ) : isFailed ? (
                  <AlertCircle className="w-5 h-5 text-red-400" />
                ) : (
                  <div className="w-2 h-2 rounded-full bg-neutral-600" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p
                  className={`text-sm font-medium ${isDone ? "text-white" : "text-neutral-500"} truncate`}
                >
                  {album.artist} — {album.title}
                </p>
                {result?.message && (
                  <p
                    className={`text-xs mt-1 ${
                      isFailed
                        ? "text-red-400"
                        : isSkipped
                          ? "text-amber-300"
                          : "text-neutral-500"
                    }`}
                  >
                    {result.message}
                  </p>
                )}
              </div>
            </motion.div>
          );
        })}
      </div>

      {error && (
        <div className="shrink-0 pt-4 border-t border-neutral-900 space-y-3">
          <p className="text-sm text-red-400 text-center">{error}</p>
          <button
            onClick={() => navigate("/review")}
            className="w-full bg-neutral-800 hover:bg-neutral-700 text-white py-3 rounded-xl font-medium transition-colors"
          >
            Back to Review
          </button>
        </div>
      )}
    </div>
  );
}
