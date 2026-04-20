import { createBrowserRouter, Navigate } from "react-router-dom";
import { LoginPage } from "./features/auth/LoginPage";
import { RequireAuth } from "./features/auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { CountryDetailPage } from "./features/countries/CountryDetailPage";
import { CountryListPage } from "./features/countries/CountryListPage";
import { ModelsListPage } from "./features/admin/ModelsListPage";
import { ModelDetailPage } from "./features/admin/ModelDetailPage";
import { TrainModelPage } from "./features/admin/TrainModelPage";

function LandingRedirect() {
  return <Navigate to="/countries" replace />;
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell>
          <LandingRedirect />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/countries",
    element: (
      <RequireAuth>
        <AppShell>
          <CountryListPage />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/countries/:iso3",
    element: (
      <RequireAuth>
        <AppShell>
          <CountryDetailPage />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/admin/models",
    element: (
      <RequireAuth>
        <AppShell>
          <ModelsListPage />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/admin/models/train",
    element: (
      <RequireAuth>
        <AppShell>
          <TrainModelPage />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/admin/models/:id",
    element: (
      <RequireAuth>
        <AppShell>
          <ModelDetailPage />
        </AppShell>
      </RequireAuth>
    ),
  },
]);
