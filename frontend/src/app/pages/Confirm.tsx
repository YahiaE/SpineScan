import { useNavigate } from "react-router";
import { useAppContext } from "../store";
import { Disc3, Check, ArrowLeft } from "lucide-react";

export function Confirm() {
  const navigate = useNavigate();
  const { scannedAlbums } = useAppContext();

  return (
    <div className="flex flex-col h-full bg-neutral-950 p-6 overflow-y-auto">
      <div className="flex-1 flex flex-col items-center justify-center text-center py-8">
        <div className="w-20 h-20 bg-emerald-500/10 rounded-full flex items-center justify-center mb-6 border border-emerald-500/20">
          <Disc3 className="w-10 h-10 text-emerald-500" />
        </div>
        <h1 className="text-3xl font-bold text-white mb-4">Ready to Import?</h1>
        <p className="text-neutral-400 text-lg max-w-xs">
          Import {scannedAlbums.length} albums to your Discogs collection?
        </p>

        <div className="mt-8 w-full max-w-xs bg-neutral-900 rounded-xl border border-neutral-800 p-4">
          <p className="text-sm text-neutral-500 text-left mb-2 uppercase tracking-wider font-semibold">Preview</p>
          <div className="space-y-2 text-left">
            {scannedAlbums.slice(0, 3).map(a => {
              if (!a) return null;
              return <p key={a.id} className="text-white text-sm truncate">{a.artist} — {a.title}</p>;
            })}
            {scannedAlbums.length > 3 && (
              <p className="text-neutral-500 text-sm italic">...and {scannedAlbums.length - 3} more</p>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-3 mt-auto shrink-0 pb-4">
        <button
          onClick={() => navigate("/importing")}
          className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors"
        >
          <Check className="w-5 h-5" /> Confirm Import
        </button>
        <button
          onClick={() => navigate("/review")}
          className="w-full bg-transparent hover:bg-neutral-900 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 border border-neutral-800 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" /> Go back and edit
        </button>
      </div>
    </div>
  );
}
