import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { X, Check, CameraOff, Zap, ZapOff } from "lucide-react";
import { useAppContext } from "../store";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";

type TorchCapableTrack = MediaStreamTrack & {
  applyConstraints?: (constraints: MediaTrackConstraints) => Promise<void>;
};

function supportsTorch(track: TorchCapableTrack | undefined): boolean {
  const capabilities = track?.getCapabilities?.() as
    | { torch?: boolean }
    | undefined;
  return Boolean(capabilities?.torch);
}

export function Scan() {
  const navigate = useNavigate();
  const { setCapturedImage } = useAppContext();

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [torchSupported, setTorchSupported] = useState(false);
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const syncTorchAvailability = (stream: MediaStream | null) => {
    const track = stream?.getVideoTracks?.()[0] as
      | TorchCapableTrack
      | undefined;
    const torchAvailable = supportsTorch(track);
    setTorchSupported(torchAvailable);
    if (!torchAvailable) {
      setTorchEnabled(false);
    }
  };

  const startCamera = async () => {
    setCameraError(null);
    setCaptureError(null);
    setCameraReady(false);
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
      syncTorchAvailability(stream);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
    } catch {
      setCameraError("Camera access denied or unavailable.");
    }
  };

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setTorchSupported(false);
    setTorchEnabled(false);
  };

  useEffect(() => {
    startCamera();
    return stopCamera;
  }, []);

  const handleTorchToggle = async () => {
    const track = streamRef.current?.getVideoTracks?.()[0] as
      | TorchCapableTrack
      | undefined;

    if (!track?.applyConstraints || !supportsTorch(track)) {
      setTorchSupported(false);
      setTorchEnabled(false);
      return;
    }

    const nextTorchState = !torchEnabled;

    try {
      await track.applyConstraints({
        advanced: [{ torch: nextTorchState } as MediaTrackConstraintSet],
      });
      setTorchEnabled(nextTorchState);
      setCaptureError(null);
    } catch {
      setCaptureError("Flash is not available on this camera.");
      setTorchEnabled(false);
    }
  };

  const handleCapture = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    setCaptureError(null);

    const width = video.videoWidth || video.clientWidth;
    const height = video.videoHeight || video.clientHeight;

    if (!width || !height) {
      setCaptureError(
        "Camera is still initializing. Please wait a moment and try again.",
      );
      return;
    }

    canvas.width = width;
    canvas.height = height;
    canvas.getContext("2d")!.drawImage(video, 0, 0);

    canvas.toBlob(
      (blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob);
          stopCamera();
          setPreview(url);
          setPreviewBlob(blob);
          return;
        }

        // Safari can occasionally return null from toBlob; fallback to dataURL conversion.
        const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
        fetch(dataUrl)
          .then((res) => res.blob())
          .then((fallbackBlob) => {
            const url = URL.createObjectURL(fallbackBlob);
            stopCamera();
            setPreview(url);
            setPreviewBlob(fallbackBlob);
          })
          .catch(() => {
            setCaptureError("Could not capture photo. Please retake.");
          });
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
    setCaptureError(null);
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
        if (res.status === 401) {
          throw new Error(
            "Session expired. Please reconnect your Discogs account.",
          );
        }
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
    <div className="flex flex-col h-full min-h-0 bg-black relative overflow-hidden">
      {!preview ? (
        <div
          className="flex-1 min-h-0 relative flex flex-col items-center justify-end overflow-hidden"
          style={{
            paddingBottom: "calc(1.25rem + env(safe-area-inset-bottom, 0px))",
          }}
        >
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            onLoadedMetadata={() => setCameraReady(true)}
            onCanPlay={() => setCameraReady(true)}
            className="absolute inset-0 w-full h-full object-cover"
          />
          <canvas ref={canvasRef} className="hidden" />

          {torchSupported && (
            <button
              onClick={handleTorchToggle}
              className="absolute top-4 right-4 z-10 flex items-center gap-2 rounded-full bg-black/60 px-3 py-2 text-xs font-medium text-white backdrop-blur-sm transition-colors hover:bg-black/75"
              type="button"
            >
              {torchEnabled ? (
                <>
                  <ZapOff className="h-4 w-4" />
                  <span>Flash Off</span>
                </>
              ) : (
                <>
                  <Zap className="h-4 w-4" />
                  <span>Flash On</span>
                </>
              )}
            </button>
          )}

          {/* Viewfinder brackets */}
          <div className="absolute inset-8 border-2 border-emerald-500/50 rounded-lg pointer-events-none">
            <div className="absolute top-0 left-0 w-8 h-8 border-t-4 border-l-4 border-emerald-400 -m-[2px] rounded-tl-lg" />
            <div className="absolute top-0 right-0 w-8 h-8 border-t-4 border-r-4 border-emerald-400 -m-[2px] rounded-tr-lg" />
            <div className="absolute bottom-0 left-0 w-8 h-8 border-b-4 border-l-4 border-emerald-400 -m-[2px] rounded-bl-lg" />
            <div className="absolute bottom-0 right-0 w-8 h-8 border-b-4 border-r-4 border-emerald-400 -m-[2px] rounded-br-lg" />
          </div>

          <div className="text-center z-10 mb-4 bg-black/60 px-4 py-2 rounded-full backdrop-blur-sm max-w-[85%]">
            <p className="text-white text-xs sm:text-sm font-medium leading-tight">
              Line up your CD spines and take a photo.
            </p>
          </div>

          <button
            onClick={handleCapture}
            disabled={!cameraReady}
            className="rounded-full border-4 border-white flex items-center justify-center p-1 bg-transparent z-10 active:scale-95 transition-transform disabled:opacity-60"
            style={{
              width: "clamp(4rem, 18vw, 5rem)",
              height: "clamp(4rem, 18vw, 5rem)",
            }}
          >
            <div className="w-full h-full bg-white rounded-full" />
          </button>

          {(captureError || uploadError) && (
            <p className="text-red-400 text-xs sm:text-sm text-center mt-3 z-10 bg-black/60 px-3 py-2 rounded-lg max-w-[88%] leading-snug">
              {captureError ?? uploadError}
            </p>
          )}
        </div>
      ) : (
        <div className="flex-1 min-h-0 relative flex flex-col bg-neutral-950 overflow-hidden">
          <div className="flex-1 min-h-0 m-3 border border-neutral-700 rounded-xl overflow-hidden">
            <img
              src={preview}
              alt="Captured photo"
              className="w-full h-full object-cover"
            />
          </div>

          <div
            className="shrink-0 px-3 pt-3 grid grid-cols-2 gap-3 bg-neutral-950 border-t border-neutral-900"
            style={{
              paddingBottom:
                "calc(0.875rem + env(safe-area-inset-bottom, 0px))",
            }}
          >
            <button
              onClick={handleRetake}
              className="min-w-0 bg-neutral-800 hover:bg-neutral-700 text-white py-3 rounded-xl font-medium text-sm sm:text-base flex items-center justify-center gap-2 transition-colors"
            >
              <X className="w-4 h-4 shrink-0" />
              <span className="truncate">Retake</span>
            </button>
            <button
              onClick={handleUsePhoto}
              disabled={uploading}
              className="min-w-0 bg-emerald-600 hover:bg-emerald-500 text-white py-3 rounded-xl font-medium text-sm sm:text-base flex items-center justify-center gap-2 transition-colors disabled:opacity-60"
            >
              <Check className="w-4 h-4 shrink-0" />
              <span className="truncate">
                {uploading ? "Uploading..." : "Use Photo"}
              </span>
            </button>
          </div>
          {uploadError && (
            <p className="text-red-400 text-xs sm:text-sm text-center px-3 pb-2 leading-snug shrink-0">
              {uploadError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
