import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ScanSearch, AlertCircle } from "lucide-react";
import { motion } from "motion/react";
import { useAppContext } from "../store";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";

export function Processing() {
  const navigate = useNavigate();
  const { capturedImage, setCapturedImage, setScannedAlbums, setSkippedLines } =
    useAppContext();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      if (!capturedImage) {
        navigate("/scan", { replace: true });
        return;
      }

      try {
        const processUrl = `${API_BASE}/process/latest?path=${encodeURIComponent(capturedImage)}`;

        const res = await apiFetch(processUrl, {
          method: "GET",
        });

        if (cancelled) return;

        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          throw new Error(payload?.error ?? `Server error ${res.status}`);
        }

        const payload = await res.json().catch(() => null);
        const rawResult = payload?.result;

        const resultText =
          typeof rawResult === "string"
            ? rawResult
            : typeof rawResult?.text === "string"
              ? rawResult.text
              : "";

        if (!resultText.trim()) {
          await apiFetch(`${API_BASE}/data/capture/finalize`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: capturedImage ?? undefined }),
          }).catch(() => {});
          setCapturedImage(null);
          throw new Error(
            "No OCR text was returned. Try taking a clearer photo and run again.",
          );
        }

        const allLines = resultText
          .split(/\r?\n/)
          .filter((line: string) => line.trim().length > 0);

        const skipped: string[] = [];
        const parsed = allLines
          .filter((entry: string) => {
            const wordCount = entry.trim().split(/\s+/).length;
            if (wordCount > 12) {
              skipped.push(entry.trim());
              return false;
            }
            // Short title-only lines are validated against Various Artists.
            if (!entry.includes(" - ") && wordCount > 8) {
              skipped.push(entry.trim());
              return false;
            }
            return true;
          })
          .map((entry: string, i: number) => {
            const sep = entry.indexOf(" - ");
            return {
              id: String(i + 1),
              artist: sep < 0 ? "" : entry.slice(0, sep).trim(),
              title: sep < 0 ? entry.trim() : entry.slice(sep + 3).trim(),
              validation: { status: "pending" as const },
            };
          });

        if (parsed.length === 0) {
          await apiFetch(`${API_BASE}/data/capture/finalize`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: capturedImage ?? undefined }),
          }).catch(() => {});
          setCapturedImage(null);
          throw new Error(
            "OCR returned no valid album title lines. Please retake the image.",
          );
        }

        setSkippedLines(skipped);
        setScannedAlbums(parsed);
        navigate("/review");
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Something went wrong");
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [capturedImage, navigate, setScannedAlbums]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 gap-4 text-center bg-neutral-950">
        <AlertCircle className="w-12 h-12 text-red-400" />
        <p className="text-white font-medium">{error}</p>
        <button
          onClick={() => {
            setCapturedImage(null);
            navigate("/scan", { replace: true });
          }}
          className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-xl transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center bg-neutral-950 overflow-y-auto">
      <div className="relative mb-8">
        <motion.div
          animate={{ scale: [1, 1.2, 1], opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          className="absolute inset-0 bg-emerald-500/20 rounded-full blur-xl"
        />
        <div className="bg-neutral-900 p-6 rounded-full border border-neutral-800 relative z-10">
          <ScanSearch className="w-12 h-12 text-emerald-500" />
        </div>
      </div>

      <h2 className="text-2xl font-bold text-white mb-2">
        Analyzing CD spines...
      </h2>
      <p className="text-neutral-400">
        Extracting text and matching with Discogs database.
      </p>

      <div className="w-full max-w-xs h-2 bg-neutral-800 rounded-full mt-10 overflow-hidden relative">
        <motion.div
          animate={{ x: ["-100%", "100%"] }}
          transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          className="absolute top-0 bottom-0 w-1/2 bg-emerald-500 rounded-full"
        />
      </div>
    </div>
  );
}
