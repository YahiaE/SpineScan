import { Outlet, useNavigate, useLocation } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { Disc, ChevronLeft } from "lucide-react";

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();

  const isHomeOrWelcome = location.pathname === "/" || location.pathname === "/home";

  return (
    <div className="min-h-screen bg-neutral-900 flex justify-center sm:py-8 sm:px-4 text-white">
      <div className="w-full max-w-md bg-neutral-950 sm:rounded-3xl sm:border sm:border-neutral-800 overflow-hidden relative shadow-2xl flex flex-col h-screen sm:h-[850px]">
        
        {/* Header */}
        <header className="h-14 flex items-center justify-between px-4 border-b border-neutral-800 shrink-0 z-10 bg-neutral-950/80 backdrop-blur-md">
          <div className="flex items-center gap-3">
            {!isHomeOrWelcome && (
              <button 
                onClick={() => navigate(-1)}
                className="p-1 -ml-1 text-neutral-400 hover:text-white transition-colors"
              >
                <ChevronLeft className="w-6 h-6" />
              </button>
            )}
            <div className="flex items-center gap-2">
              <Disc className="w-5 h-5 text-emerald-500" />
              <span className="font-semibold text-white tracking-wide">CD Scanner</span>
            </div>
          </div>
        </header>

        {/* Content Area with Animation */}
        <main className="flex-1 overflow-hidden relative bg-neutral-950">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className="absolute inset-0 flex flex-col"
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
