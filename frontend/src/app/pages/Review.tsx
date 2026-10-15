import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { CollectionFolder, useAppContext } from "../store";
import {
  Trash2,
  Edit2,
  Plus,
  ArrowRight,
  ShieldCheck,
  ShieldAlert,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";

type FolderResponse = {
  folders: CollectionFolder[];
};

type ValidationResponse = {
  validations: Array<{
    id: string;
    status: "pending" | "valid" | "invalid";
    message?: string;
    release_id?: number;
    matched_artist?: string;
    matched_title?: string;
  }>;
  retry_ids?: string[];
};

type ReleaseOption = {
  release_id: number;
  matched_artist: string;
  matched_title: string;
  year: number | null;
  country: string | null;
  formats: string[];
  labels: string[];
  catno: string | null;
  is_standard_album: boolean;
  is_special_edition: boolean;
};

export function Review() {
  const navigate = useNavigate();
  const {
    scannedAlbums,
    setScannedAlbums,
    collectionFolders,
    setCollectionFolders,
    selectedCollectionId,
    setSelectedCollectionId,
    skippedLines,
  } = useAppContext();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editArtist, setEditArtist] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [loadingFolders, setLoadingFolders] = useState(false);
  const [refreshingCollection, setRefreshingCollection] = useState(false);
  const [collectionRefreshMessage, setCollectionRefreshMessage] = useState<{
    text: string;
    error: boolean;
  } | null>(null);
  const [editionOptionsById, setEditionOptionsById] = useState<
    Record<string, ReleaseOption[]>
  >({});
  const [openEditionId, setOpenEditionId] = useState<string | null>(null);
  const [loadingEditionId, setLoadingEditionId] = useState<string | null>(null);
  const [editionErrorById, setEditionErrorById] = useState<
    Record<string, string>
  >({});
  const [folderError, setFolderError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const pollAttemptsRef = useRef(0);
  const [showSkipped, setShowSkipped] = useState(false);

  const applyValidationPayload = (payload: ValidationResponse) => {
    const validationMap = new Map(
      payload.validations.map((item) => [item.id, item]),
    );

    setScannedAlbums((currentAlbums) =>
      currentAlbums.map((album) => {
        const validation = validationMap.get(album.id);
        if (!validation) return album;

        return {
          ...album,
          validation: {
            status: validation.status,
            message: validation.message,
            releaseId: validation.release_id,
            matchedArtist: validation.matched_artist,
            matchedTitle: validation.matched_title,
          },
        };
      }),
    );
  };

  const requestValidation = async (
    albumsToValidate: Array<{ id: string; artist: string; title: string }>,
    options?: { background?: boolean; statusOnly?: boolean },
  ) => {
    if (albumsToValidate.length === 0) return;

    const isBackground = options?.background ?? false;
    const statusOnly = options?.statusOnly ?? false;
    if (!isBackground) {
      setValidating(true);
      setValidationError(null);
    }

    try {
      const res = await apiFetch(
        `${API_BASE}/discogs/${statusOnly ? "validation-status" : "validate"}`,
        {
          method: "POST",

          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entries: albumsToValidate }),
        },
      );

      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.error ?? "Validation failed");
      }

      const payload = (await res.json()) as ValidationResponse;
      applyValidationPayload(payload);

      if (statusOnly && payload.retry_ids?.length) {
        const retryIds = new Set(payload.retry_ids);
        const entriesToRetry = albumsToValidate.filter((album) =>
          retryIds.has(album.id),
        );
        if (entriesToRetry.length > 0) {
          const retryRes = await apiFetch(`${API_BASE}/discogs/validate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ entries: entriesToRetry }),
          });

          if (!retryRes.ok) {
            const retryPayload = await retryRes.json().catch(() => null);
            throw new Error(retryPayload?.error ?? "Validation failed");
          }

          const retryPayload = (await retryRes.json()) as ValidationResponse;
          applyValidationPayload(retryPayload);
        }
      }
    } catch (error) {
      setValidationError(
        error instanceof Error ? error.message : "Validation failed",
      );
    } finally {
      if (!isBackground) {
        setValidating(false);
      }
    }
  };

  const handleRefreshCollection = async () => {
    if (selectedCollectionId === null) return;

    setRefreshingCollection(true);
    setCollectionRefreshMessage(null);
    try {
      const response = await apiFetch(
        `${API_BASE}/discogs/collection-cache/refresh`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ folder_id: selectedCollectionId }),
        },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(payload?.error ?? "Could not refresh collection");
      }

      setCollectionRefreshMessage({
        text: `Refreshed ${payload.entry_count} releases from Discogs.`,
        error: false,
      });
    } catch (error) {
      setCollectionRefreshMessage({
        text:
          error instanceof Error ? error.message : "Could not refresh collection",
        error: true,
      });
    } finally {
      setRefreshingCollection(false);
    }
  };

  const toggleEditionOptions = async (album: (typeof scannedAlbums)[number]) => {
    if (openEditionId === album.id) {
      setOpenEditionId(null);
      return;
    }

    setOpenEditionId(album.id);
    if (editionOptionsById[album.id]) return;

    setLoadingEditionId(album.id);
    setEditionErrorById((current) => ({ ...current, [album.id]: "" }));
    try {
      const query = new URLSearchParams({
        artist: album.artist,
        title: album.title,
      });
      const response = await apiFetch(
        `${API_BASE}/discogs/release-options?${query.toString()}`,
        {},
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(payload?.error ?? "Could not load CD editions");
      }
      setEditionOptionsById((current) => ({
        ...current,
        [album.id]: payload.options ?? [],
      }));
    } catch (error) {
      setEditionErrorById((current) => ({
        ...current,
        [album.id]:
          error instanceof Error ? error.message : "Could not load CD editions",
      }));
    } finally {
      setLoadingEditionId(null);
    }
  };

  const selectEdition = (albumId: string, releaseId: number) => {
    const option = editionOptionsById[albumId]?.find(
      (candidate) => candidate.release_id === releaseId,
    );
    if (!option) return;

    setScannedAlbums(
      scannedAlbums.map((album) =>
        album.id === albumId
          ? {
              ...album,
              validation: {
                ...album.validation,
                status: "valid",
                releaseId: option.release_id,
                matchedArtist: option.matched_artist,
                matchedTitle: option.matched_title,
                message: "User-selected Discogs edition",
              },
            }
          : album,
      ),
    );
  };

  useEffect(() => {
    let cancelled = false;

    const loadFolders = async () => {
      setLoadingFolders(true);
      setFolderError(null);

      try {
        const res = await apiFetch(
          `${API_BASE}/discogs/collection-folders`,
          {},
        );

        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          throw new Error(payload?.error ?? "Failed to load collections");
        }

        const payload = (await res.json()) as FolderResponse;
        if (cancelled) return;

        // On page load, trust backend folder counts so the starting view is authoritative.
        setCollectionFolders(payload.folders);
        if (payload.folders.length > 0 && selectedCollectionId === null) {
          setSelectedCollectionId(payload.folders[0].id);
        }
      } catch (error) {
        if (!cancelled) {
          setFolderError(
            error instanceof Error
              ? error.message
              : "Failed to load collections",
          );
        }
      } finally {
        if (!cancelled) {
          setLoadingFolders(false);
        }
      }
    };

    loadFolders();

    return () => {
      cancelled = true;
    };
  }, [selectedCollectionId, setCollectionFolders, setSelectedCollectionId]);

  const handleRemove = (id: string) => {
    setScannedAlbums(scannedAlbums.filter((album) => album.id !== id));
  };

  const handleEdit = (id: string) => {
    const album = scannedAlbums.find((item) => item.id === id);
    if (album) {
      setEditingId(id);
      setEditArtist(album.artist);
      setEditTitle(album.title);
    }
  };

  const saveEdit = () => {
    setScannedAlbums(
      scannedAlbums.map((album) =>
        album.id === editingId
          ? {
              ...album,
              artist: editArtist.trim(),
              title: editTitle.trim(),
              validation: { status: "pending" },
            }
          : album,
      ),
    );
    setEditingId(null);
  };

  const addManual = () => {
    const newId = Math.random().toString(36).substring(2, 9);
    setScannedAlbums([
      ...scannedAlbums,
      {
        id: newId,
        artist: "New Artist",
        title: "New Album",
        validation: { status: "pending" },
      },
    ]);
    setEditingId(newId);
    setEditArtist("New Artist");
    setEditTitle("New Album");
  };

  const validateAlbums = async () => {
    if (scannedAlbums.length === 0) return;
    pollAttemptsRef.current = 0;
    setPollTimedOut(false);
    await requestValidation(
      scannedAlbums.map((album) => ({
        id: album.id,
        artist: album.artist,
        title: album.title,
      })),
    );
  };

  // Calculate exponential backoff with jitter
  const calculatePollDelay = (attempt: number): number => {
    const baseDelay = 1000; // Start at 1 second
    const multiplier = 1.5; // Exponential multiplier
    const maxDelay = 10000; // Cap at 10 seconds
    const jitterFraction = 0.1; // 10% jitter

    if (attempt >= 20) {
      return 15000; // Keep polling slowly after timeout warning
    }

    const exponentialDelay = Math.min(
      baseDelay * Math.pow(multiplier, attempt),
      maxDelay,
    );
    const jitterAmount = exponentialDelay * jitterFraction * Math.random();

    return exponentialDelay + jitterAmount;
  };

  useEffect(() => {
    const queuedAlbums = scannedAlbums.filter(
      (album) => album.validation?.status === "pending",
    );

    if (queuedAlbums.length === 0) {
      pollAttemptsRef.current = 0;
      setPollTimedOut(false);
      return;
    }

    if (validating) {
      return;
    }

    if (pollAttemptsRef.current >= 20 && !pollTimedOut) {
      setPollTimedOut(true);
    }

    const pollDelay = calculatePollDelay(pollAttemptsRef.current);
    const timer = window.setTimeout(() => {
      pollAttemptsRef.current += 1;
      void requestValidation(
        queuedAlbums.map((album) => ({
          id: album.id,
          artist: album.artist,
          title: album.title,
        })),
        { background: true, statusOnly: true },
      );
    }, pollDelay);

    return () => {
      window.clearTimeout(timer);
    };
  }, [scannedAlbums, validating, pollTimedOut]);

  const removeInvalid = () => {
    setScannedAlbums(
      scannedAlbums.filter((album) => album.validation?.status !== "invalid"),
    );
  };

  const validCount = scannedAlbums.filter(
    (album) => album.validation?.status === "valid",
  ).length;
  const invalidCount = scannedAlbums.filter(
    (album) => album.validation?.status === "invalid",
  ).length;
  const pendingCount = scannedAlbums.length - validCount - invalidCount;
  const canImport =
    scannedAlbums.length > 0 &&
    selectedCollectionId !== null &&
    scannedAlbums.every((album) => album.validation?.status === "valid");
  const totalCount = scannedAlbums.length;
  const progressPercent =
    totalCount > 0 ? Math.round((validCount / totalCount) * 100) : 0;
  const queuedPendingCount = scannedAlbums.filter(
    (album) => album.validation?.status === "pending",
  ).length;
  const verificationActive = validating || queuedPendingCount > 0;

  const selectedFolderName =
    collectionFolders.find((folder) => folder.id === selectedCollectionId)
      ?.name ?? "your collection";

  const getValidationClasses = (status?: "pending" | "valid" | "invalid") => {
    if (status === "valid") {
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    }

    if (status === "invalid") {
      return "border-red-500/40 bg-red-500/10 text-red-300";
    }

    return "border-neutral-700 bg-neutral-800/60 text-neutral-300";
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-neutral-950">
      <div className="shrink-0 space-y-2 border-b border-neutral-800 px-3 pb-2 pt-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-white">
              Detected CDs
            </h1>
            <p className="text-xs text-neutral-400">
              {validCount} valid · {invalidCount} invalid · {pendingCount} pending
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-sm tabular-nums text-neutral-300">
            {verificationActive && (
              <Loader2 className="h-4 w-4 animate-spin text-emerald-400" />
            )}
            <span>{validCount}/{totalCount}</span>
          </div>
        </div>

        {totalCount > 0 && (
          <div className="h-1.5 overflow-hidden rounded-full bg-neutral-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        )}

        <div className="flex min-w-0 gap-2">
          <select
            aria-label="Target Discogs collection"
            value={selectedCollectionId ?? ""}
            onChange={(event) => {
              setSelectedCollectionId(Number(event.target.value));
              setCollectionRefreshMessage(null);
            }}
            disabled={loadingFolders || collectionFolders.length === 0}
            className="min-h-11 min-w-0 flex-1 touch-manipulation rounded-lg border border-neutral-700 bg-neutral-950 px-3 text-base text-white focus:border-emerald-500 focus:outline-none sm:text-sm"
          >
            {collectionFolders.map((folder) => (
              <option key={folder.id} value={folder.id}>
                {folder.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => void handleRefreshCollection()}
            disabled={
              loadingFolders ||
              refreshingCollection ||
              selectedCollectionId === null
            }
            className="flex min-h-11 shrink-0 touch-manipulation items-center justify-center gap-1.5 rounded-lg border border-neutral-700 px-3 text-sm font-medium text-neutral-200 transition-colors hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
          >
            <RefreshCw
              className={`h-4 w-4 ${refreshingCollection ? "animate-spin" : ""}`}
            />
            <span>{refreshingCollection ? "Refreshing" : "Refresh"}</span>
          </button>
        </div>

        {(collectionRefreshMessage || folderError) && (
          <p
            className={`text-xs ${collectionRefreshMessage?.error || folderError ? "text-red-400" : "text-emerald-400"}`}
            role="status"
          >
            {collectionRefreshMessage?.text ?? folderError}
          </p>
        )}

        <div className="flex gap-2">
          <button
            onClick={validateAlbums}
            disabled={validating || scannedAlbums.length === 0}
            className="flex min-h-10 flex-1 touch-manipulation items-center justify-center gap-2 rounded-lg bg-neutral-800 px-3 text-sm font-medium text-white transition-colors hover:bg-neutral-700 disabled:opacity-50"
            type="button"
          >
            <ShieldCheck className="h-4 w-4" />
            {validating ? "Validating..." : "Validate"}
          </button>
          <button
            onClick={removeInvalid}
            disabled={invalidCount === 0}
            className="flex min-h-10 flex-1 touch-manipulation items-center justify-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 text-sm font-medium text-red-300 transition-colors hover:bg-red-500/20 disabled:opacity-50"
            type="button"
          >
            <ShieldAlert className="h-4 w-4" /> Remove invalid
          </button>
        </div>

        {validationError && (
          <p className="text-xs text-red-400" role="alert">
            {validationError}
          </p>
        )}
        {pollTimedOut && (
          <p className="text-xs text-yellow-300" role="status">
            Validation is slow. You can proceed with valid entries or{" "}
            <button
              onClick={validateAlbums}
              className="touch-manipulation underline"
              type="button"
            >
              retry
            </button>
            .
          </p>
        )}
        {skippedLines.length > 0 && (
          <details className="text-xs text-neutral-400">
            <summary className="touch-manipulation cursor-pointer">
              {skippedLines.length} OCR line
              {skippedLines.length !== 1 ? "s" : ""} skipped
            </summary>
            <ul className="mt-1 max-h-20 space-y-1 overflow-y-auto">
              {skippedLines.map((line, index) => (
                <li key={index} className="truncate font-mono text-neutral-500">
                  {line}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="min-h-0 flex-1 touch-manipulation overscroll-y-contain overflow-y-auto px-3 py-2">
        <div className="space-y-2 pb-2">
        <AnimatePresence>
          {scannedAlbums.map((album) => {
            if (!album) return null;
            const validationStatus = album.validation?.status ?? "pending";
            const validationMessage =
              album.validation?.message ??
              (validationStatus === "valid"
                ? `${album.validation?.matchedArtist ?? album.artist} - ${album.validation?.matchedTitle ?? album.title}`
                : validationStatus === "invalid"
                  ? "No reliable Discogs match"
                  : "Waiting for Discogs lookup");

            return (
              <motion.div
                key={album.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                className="bg-neutral-900 border border-neutral-800 rounded-xl p-3 flex items-start justify-between gap-2 group overflow-hidden"
              >
                {editingId === album.id ? (
                  <div className="flex-1 flex flex-col gap-2 mr-2">
                    <input
                      value={editArtist}
                      onChange={(event) => setEditArtist(event.target.value)}
                      className="bg-neutral-950 text-white px-3 py-2 rounded-lg border border-neutral-700 text-base sm:text-sm focus:outline-none focus:border-emerald-500"
                      placeholder="Artist"
                    />
                    <input
                      value={editTitle}
                      onChange={(event) => setEditTitle(event.target.value)}
                      className="bg-neutral-950 text-white px-3 py-2 rounded-lg border border-neutral-700 text-base sm:text-sm focus:outline-none focus:border-emerald-500"
                      placeholder="Title"
                    />
                    <button
                      onClick={saveEdit}
                      className="bg-emerald-600 hover:bg-emerald-500 transition-colors text-white py-2 rounded-lg text-base sm:text-sm mt-1 font-medium touch-manipulation"
                    >
                      Save
                    </button>
                  </div>
                ) : (
                  <div className="flex-1 pr-2 space-y-2">
                    <div>
                      <p className="font-semibold text-white">{album.artist}</p>
                      <p className="text-neutral-400 text-sm">{album.title}</p>
                    </div>
                    <div
                      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${getValidationClasses(validationStatus)}`}
                    >
                      {validationStatus === "valid"
                        ? "Valid"
                        : validationStatus === "invalid"
                          ? "Invalid"
                          : "Pending validation"}
                    </div>
                    <p className="text-xs text-neutral-500">
                      {validationMessage}
                    </p>
                    {validationStatus === "valid" &&
                      album.validation?.releaseId && (
                        <div className="space-y-2">
                          <button
                            onClick={() => void toggleEditionOptions(album)}
                            disabled={loadingEditionId === album.id}
                            className="min-h-9 touch-manipulation text-left text-xs font-medium text-emerald-300 underline decoration-emerald-500/40 underline-offset-2 disabled:opacity-60"
                            type="button"
                          >
                            {loadingEditionId === album.id
                              ? "Loading editions..."
                              : openEditionId === album.id
                                ? "Hide other editions"
                                : "Change CD edition"}
                          </button>
                          {openEditionId === album.id &&
                            loadingEditionId !== album.id && (
                              <div className="space-y-1.5">
                                {editionOptionsById[album.id] === undefined ? null :
                                  editionOptionsById[album.id].length > 0 ? (
                                  <select
                                    aria-label={`Discogs CD edition for ${album.title}`}
                                    value={album.validation.releaseId}
                                    onChange={(event) =>
                                      selectEdition(
                                        album.id,
                                        Number(event.target.value),
                                      )
                                    }
                                    className="min-h-11 w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 text-base text-white focus:border-emerald-500 focus:outline-none sm:text-sm"
                                  >
                                    <option value={album.validation.releaseId}>
                                      Current selection: {album.validation.matchedTitle ?? album.title}
                                    </option>
                                    {editionOptionsById[album.id]
                                      .filter(
                                        (option) =>
                                          option.release_id !==
                                          album.validation?.releaseId,
                                      )
                                      .map((option) => {
                                        const category = option.is_standard_album
                                          ? "Standard album"
                                          : option.is_special_edition
                                            ? "Special edition"
                                            : "Other CD";
                                        const details = [
                                          option.year,
                                          option.country,
                                          option.formats.join(", "),
                                          option.catno,
                                        ]
                                          .filter(Boolean)
                                          .join(" · ");

                                        return (
                                          <option
                                            key={option.release_id}
                                            value={option.release_id}
                                          >
                                            {category}: {option.matchedTitle}
                                            {details ? ` · ${details}` : ""}
                                          </option>
                                        );
                                      })}
                                  </select>
                                  ) : (
                                  <p className="text-xs text-neutral-400">
                                    No alternate CD editions found.
                                  </p>
                                  )}
                                {editionErrorById[album.id] && (
                                  <p className="text-xs text-red-400" role="alert">
                                    {editionErrorById[album.id]}
                                  </p>
                                )}
                              </div>
                            )}
                        </div>
                      )}
                  </div>
                )}

                {editingId !== album.id && (
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleEdit(album.id)}
                      className="min-h-11 min-w-11 touch-manipulation p-2 text-neutral-500 hover:text-white bg-neutral-800/50 hover:bg-neutral-700 rounded-lg transition-colors"
                      type="button"
                      aria-label={`Edit ${album.title}`}
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleRemove(album.id)}
                      className="min-h-11 min-w-11 touch-manipulation p-2 text-red-400 hover:text-red-300 bg-red-400/10 hover:bg-red-400/20 rounded-lg transition-colors"
                      type="button"
                      aria-label={`Remove ${album.title}`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>

        <button
          onClick={addManual}
          className="w-full min-h-12 touch-manipulation py-3 border-2 border-dashed border-neutral-800 rounded-xl text-neutral-400 font-medium flex items-center justify-center gap-2 hover:bg-neutral-900 hover:text-white hover:border-neutral-600 transition-colors mt-2"
          type="button"
        >
          <Plus className="w-4 h-4" /> Add Missing Album
        </button>
      </div>
      </div>

      <div
        className="shrink-0 border-t border-neutral-800 bg-neutral-950 px-3 pt-2"
        style={{ paddingBottom: "calc(0.75rem + env(safe-area-inset-bottom, 0px))" }}
      >
        <button
          onClick={() => navigate("/confirm")}
          disabled={!canImport}
          className="w-full min-h-12 touch-manipulation bg-emerald-600 hover:bg-emerald-500 transition-colors text-white px-3 rounded-xl font-medium flex items-center justify-center gap-2 disabled:opacity-50 disabled:hover:bg-emerald-600"
          type="button"
        >
          Import to {selectedFolderName} <ArrowRight className="w-5 h-5" />
        </button>
        {!canImport && (
          <p className="text-neutral-500 text-sm mt-3 text-center">
            Select a collection and validate all remaining entries before
            importing.
          </p>
        )}
      </div>
    </div>
  );
}
