import { createBrowserRouter } from "react-router";
import { Layout } from "./components/ui/Layout";
import { Welcome } from "./pages/Welcome";
import { Home } from "./pages/Home";
import { HistoryPage } from "./pages/History";
import { Scan } from "./pages/Scan";
import { Processing } from "./pages/Processing";
import { Review } from "./pages/Review";
import { Confirm } from "./pages/Confirm";
import { Importing } from "./pages/Importing";
import { Success } from "./pages/Success";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: Welcome },
      { path: "home", Component: Home },
      { path: "history", Component: HistoryPage },
      { path: "scan", Component: Scan },
      { path: "processing", Component: Processing },
      { path: "review", Component: Review },
      { path: "confirm", Component: Confirm },
      { path: "importing", Component: Importing },
      { path: "success", Component: Success },
    ],
  },
]);
