import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import {
  X,
  Check,
  Camera,
  CameraOff,
  ImagePlus,
  Zap,
  ZapOff,
} from "lucide-react";
import { useAppContext } from "../store";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";
const MAX_PHOTO_DIMENSION = 2000;

async function normalizePhotoFile(file: File): Promise<Blob> {
  let image: CanvasImageSource;
  let width: number;
  let height: number;
  let releaseImage = () => {};

  try {
    const bitmap = await createImageBitmap(file);
    image = bitmap;
    width = bitmap.width;
    height = bitmap.height;
    releaseImage = () => bitmap.close();
  } catch {
    const imageUrl = URL.createObjectURL(file);
    const element = new Image();
    try {
      await new Promise<void>((resolve, reject) => {
        element.onload = () => resolve();
        element.onerror = () => reject(new Error("Could not read this photo."));
        element.src = imageUrl;
      });
    } catch (error) {
      URL.revokeObjectURL(imageUrl);
      throw error;
    }
    image = element;
    width = element.naturalWidth;
    height = element.naturalHeight;
    releaseImage = () => URL.revokeObjectURL(imageUrl);
  }

  if (!width || !height) {
    releaseImage();
    throw new Error("Could not read this photo.");
  }

  const scale = Math.min(1, MAX_PHOTO_DIMENSION / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  if (!context) {
    releaseImage();
    throw new Error("Could not prepare this photo.");
  }
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  releaseImage();

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) =>
        blob ? resolve(blob) : reject(new Error("Could not prepare this photo.")),
      "image/jpeg",
      0.88,
    );
  });
}

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
  const nativeCameraInputRef = useRef<HTMLInputElement>(null);
  const photoLibraryInputRef = useRef<HTMLInputElement>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [torchSupported, setTorchSupported] = useState(false);
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [preparingPhoto, setPreparingPhoto] = useState(false);
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

  const disableTorch = async () => {
    const track = streamRef.current?.getVideoTracks?.()[0] as
      | TorchCapableTrack
      | undefined;

    if (!torchEnabled || !track?.applyConstraints || !supportsTorch(track)) {
      return;
    }

    try {
      await track.applyConstraints({
        advanced: [{ torch: false } as MediaTrackConstraintSet],
      });
    } catch {
      // Best-effort only; stopping the track still tears down the camera.
    } finally {
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

  const stopCamera = async () => {
    await disableTorch();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setTorchSupported(false);
    setTorchEnabled(false);
  };

  useEffect(() => {
    startCamera();
    return () => {
      void stopCamera();
    };
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

  const handleCapture = async () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    setCaptureError(null);

    await disableTorch();

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
          void stopCamera();
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
            void stopCamera();
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

  const handlePhotoSelection = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;

    setPreparingPhoto(true);
    setCameraError(null);
    setCaptureError(null);
    setUploadError(null);
    try {
      const blob = await normalizePhotoFile(file);
      await stopCamera();
      setPreview(URL.createObjectURL(blob));
      setPreviewBlob(blob);
    } catch (e) {
      setCaptureError(
        e instanceof Error
          ? e.message
          : "Could not read this photo. Try a JPEG or PNG image.",
      );
    } finally {
      setPreparingPhoto(false);
    }
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

  const photoInputs = (
    <>
      <input
        ref={nativeCameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(event) => void handlePhotoSelection(event)}
      />
      <input
        ref={photoLibraryInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => void handlePhotoSelection(event)}
      />
    </>
  );

  if (cameraError) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 gap-4 text-center bg-black">
        {photoInputs}
        <CameraOff className="w-12 h-12 text-red-400" />
        <p className="text-white font-medium">{cameraError}</p>
        <button
          onClick={startCamera}
          className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-xl transition-colors"
        >
          Try again
        </button>
        <button
          onClick={() => nativeCameraInputRef.current?.click()}
          disabled={preparingPhoto}
          className="flex items-center gap-2 rounded-xl border border-neutral-700 px-5 py-3 text-white transition-colors hover:bg-neutral-900 disabled:opacity-60"
          type="button"
        >
          <Camera className="h-4 w-4" />
          Use phone camera
        </button>
        <button
          onClick={() => photoLibraryInputRef.current?.click()}
          disabled={preparingPhoto}
          className="flex items-center gap-2 rounded-xl border border-neutral-700 px-5 py-3 text-white transition-colors hover:bg-neutral-900 disabled:opacity-60"
          type="button"
        >
          <ImagePlus className="h-4 w-4" />
          {preparingPhoto ? "Preparing photo..." : "Choose a photo"}
        </button>
        {captureError && <p className="text-red-400 text-sm">{captureError}</p>}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0 bg-black relative overflow-hidden">
      {photoInputs}
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

          <button
            onClick={handleTorchToggle}
            disabled={!torchSupported}
            className="absolute top-4 right-4 z-10 flex items-center gap-2 rounded-full bg-black/60 px-3 py-2 text-xs font-medium text-white backdrop-blur-sm transition-colors hover:bg-black/75 disabled:opacity-60 disabled:hover:bg-black/60"
            type="button"
            title={
              torchSupported
                ? "Toggle camera flash"
                : "Flash is not supported in this browser"
            }
          >
            {torchSupported ? (
              torchEnabled ? (
                <>
                  <Zap className="h-4 w-4" />
                  <span>Flash On</span>
                </>
              ) : (
                <>
                  <ZapOff className="h-4 w-4" />
                  <span>Flash Off</span>
                </>
              )
            ) : (
              <>
                <ZapOff className="h-4 w-4" />
                <span>Flash Unavailable</span>
              </>
            )}
          </button>

          <div className="absolute top-16 left-0 right-0 z-10 flex justify-center gap-2 px-3">
            <button
              onClick={() => nativeCameraInputRef.current?.click()}
              disabled={preparingPhoto}
              className="flex items-center gap-2 rounded-full bg-black/60 px-3 py-2 text-xs font-medium text-white backdrop-blur-sm transition-colors hover:bg-black/75 disabled:opacity-60"
              type="button"
            >
              <Camera className="h-4 w-4" />
              Phone camera
            </button>
            <button
              onClick={() => photoLibraryInputRef.current?.click()}
              disabled={preparingPhoto}
              className="flex items-center gap-2 rounded-full bg-black/60 px-3 py-2 text-xs font-medium text-white backdrop-blur-sm transition-colors hover:bg-black/75 disabled:opacity-60"
              type="button"
            >
              <ImagePlus className="h-4 w-4" />
              {preparingPhoto ? "Preparing..." : "Choose photo"}
            </button>
          </div>

          {/* Viewfinder brackets */}
          <div
            className="absolute border-2 border-emerald-500/50 rounded-lg pointer-events-none"
            style={{
              top: "1.5rem",
              left: "1.5rem",
              right: "1.5rem",
              bottom: "calc(0.75rem + env(safe-area-inset-bottom, 0px))",
            }}
          >
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
              marginBottom: "0.25rem",
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
