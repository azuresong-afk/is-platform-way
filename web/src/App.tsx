import { AuthProvider, Loading, useAuth } from "@platform/ui";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ShellLayout } from "./components/ShellLayout";
import { AssetsPage } from "./pages/admin/Assets";
import { AuditPage } from "./pages/admin/Audit";
import { EventsPage } from "./pages/admin/Events";
import { ProductsPage } from "./pages/admin/Products";
import { ProjectsPage } from "./pages/admin/Projects";
import { ServiceAccountsPage } from "./pages/admin/ServiceAccounts";
import { SigningKeysPage } from "./pages/admin/SigningKeys";
import { TeamsPage } from "./pages/admin/Teams";
import { UsersPage } from "./pages/admin/Users";
import { ForcedPasswordPage, PasswordPage } from "./pages/ChangePassword";
import { HomePage } from "./pages/Home";
import { LoginPage } from "./pages/Login";
import { AdminOnly, NotFoundPage } from "./pages/Misc";
import { NotificationsPage } from "./pages/Notifications";

function Authed() {
  const auth = useAuth();
  if (!auth.ready) return <Loading text="Проверяем вход…" />;
  // Временный пароль от администратора: до смены ролей нет, оболочку не показываем.
  if (auth.passwordChangeRequired) return <ForcedPasswordPage />;
  return (
    <ShellLayout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/password" element={<PasswordPage />} />
        <Route path="/admin/users" element={<AdminOnly><UsersPage /></AdminOnly>} />
        <Route path="/admin/groups" element={<AdminOnly><TeamsPage /></AdminOnly>} />
        <Route path="/admin/projects" element={<AdminOnly><ProjectsPage /></AdminOnly>} />
        <Route path="/admin/assets" element={<AdminOnly><AssetsPage /></AdminOnly>} />
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
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="*"
          element={
            <AuthProvider platformToken>
              <Authed />
            </AuthProvider>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
