import { useNavigate } from "react-router";
import { Disc3, CheckCircle2 } from "lucide-react";
import { useAppContext } from "../store";
import { motion } from "motion/react";
import { useState } from "react";

export function Welcome() {
  const navigate = useNavigate();
  const { setConnected } = useAppContext();
  const [loading, setLoading] = useState(false);

  const handleConnect = () => {
    setLoading(true);
    setTimeout(() => {
      setConnected(true);
      navigate("/home");
    }, 1500);
  };

  return (
    <div className="flex flex-col items-center justify-center p-8 h-full text-center space-y-8 overflow-y-auto">
      <motion.div 
        animate={{ rotate: 360 }} 
        transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
        className="w-32 h-32 rounded-full border-4 border-neutral-800 flex items-center justify-center bg-neutral-900"
      >
        <Disc3 className="w-16 h-16 text-emerald-500" />
      </motion.div>
      
      <div className="space-y-3">
        <h1 className="text-3xl font-bold text-white">Welcome</h1>
        <p className="text-neutral-400 text-lg">
          Scan your CD spines and add them directly to your Discogs collection.
        </p>
      </div>

      <button
        onClick={handleConnect}
        disabled={loading}
        className="w-full max-w-xs bg-emerald-600 hover:bg-emerald-500 text-white font-medium py-4 px-6 rounded-2xl transition-all active:scale-95 flex items-center justify-center gap-2 disabled:opacity-70 mt-8"
      >
        {loading ? (
          <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
            <Disc3 className="w-5 h-5" />
          </motion.div>
        ) : (
          <>
            <CheckCircle2 className="w-5 h-5" />
            Connect Discogs Account
          </>
        )}
      </button>
    </div>
  );
}
