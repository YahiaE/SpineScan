import { useEffect } from "react";
import { useNavigate } from "react-router";
import { ScanSearch } from "lucide-react";
import { motion } from "motion/react";
import { useAppContext } from "../store";

const MOCK_ALBUMS = [
  { id: "1", artist: "Radiohead", title: "OK Computer" },
  { id: "2", artist: "Miles Davis", title: "Kind of Blue" },
  { id: "3", artist: "Daft Punk", title: "Discovery" },
  { id: "4", artist: "Pink Floyd", title: "The Dark Side of the Moon" },
];

export function Processing() {
  const navigate = useNavigate();
  const { setScannedAlbums } = useAppContext();

  useEffect(() => {
    // Simulate OCR delay
    const timer = setTimeout(() => {
      setScannedAlbums(MOCK_ALBUMS);
      navigate("/review");
    }, 3000);
    return () => clearTimeout(timer);
  }, [navigate, setScannedAlbums]);

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center bg-neutral-950 overflow-y-auto">
      <div className="relative mb-8">
        <motion.div
          animate={{
            scale: [1, 1.2, 1],
            opacity: [0.5, 1, 0.5],
          }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          className="absolute inset-0 bg-emerald-500/20 rounded-full blur-xl"
        />
        <div className="bg-neutral-900 p-6 rounded-full border border-neutral-800 relative z-10">
          <ScanSearch className="w-12 h-12 text-emerald-500" />
        </div>
      </div>
      
      <h2 className="text-2xl font-bold text-white mb-2">Analyzing CD spines...</h2>
      <p className="text-neutral-400">Extracting text and matching with Discogs database.</p>

      {/* Progress bar mock */}
      <div className="w-full max-w-xs h-2 bg-neutral-800 rounded-full mt-10 overflow-hidden relative">
        <motion.div
          initial={{ width: "0%" }}
          animate={{ width: "100%" }}
          transition={{ duration: 3, ease: "linear" }}
          className="absolute top-0 left-0 bottom-0 bg-emerald-500 rounded-full"
        />
      </div>
    </div>
  );
}
