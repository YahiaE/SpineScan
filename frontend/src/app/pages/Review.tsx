import { useState } from "react";
import { useNavigate } from "react-router";
import { useAppContext } from "../store";
import { Trash2, Edit2, Plus, ArrowRight } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export function Review() {
  const navigate = useNavigate();
  const { scannedAlbums, setScannedAlbums } = useAppContext();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editArtist, setEditArtist] = useState("");
  const [editTitle, setEditTitle] = useState("");

  const handleRemove = (id: string) => {
    setScannedAlbums(scannedAlbums.filter(a => a.id !== id));
  };

  const handleEdit = (id: string) => {
    const album = scannedAlbums.find(a => a.id === id);
    if (album) {
      setEditingId(id);
      setEditArtist(album.artist);
      setEditTitle(album.title);
    }
  };

  const saveEdit = () => {
    setScannedAlbums(scannedAlbums.map(a => 
      a.id === editingId ? { ...a, artist: editArtist, title: editTitle } : a
    ));
    setEditingId(null);
  };

  const addManual = () => {
    const newId = Math.random().toString(36).substring(2, 9);
    setScannedAlbums([...scannedAlbums, { id: newId, artist: "New Artist", title: "New Album" }]);
    handleEdit(newId);
  };

  return (
    <div className="flex flex-col h-full bg-neutral-950">
      <div className="p-6 pb-2">
        <h1 className="text-2xl font-bold text-white mb-1">Detected Albums</h1>
        <p className="text-neutral-400 text-sm">Review and correct any errors.</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        <AnimatePresence>
          {scannedAlbums.map(album => {
            if (!album) return null;
            return (
            <motion.div
              key={album.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, height: 0, marginBottom: 0 }}
              className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex items-center justify-between group overflow-hidden"
            >
              {editingId === album.id ? (
                <div className="flex-1 flex flex-col gap-2 mr-2">
                  <input 
                    value={editArtist} 
                    onChange={e => setEditArtist(e.target.value)}
                    className="bg-neutral-950 text-white px-3 py-2 rounded-lg border border-neutral-700 text-sm focus:outline-none focus:border-emerald-500"
                    placeholder="Artist"
                  />
                  <input 
                    value={editTitle} 
                    onChange={e => setEditTitle(e.target.value)}
                    className="bg-neutral-950 text-white px-3 py-2 rounded-lg border border-neutral-700 text-sm focus:outline-none focus:border-emerald-500"
                    placeholder="Title"
                  />
                  <button onClick={saveEdit} className="bg-emerald-600 hover:bg-emerald-500 transition-colors text-white py-2 rounded-lg text-sm mt-1 font-medium">Save</button>
                </div>
              ) : (
                <div className="flex-1 pr-4">
                  <p className="font-semibold text-white">{album.artist}</p>
                  <p className="text-neutral-400 text-sm">{album.title}</p>
                </div>
              )}
              
              {editingId !== album.id && (
                <div className="flex items-center gap-1">
                  <button onClick={() => handleEdit(album.id)} className="p-2 text-neutral-500 hover:text-white bg-neutral-800/50 hover:bg-neutral-700 rounded-lg transition-colors">
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button onClick={() => handleRemove(album.id)} className="p-2 text-red-400 hover:text-red-300 bg-red-400/10 hover:bg-red-400/20 rounded-lg transition-colors">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )}
            </motion.div>
            );
          })}
        </AnimatePresence>

        <button 
          onClick={addManual}
          className="w-full py-4 border-2 border-dashed border-neutral-800 rounded-xl text-neutral-400 font-medium flex items-center justify-center gap-2 hover:bg-neutral-900 hover:text-white hover:border-neutral-600 transition-colors mt-2"
        >
          <Plus className="w-4 h-4" /> Add Missing Album
        </button>
      </div>

      <div className="p-6 bg-neutral-950 border-t border-neutral-900 shrink-0">
        <button
          onClick={() => navigate("/confirm")}
          disabled={scannedAlbums.length === 0}
          className="w-full bg-emerald-600 hover:bg-emerald-500 transition-colors text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 disabled:opacity-50 disabled:hover:bg-emerald-600"
        >
          Import {scannedAlbums.length} Albums <ArrowRight className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
}
