import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";

const SCAN_HISTORY_STORAGE_KEY = "spinescan:scanHistory";
const SCAN_HISTORY_RETENTION_MS = 6 * 60 * 60 * 1000;

function pruneScanHistory(entries: ScanHistoryEntry[]): ScanHistoryEntry[] {
  const cutoff = Date.now() - SCAN_HISTORY_RETENTION_MS;
  return entries.filter((entry) => {
    const parsed = Date.parse(entry.date);
    return Number.isFinite(parsed) && parsed >= cutoff;
  });
}

export interface AlbumValidation {
  status: "pending" | "valid" | "invalid";
  message?: string;
  releaseId?: number;
  matchedArtist?: string;
  matchedTitle?: string;
}

export interface Album {
  id: string;
  artist: string;
  title: string;
  validation?: AlbumValidation;
}

export interface CollectionFolder {
  id: number;
  name: string;
  count: number;
}

export interface ImportResult {
  id: string;
  status: "added" | "failed" | "rejected" | "skipped";
  artist: string;
  title: string;
  release_id?: number;
  message?: string;
}

export interface ImportSummary {
  folderId: number;
  addedCount: number;
  skippedCount: number;
  failedCount: number;
  results: ImportResult[];
}

export interface ScanHistoryEntry {
  date: string;
  count: number;
  failedCount: number;
  folderName?: string;
  scannedEntries?: Array<{
    id: string;
    artist: string;
    title: string;
    status?: ImportResult["status"];
    message?: string;
    releaseId?: number;
  }>;
}

interface AppState {
  isConnected: boolean;
  setConnected: (val: boolean) => void;
  scannedAlbums: Album[];
  setScannedAlbums: (albums: Album[]) => void;
  scanHistory: ScanHistoryEntry[];
  addHistory: (entry: Omit<ScanHistoryEntry, "date">) => void;
  capturedImage: string | null;
  setCapturedImage: (url: string | null) => void;
  collectionFolders: CollectionFolder[];
  setCollectionFolders: (folders: CollectionFolder[]) => void;
  selectedCollectionId: number | null;
  setSelectedCollectionId: (folderId: number | null) => void;
  lastImportSummary: ImportSummary | null;
  setLastImportSummary: (summary: ImportSummary | null) => void;
  skippedLines: string[];
  setSkippedLines: (lines: string[]) => void;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [isConnected, setConnected] = useState(false);
  const [scannedAlbums, setScannedAlbums] = useState<Album[]>([]);
  const [scanHistory, setScanHistory] = useState<ScanHistoryEntry[]>(() => {
    try {
      const stored = localStorage.getItem(SCAN_HISTORY_STORAGE_KEY);
      const parsed = stored ? (JSON.parse(stored) as ScanHistoryEntry[]) : [];
      return pruneScanHistory(parsed);
    } catch {
      return [];
    }
  });
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [collectionFolders, setCollectionFolders] = useState<
    CollectionFolder[]
  >([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState<
    number | null
  >(null);
  const [lastImportSummary, setLastImportSummary] =
    useState<ImportSummary | null>(null);
  const [skippedLines, setSkippedLines] = useState<string[]>([]);

  useEffect(() => {
    try {
      localStorage.setItem(
        SCAN_HISTORY_STORAGE_KEY,
        JSON.stringify(scanHistory),
      );
    } catch {
      // localStorage may be unavailable (private browsing quota exceeded, etc.)
    }
  }, [scanHistory]);

  const addHistory = (entry: Omit<ScanHistoryEntry, "date">) => {
    setScanHistory((prev) => {
      const pruned = pruneScanHistory(prev);
      return [{ date: new Date().toISOString(), ...entry }, ...pruned];
    });
  };

  return (
    <AppContext.Provider
      value={{
        isConnected,
        setConnected,
        scannedAlbums,
        setScannedAlbums,
        scanHistory,
        addHistory,
        capturedImage,
        setCapturedImage,
        collectionFolders,
        setCollectionFolders,
        selectedCollectionId,
        setSelectedCollectionId,
        lastImportSummary,
        setLastImportSummary,
        skippedLines,
        setSkippedLines,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useAppContext must be used within AppProvider");
  return ctx;
}
