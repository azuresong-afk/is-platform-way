import { AuthProvider, Loading, useAuth } from "@platform/ui";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ShellLayout } from "./components/ShellLayout";
import { AuditPage } from "./pages/admin/Audit";
import { EventsPage } from "./pages/admin/Events";
import { ProductsPage } from "./pages/admin/Products";
import { ProjectsPage } from "./pages/admin/Projects";
import { ServiceAccountsPage } from "./pages/admin/ServiceAccounts";
import { SigningKeysPage } from "./pages/admin/SigningKeys";
import { UsersPage } from "./pages/admin/Users";
import { HomePage } from "./pages/Home";
import { LoginPage } from "./pages/Login";
import { AdminOnly, NotFoundPage, NotificationsPage } from "./pages/Misc";

function Authed() {
  const auth = useAuth();
  if (!auth.ready) return <Loading text="Проверяем вход…" />;
  return (
    <ShellLayout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/admin/users" element={<AdminOnly><UsersPage /></AdminOnly>} />
        <Route path="/admin/projects" element={<AdminOnly><ProjectsPage /></AdminOnly>} />
        <Route path="/admin/products" element={<AdminOnly><ProductsPage /></AdminOnly>} />
        <Route path="/admin/events" element={<AdminOnly><EventsPage /></AdminOnly>} />
        <Route path="/admin/service-accounts" element={<AdminOnly><ServiceAccountsPage /></AdminOnly>} />
        <Route path="/admin/audit" element={<AdminOnly><AuditPage /></AdminOnly>} />
        <Route path="/admin/keys" element={<AdminOnly><SigningKeysPage /></AdminOnly>} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </ShellLayout>
  );
}

export function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="*"
          element={
            <AuthProvider>
              <Authed />
            </AuthProvider>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
