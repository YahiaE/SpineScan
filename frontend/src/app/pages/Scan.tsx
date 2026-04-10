import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { X, Check, CameraOff } from "lucide-react";
import { useAppContext } from "../store";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";

export function Scan() {
  const navigate = useNavigate();
  const { setCapturedImage } = useAppContext();

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const startCamera = async () => {
    setCameraError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
    } catch {
      setCameraError("Camera access denied or unavailable.");
    }
  };

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };

  useEffect(() => {
    startCamera();
    return stopCamera;
  }, []);

  const handleCapture = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);

    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        stopCamera();
        setPreview(url);
        setPreviewBlob(blob);
      },
      "image/jpeg",
      0.92,
    );
  };

  const handleRetake = () => {
    if (preview) {
      URL.revokeObjectURL(preview);
      setPreview(null);
      setPreviewBlob(null);
    }
    setUploadError(null);
    startCamera();
  };

  const handleUsePhoto = async () => {
    if (!preview || !previewBlob) return;
    setUploading(true);
    setUploadError(null);

    try {
      const form = new FormData();
      form.append("file", previewBlob, "scan.jpg");

      const res = await apiFetch(`${API_BASE}/data/upload`, {
        method: "POST",

        body: form,
      });

      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.error ?? "Upload failed");
      }

      const { path } = await res.json();
      setCapturedImage(path);
      URL.revokeObjectURL(preview);
      navigate("/processing");
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  if (cameraError) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 gap-4 text-center bg-black">
        <CameraOff className="w-12 h-12 text-red-400" />
        <p className="text-white font-medium">{cameraError}</p>
        <button
          onClick={startCamera}
          className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-xl transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-black relative">
      {!preview ? (
        <div className="flex-1 relative flex flex-col items-center justify-end pb-12 overflow-hidden">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="absolute inset-0 w-full h-full object-cover"
          />
          <canvas ref={canvasRef} className="hidden" />

          {/* Viewfinder brackets */}
          <div className="absolute inset-8 border-2 border-emerald-500/50 rounded-lg pointer-events-none">
            <div className="absolute top-0 left-0 w-8 h-8 border-t-4 border-l-4 border-emerald-400 -m-[2px] rounded-tl-lg" />
            <div className="absolute top-0 right-0 w-8 h-8 border-t-4 border-r-4 border-emerald-400 -m-[2px] rounded-tr-lg" />
            <div className="absolute bottom-0 left-0 w-8 h-8 border-b-4 border-l-4 border-emerald-400 -m-[2px] rounded-bl-lg" />
            <div className="absolute bottom-0 right-0 w-8 h-8 border-b-4 border-r-4 border-emerald-400 -m-[2px] rounded-br-lg" />
          </div>

          <div className="text-center z-10 mb-8 bg-black/60 px-6 py-2 rounded-full backdrop-blur-sm">
            <p className="text-white text-sm font-medium">
              Line up your CD spines and take a photo.
            </p>
          </div>

          <button
            onClick={handleCapture}
            className="w-20 h-20 rounded-full border-4 border-white flex items-center justify-center p-1 bg-transparent z-10 active:scale-95 transition-transform"
          >
            <div className="w-full h-full bg-white rounded-full" />
          </button>
        </div>
      ) : (
        <div className="flex-1 relative flex flex-col bg-neutral-950">
          <div className="flex-1 m-4 border border-neutral-700 rounded-xl overflow-hidden">
            <img
              src={preview}
              alt="Captured photo"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="p-6 flex gap-4 bg-neutral-950 border-t border-neutral-900">
            <button
              onClick={handleRetake}
              className="flex-1 bg-neutral-800 hover:bg-neutral-700 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors"
            >
              <X className="w-5 h-5" /> Retake
            </button>
            <button
              onClick={handleUsePhoto}
              disabled={uploading}
              className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-4 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-60"
            >
              <Check className="w-5 h-5" />
              {uploading ? "Uploading..." : "Use Photo"}
            </button>
          </div>
          {uploadError && (
            <p className="text-red-400 text-sm text-center pb-2">
              {uploadError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
