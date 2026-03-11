import { useState } from "react";
import { useNavigate } from "react-router";
import { Camera, X, Check } from "lucide-react";

export function Scan() {
  const navigate = useNavigate();
  const [taken, setTaken] = useState(false);
  
  // Simulate a viewfinder
  return (
    <div className="flex flex-col h-full bg-black relative">
      {!taken ? (
        <div className="flex-1 relative flex flex-col items-center justify-end pb-12 overflow-hidden">
          {/* Mock Camera Viewfinder */}
          <div className="absolute inset-0 bg-neutral-900 overflow-hidden">
             <div className="absolute inset-0 opacity-20 bg-[url('https://images.unsplash.com/photo-1542382025-a13180ccbfeb?q=80&w=800&auto=format&fit=crop')] bg-cover bg-center mix-blend-overlay" />
          </div>

          {/* Viewfinder brackets */}
          <div className="absolute inset-8 border-2 border-emerald-500/50 rounded-lg pointer-events-none">
            <div className="absolute top-0 left-0 w-8 h-8 border-t-4 border-l-4 border-emerald-400 -m-[2px] rounded-tl-lg" />
            <div className="absolute top-0 right-0 w-8 h-8 border-t-4 border-r-4 border-emerald-400 -m-[2px] rounded-tr-lg" />
            <div className="absolute bottom-0 left-0 w-8 h-8 border-b-4 border-l-4 border-emerald-400 -m-[2px] rounded-bl-lg" />
            <div className="absolute bottom-0 right-0 w-8 h-8 border-b-4 border-r-4 border-emerald-400 -m-[2px] rounded-br-lg" />
          </div>
          
          <div className="text-center z-10 mb-8 bg-black/60 px-6 py-2 rounded-full backdrop-blur-sm">
            <p className="text-white text-sm font-medium">Line up your CD spines and take a photo.</p>
          </div>

          <button
            onClick={() => setTaken(true)}
            className="w-20 h-20 rounded-full border-4 border-white flex items-center justify-center p-1 bg-transparent z-10 active:scale-95 transition-transform"
          >
            <div className="w-full h-full bg-white rounded-full" />
          </button>
        </div>
      ) : (
        <div className="flex-1 relative flex flex-col bg-neutral-950">
          <div className="flex-1 m-4 border border-neutral-700 rounded-xl bg-neutral-800 flex items-center justify-center overflow-hidden relative">
             <div className="absolute inset-0 opacity-40 bg-[url('https://images.unsplash.com/photo-1542382025-a13180ccbfeb?q=80&w=800&auto=format&fit=crop')] bg-cover bg-center mix-blend-overlay" />
             <div className="absolute inset-0 bg-emerald-500/10" />
             <Camera className="w-12 h-12 text-emerald-400/50 z-10 drop-shadow-lg" />
          </div>
          
          <div className="p-6 flex gap-4 bg-neutral-950 border-t border-neutral-900">
            <button
              onClick={() => setTaken(false)}
              className="flex-1 bg-neutral-800 hover:bg-neutral-700 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors"
            >
              <X className="w-5 h-5" /> Retake
            </button>
            <button
              onClick={() => navigate("/processing")}
              className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors"
            >
              <Check className="w-5 h-5" /> Use Photo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
