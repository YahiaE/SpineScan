import * as Sentry from "@sentry/react";
import { createRoot } from "react-dom/client";

import App from "./app/App.tsx";
import "./styles/index.css";

const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
if (sentryDsn) {
  const tracesSampleRateRaw = Number(
    import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? "0.1",
  );
  const tracesSampleRate = Number.isFinite(tracesSampleRateRaw)
    ? tracesSampleRateRaw
    : 0.1;

  Sentry.init({
    dsn: sentryDsn,
    environment: import.meta.env.MODE,
    release: import.meta.env.VITE_RELEASE,
    tracesSampleRate,
    beforeSend(event) {
      if (event.request?.headers) {
        delete event.request.headers.Authorization;
      }
      return event;
    },
  });
}

createRoot(document.getElementById("root")!).render(
  <Sentry.ErrorBoundary fallback={<p>Unexpected error. Please refresh.</p>}>
    <App />
  </Sentry.ErrorBoundary>,
);
