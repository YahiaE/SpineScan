import { useNavigate } from "react-router";
import { CheckCircle2, ScanLine, List } from "lucide-react";
import { motion } from "motion/react";
import { useAppContext } from "../store";

export function Success() {
  const navigate = useNavigate();
  const {
    setScannedAlbums,
    collectionFolders,
    selectedCollectionId,
    setSelectedCollectionId,
    lastImportSummary,
    setLastImportSummary,
  } = useAppContext();

  const selectedFolder = collectionFolders.find(
    (folder) => folder.id === selectedCollectionId,
  );

  const handleScanMore = () => {
    setScannedAlbums([]);
    setLastImportSummary(null);
    navigate("/scan");
  };

  const handleHome = () => {
    setScannedAlbums([]);
    setSelectedCollectionId(null);
    setLastImportSummary(null);
    navigate("/home");
  };

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center bg-neutral-950 overflow-y-auto">
      <motion.div
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", bounce: 0.5, duration: 0.8 }}
        className="w-24 h-24 bg-emerald-500/20 rounded-full flex items-center justify-center mb-8 border-4 border-emerald-500/30"
      >
        <CheckCircle2 className="w-12 h-12 text-emerald-500" />
      </motion.div>

      <h1 className="text-3xl font-bold text-white mb-3">Success!</h1>
      <p className="text-neutral-400 text-lg mb-12 max-w-xs">
        Added {lastImportSummary?.addedCount ?? 0} albums to{" "}
        {selectedFolder?.name ?? "your Discogs collection"}.
      </p>
      {(lastImportSummary?.skippedCount ?? 0) > 0 && (
        <p className="text-amber-300 text-sm mb-8 max-w-xs">
          Skipped {lastImportSummary?.skippedCount ?? 0} duplicate
          {(lastImportSummary?.skippedCount ?? 0) === 1 ? " entry" : " entries"}
          .
        </p>
      )}

      <div className="w-full space-y-4">
        <button
          onClick={handleScanMore}
          className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors"
        >
          <ScanLine className="w-5 h-5" /> Scan more CDs
        </button>
        <button
          onClick={handleHome}
          className="w-full bg-transparent border border-neutral-800 hover:bg-neutral-900 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors"
        >
          <List className="w-5 h-5" /> Back to Home
        </button>
      </div>
    </div>
  );
}
