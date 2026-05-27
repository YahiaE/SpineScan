import { useNavigate } from "react-router";
import { ScanLine, History, ChevronRight } from "lucide-react";
import { useAppContext } from "../store";
import { formatDistanceToNow } from "date-fns";

export function Home() {
  const navigate = useNavigate();
  const { scanHistory } = useAppContext();
  const recentHistory = scanHistory.slice(0, 5).map((scan, index) => ({
    key: `${scan.date}-${index}`,
    count: scan.count,
    failedCount: scan.failedCount,
    folderName: scan.folderName,
    date: scan.date,
  }));

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
        <div className="flex items-center justify-between gap-2 text-neutral-300 mb-4">
          <div className="flex items-center gap-2">
            <History className="w-5 h-5" />
            <h2 className="font-medium">Recent Scans</h2>
          </div>
          {recentHistory.length > 0 && (
            <button
              onClick={() => navigate("/history")}
              className="text-sm text-emerald-400 hover:text-emerald-300 transition-colors"
            >
              View all
            </button>
          )}
        </div>

        {recentHistory.length === 0 ? (
          <div className="text-center p-8 border border-neutral-800 border-dashed rounded-2xl">
            <p className="text-neutral-500">No previous scans.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {recentHistory.map((scan) => (
              <button
                key={scan.key}
                onClick={() => navigate("/history")}
                className="w-full flex items-center justify-between p-4 bg-neutral-900 border border-neutral-800 rounded-xl hover:bg-neutral-800 transition-colors text-left"
              >
                <div>
                  <p className="text-white font-medium">
                    {scan.count} Albums Added
                  </p>
                  <div className="mt-1 space-y-1 text-sm text-neutral-500">
                    {scan.folderName && <p>Collection: {scan.folderName}</p>}
                    <p>
                      Imported{" "}
                      {formatDistanceToNow(new Date(scan.date), {
                        addSuffix: true,
                      })}
                    </p>
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-neutral-600" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
