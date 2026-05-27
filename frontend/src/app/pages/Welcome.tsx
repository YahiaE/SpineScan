import { useEffect } from "react";
import { useNavigate } from "react-router";
import { Disc3, CheckCircle2, ExternalLink } from "lucide-react";
import { useAppContext } from "../store";
import { motion } from "motion/react";
import { useState } from "react";
import { apiFetch } from "../apiClient";

const API_BASE = "/api";
const EXCHANGE_RETRY_COUNT = 20;
const EXCHANGE_RETRY_BASE_DELAY_MS = 800;
const EXCHANGE_RETRY_MAX_DELAY_MS = 5000;

type AuthStep = "idle" | "requesting" | "authorizing" | "exchanging" | "error";

export function Welcome() {
  const navigate = useNavigate();
  const { setConnected } = useAppContext();
  const [step, setStep] = useState<AuthStep>("idle");
  const [error, setError] = useState<string | null>(null);
  const [authPopup, setAuthPopup] = useState<Window | null>(null);
  const [oauthToken, setOauthToken] = useState<string | null>(null);
  const [oauthVerifier, setOauthVerifier] = useState<string | null>(null);

  const handleConnect = async () => {
    setStep("requesting");
    setError(null);

    try {
      const res = await apiFetch(`${API_BASE}/auth/request_token`, {});
      if (!res.ok) throw new Error("Failed to get request token");
      const { authorize_url, oauth_token } = await res.json();

      if (!oauth_token)
        throw new Error("OAuth token missing from server response");
      setOauthToken(oauth_token);

      const popup = window.open(
        authorize_url,
        "discogs_auth",
        "width=600,height=700",
      );
      setAuthPopup(popup);
      setStep("authorizing");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setStep("error");
    }
  };

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type !== "discogs_oauth_complete") return;

      const token =
        typeof event.data?.oauth_token === "string"
          ? event.data.oauth_token
          : null;
      const verifier =
        typeof event.data?.oauth_verifier === "string"
          ? event.data.oauth_verifier
          : null;

      if (token) setOauthToken(token);
      if (verifier) setOauthVerifier(verifier);
      void handleAuthorized(token ?? undefined, verifier ?? undefined);
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const handleAuthorized = async (
    tokenOverride?: string,
    verifierOverride?: string,
  ) => {
    authPopup?.close();

    const token = tokenOverride ?? oauthToken;
    const verifier = verifierOverride ?? oauthVerifier;

    if (!token) {
      setError("Missing OAuth token. Please reconnect and try again.");
      setStep("error");
      return;
    }

    setStep("exchanging");
    setError(null);

    try {
      let res: Response | null = null;
      let payload: { error?: string } | null = null;

      for (let attempt = 0; attempt < EXCHANGE_RETRY_COUNT; attempt += 1) {
        const query = new URLSearchParams({ oauth_token: token });
        if (verifier) query.set("oauth_verifier", verifier);

        res = await apiFetch(
          `${API_BASE}/auth/access_token?${query.toString()}`,
          {},
        );

        if (res.ok) break;

        payload = await res.json().catch(() => null);
        if (res.status !== 409) break;

        const delay = Math.min(
          EXCHANGE_RETRY_BASE_DELAY_MS * 2 ** attempt,
          EXCHANGE_RETRY_MAX_DELAY_MS,
        );
        await new Promise((resolve) => setTimeout(resolve, delay));
      }

      if (!res) {
        throw new Error("No response from authorization server");
      }

      if (!res.ok) {
        const msg = payload?.error ?? "Authorization failed - please try again";
        throw new Error(msg);
      }

      await res.json();
      setConnected(true);
      navigate("/home");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setStep("error");
    }
  };

  const isLoading = step === "requesting" || step === "exchanging";

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

      {step === "authorizing" ? (
        <div className="w-full max-w-xs space-y-3">
          <p className="text-neutral-400 text-sm">
            Authorize SpineScan in the Discogs window, then click below.
          </p>
          <button
            onClick={handleAuthorized}
            className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-medium py-4 px-6 rounded-2xl transition-all active:scale-95 flex items-center justify-center gap-2"
          >
            <CheckCircle2 className="w-5 h-5" />
            I've Authorized
          </button>
          <button
            onClick={() => {
              authPopup?.focus();
            }}
            className="w-full text-neutral-400 hover:text-white text-sm flex items-center justify-center gap-1 transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
            Re-open authorization window
          </button>
        </div>
      ) : (
        <button
          onClick={handleConnect}
          disabled={isLoading}
          className="w-full max-w-xs bg-emerald-600 hover:bg-emerald-500 text-white font-medium py-4 px-6 rounded-2xl transition-all active:scale-95 flex items-center justify-center gap-2 disabled:opacity-70 mt-8"
        >
          {isLoading ? (
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
            >
              <Disc3 className="w-5 h-5" />
            </motion.div>
          ) : (
            <>
              <CheckCircle2 className="w-5 h-5" />
              Connect Discogs Account
            </>
          )}
        </button>
      )}

      {error && <p className="text-red-400 text-sm max-w-xs">{error}</p>}
    </div>
  );
}
