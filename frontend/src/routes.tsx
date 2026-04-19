import { createBrowserRouter, Navigate } from "react-router-dom";
import { LoginPage } from "./features/auth/LoginPage";
import { RequireAuth } from "./features/auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { CountryListPage } from "./features/countries/CountryListPage";

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
]);
