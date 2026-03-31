import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { CollectionFolder, useAppContext } from "../store";
import {
  Trash2,
  Edit2,
  Plus,
  ArrowRight,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

const API_BASE = "/api";

type FolderResponse = {
  folders: CollectionFolder[];
};

type ValidationResponse = {
  validations: Array<{
    id: string;
    status: "valid" | "invalid";
    message?: string;
    release_id?: number;
    matched_artist?: string;
    matched_title?: string;
  }>;
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
  } = useAppContext();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editArtist, setEditArtist] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [loadingFolders, setLoadingFolders] = useState(false);
  const [folderError, setFolderError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const loadFolders = async () => {
      setLoadingFolders(true);
      setFolderError(null);

      try {
        const res = await fetch(`${API_BASE}/discogs/collection-folders`, {
          credentials: "include",
        });

        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          throw new Error(payload?.error ?? "Failed to load collections");
        }

        const payload = (await res.json()) as FolderResponse;
        if (cancelled) return;

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

    setValidating(true);
    setValidationError(null);

    try {
      const res = await fetch(`${API_BASE}/discogs/validate`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entries: scannedAlbums.map((album) => ({
            id: album.id,
            artist: album.artist,
            title: album.title,
          })),
        }),
      });

      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.error ?? "Validation failed");
      }

      const payload = (await res.json()) as ValidationResponse;
      const validationMap = new Map(
        payload.validations.map((item) => [item.id, item]),
      );

      setScannedAlbums(
        scannedAlbums.map((album) => {
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
    } catch (error) {
      setValidationError(
        error instanceof Error ? error.message : "Validation failed",
      );
    } finally {
      setValidating(false);
    }
  };

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
    <div className="flex flex-col h-full bg-neutral-950">
      <div className="p-6 pb-2 space-y-4">
        <h1 className="text-2xl font-bold text-white mb-1">Detected Albums</h1>
        <p className="text-neutral-400 text-sm">
          Review and correct any errors.
        </p>

        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 space-y-4">
          <div>
            <p className="text-sm text-neutral-400 mb-2">
              Target Discogs collection
            </p>
            <select
              value={selectedCollectionId ?? ""}
              onChange={(event) =>
                setSelectedCollectionId(Number(event.target.value))
              }
              disabled={loadingFolders || collectionFolders.length === 0}
              className="w-full bg-neutral-950 text-white px-3 py-3 rounded-lg border border-neutral-700 focus:outline-none focus:border-emerald-500"
            >
              {collectionFolders.map((folder) => (
                <option key={folder.id} value={folder.id}>
                  {folder.name} ({folder.count})
                </option>
              ))}
            </select>
            {folderError && (
              <p className="text-red-400 text-sm mt-2">{folderError}</p>
            )}
          </div>

          <div className="flex gap-2 text-sm">
            <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
              {validCount} valid
            </span>
            <span className="px-3 py-1 rounded-full bg-red-500/10 text-red-300 border border-red-500/30">
              {invalidCount} invalid
            </span>
            <span className="px-3 py-1 rounded-full bg-neutral-800 text-neutral-300 border border-neutral-700">
              {pendingCount} pending
            </span>
          </div>

          <div className="flex gap-3">
            <button
              onClick={validateAlbums}
              disabled={validating || scannedAlbums.length === 0}
              className="flex-1 bg-neutral-800 hover:bg-neutral-700 text-white py-3 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
            >
              <ShieldCheck className="w-4 h-4" />
              {validating ? "Validating..." : "Validate Entries"}
            </button>
            <button
              onClick={removeInvalid}
              disabled={invalidCount === 0}
              className="flex-1 bg-red-500/10 hover:bg-red-500/20 text-red-300 py-3 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
            >
              <ShieldAlert className="w-4 h-4" /> Remove Invalid
            </button>
          </div>
          {validationError && (
            <p className="text-red-400 text-sm">{validationError}</p>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
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
                  : "Validate this entry before importing");

            return (
              <motion.div
                key={album.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex items-start justify-between gap-3 group overflow-hidden"
              >
                {editingId === album.id ? (
                  <div className="flex-1 flex flex-col gap-2 mr-2">
                    <input
                      value={editArtist}
                      onChange={(event) => setEditArtist(event.target.value)}
                      className="bg-neutral-950 text-white px-3 py-2 rounded-lg border border-neutral-700 text-sm focus:outline-none focus:border-emerald-500"
                      placeholder="Artist"
                    />
                    <input
                      value={editTitle}
                      onChange={(event) => setEditTitle(event.target.value)}
                      className="bg-neutral-950 text-white px-3 py-2 rounded-lg border border-neutral-700 text-sm focus:outline-none focus:border-emerald-500"
                      placeholder="Title"
                    />
                    <button
                      onClick={saveEdit}
                      className="bg-emerald-600 hover:bg-emerald-500 transition-colors text-white py-2 rounded-lg text-sm mt-1 font-medium"
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
                  </div>
                )}

                {editingId !== album.id && (
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleEdit(album.id)}
                      className="p-2 text-neutral-500 hover:text-white bg-neutral-800/50 hover:bg-neutral-700 rounded-lg transition-colors"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleRemove(album.id)}
                      className="p-2 text-red-400 hover:text-red-300 bg-red-400/10 hover:bg-red-400/20 rounded-lg transition-colors"
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
          className="w-full py-4 border-2 border-dashed border-neutral-800 rounded-xl text-neutral-400 font-medium flex items-center justify-center gap-2 hover:bg-neutral-900 hover:text-white hover:border-neutral-600 transition-colors mt-2"
        >
          <Plus className="w-4 h-4" /> Add Missing Album
        </button>
      </div>

      <div className="p-6 bg-neutral-950 border-t border-neutral-900 shrink-0">
        <button
          onClick={() => navigate("/confirm")}
          disabled={!canImport}
          className="w-full bg-emerald-600 hover:bg-emerald-500 transition-colors text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 disabled:opacity-50 disabled:hover:bg-emerald-600"
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
