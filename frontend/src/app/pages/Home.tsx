import { useNavigate } from "react-router";
import { ScanLine, History, ChevronRight } from "lucide-react";
import { useAppContext } from "../store";
import { formatDistanceToNow } from "date-fns";

export function Home() {
  const navigate = useNavigate();
  const { scanHistory } = useAppContext();

  return (
    <div className="flex flex-col h-full p-6 space-y-8 overflow-y-auto">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold text-white">Your Collection</h1>
        <p className="text-neutral-400">Ready to digitize more CDs?</p>
      </div>

      <button
        onClick={() => navigate("/scan")}
        className="w-full bg-emerald-600 hover:bg-emerald-500 text-white rounded-3xl p-8 flex flex-col items-center justify-center gap-4 transition-all active:scale-95 shadow-lg shadow-emerald-900/20"
      >
        <div className="bg-white/20 p-4 rounded-full">
          <ScanLine className="w-10 h-10" />
        </div>
        <span className="text-xl font-semibold">Scan CDs</span>
      </button>

      <div className="flex-1 pb-6">
        <div className="flex items-center gap-2 text-neutral-300 mb-4">
          <History className="w-5 h-5" />
          <h2 className="font-medium">Recent Scans</h2>
        </div>

        {scanHistory.length === 0 ? (
          <div className="text-center p-8 border border-neutral-800 border-dashed rounded-2xl">
            <p className="text-neutral-500">No previous scans.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {scanHistory.map((scan, i) => (
              <div key={i} className="flex items-center justify-between p-4 bg-neutral-900 border border-neutral-800 rounded-xl hover:bg-neutral-800 transition-colors cursor-pointer">
                <div>
                  <p className="text-white font-medium">{scan.count} Albums Added</p>
                  <p className="text-sm text-neutral-500">{formatDistanceToNow(new Date(scan.date), { addSuffix: true })}</p>
                </div>
                <ChevronRight className="w-5 h-5 text-neutral-600" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
