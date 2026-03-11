import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useAppContext } from "../store";
import { CheckCircle2, Disc3 } from "lucide-react";
import { motion } from "motion/react";

export function Importing() {
  const navigate = useNavigate();
  const { scannedAlbums, addHistory } = useAppContext();
  const [completed, setCompleted] = useState<string[]>([]);
  
  useEffect(() => {
    if (scannedAlbums.length === 0) return;
    
    let index = 0;
    const interval = setInterval(() => {
      if (index < scannedAlbums.length) {
        setCompleted(prev => {
          const album = scannedAlbums[index];
          return album ? [...prev, album.id] : prev;
        });
        index++;
      } else {
        clearInterval(interval);
        setTimeout(() => {
          addHistory(scannedAlbums.length);
          navigate("/success");
        }, 1000);
      }
    }, 800);

    return () => clearInterval(interval);
  }, [scannedAlbums, navigate, addHistory]);

  const progress = scannedAlbums.length > 0 ? (completed.length / scannedAlbums.length) * 100 : 0;

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
        <h1 className="text-2xl font-bold text-white">Adding to collection...</h1>
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
        {scannedAlbums.map(album => {
          if (!album) return null;
          const isDone = completed.includes(album.id);
          return (
            <motion.div 
              key={album.id}
              initial={{ opacity: 0.3 }}
              animate={{ opacity: isDone ? 1 : 0.3, x: isDone ? 0 : -5 }}
              className="flex items-center gap-3 p-3 bg-neutral-900/50 rounded-xl border border-neutral-800/50"
            >
              <div className="w-6 flex justify-center shrink-0">
                {isDone ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                ) : (
                  <div className="w-2 h-2 rounded-full bg-neutral-600" />
                )}
              </div>
              <p className={`text-sm font-medium ${isDone ? "text-white" : "text-neutral-500"} truncate`}>
                {album.artist} — {album.title}
              </p>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
