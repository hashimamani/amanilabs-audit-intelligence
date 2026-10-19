import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, configureAuth } from "../auth/AuthContext";
import { LoginPage } from "./LoginPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const user = { id: "u1", email: "admin@default.local", name: "Default Admin", role: "admin", is_active: true, tenant_slug: "default", tenant_name: "Default / Demo" };

afterEach(() => vi.restoreAllMocks());

function renderLogin() {
  configureAuth();
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<h1>Dashboard</h1>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("LoginPage (local mode)", () => {
  it("signs in through the API and lands on the dashboard", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ detail: "Invalid or missing credentials" }, 401)) // boot-time /auth/me
      .mockResolvedValueOnce(jsonResponse({ access_token: "tok", user }));
    renderLogin();
    await userEvent.type(await screen.findByLabelText("Email"), "admin@default.local");
    await userEvent.type(screen.getByLabelText("Password"), "local-dev-admin");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument());
    expect(localStorage.getItem("audit_intelligence_token")).toBe("tok");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/auth/login");
  });

  it("shows the API's message on a bad password", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ detail: "Invalid or missing credentials" }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "Invalid email or password" }, 401));
    renderLogin();
    await userEvent.type(await screen.findByLabelText("Email"), "admin@default.local");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Invalid email or password")).toBeInTheDocument();
    expect(screen.queryByText("Forgot your password?")).not.toBeInTheDocument();
  });
});
