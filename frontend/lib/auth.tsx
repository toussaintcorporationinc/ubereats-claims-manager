"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  SESSION_EXPIRED_EVENT,
  api,
  clearStoredToken,
  getStoredToken,
  type LoginPayload,
  type RegisterOwnerPayload,
  type User,
} from "./api";

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  signIn: (payload: LoginPayload) => Promise<User>;
  setupOwner: (payload: RegisterOwnerPayload) => Promise<User>;
  logout: () => void;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  async function refreshUser() {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }

    try {
      setUser(await api.getMe());
    } catch {
      clearStoredToken();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshUser();
  }, []);

  useEffect(() => {
    function handleSessionExpired() {
      setUser(null);
      setLoading(false);
    }

    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      signIn: async (payload) => {
        const response = await api.login(payload);
        setUser(response.user);
        return response.user;
      },
      setupOwner: async (payload) => {
        const response = await api.registerOwner(payload);
        setUser(response.user);
        return response.user;
      },
      logout: () => {
        api.logout();
        setUser(null);
      },
      refreshUser,
    }),
    [loading, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
