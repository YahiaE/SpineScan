import { createContext, useContext, useState, ReactNode } from "react";

export interface Album {
  id: string;
  artist: string;
  title: string;
}

interface AppState {
  isConnected: boolean;
  setConnected: (val: boolean) => void;
  scannedAlbums: Album[];
  setScannedAlbums: (albums: Album[]) => void;
  scanHistory: { date: string; count: number }[];
  addHistory: (count: number) => void;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [isConnected, setConnected] = useState(false);
  const [scannedAlbums, setScannedAlbums] = useState<Album[]>([]);
  const [scanHistory, setScanHistory] = useState<{ date: string; count: number }[]>([]);

  const addHistory = (count: number) => {
    setScanHistory(prev => [{ date: new Date().toISOString(), count }, ...prev]);
  };

  return (
    <AppContext.Provider value={{
      isConnected, setConnected,
      scannedAlbums, setScannedAlbums,
      scanHistory, addHistory
    }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useAppContext must be used within AppProvider");
  return ctx;
}
