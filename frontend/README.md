
  # Album Metadata Storage App

  This is a code bundle for Album Metadata Storage App. The original project is available at https://www.figma.com/design/id8JowP8GhztodyQKL7znZ/Album-Metadata-Storage-App.

  ## Running the code

  Run `npm i` to install the dependencies.

  Run `npm run dev` to start the development server.

  ## Backend target

  By default, the app calls relative `/api/...` endpoints (useful with local Vite proxy).

  To point the frontend directly to a deployed backend, set:

  ```env
  VITE_API_BASE_URL=https://ye-spinescan-api.fly.dev
  ```

  The client rewrites `/api/foo` to `https://ye-spinescan-api.fly.dev/foo` when this variable is set.
  