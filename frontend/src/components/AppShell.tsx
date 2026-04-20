import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { useAuth } from "../features/auth/AuthProvider";

export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return (
    <div className="flex min-h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <Link to="/" className="text-sm font-semibold text-slate-900">Country Risk Model</Link>
        <div className="flex items-center gap-3 text-sm">
          <nav className="flex gap-3">
            <Link to="/countries" className="text-slate-700 hover:underline">Countries</Link>
            <Link to="/admin/models" className="text-slate-700 hover:underline">Models</Link>
          </nav>
          {user && (
            <button
              onClick={() => supabase.auth.signOut()}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
            >
              Sign out
            </button>
          )}
        </div>
      </header>
      <main className="flex-1 bg-slate-50 p-6">{children}</main>
    </div>
  );
}
