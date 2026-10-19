import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Amplify } from "aws-amplify";
import {
  confirmResetPassword,
  confirmSignIn,
  fetchAuthSession,
  resetPassword,
  signIn as amplifySignIn,
  signOut as amplifySignOut,
} from "aws-amplify/auth";
import { ApiError, getMe, login as apiLogin, setTokenProvider } from "../api/client";
import type { UserInfo } from "../api/types";
import { getConfig } from "../config";

const LOCAL_TOKEN_KEY = "audit_intelligence_token";

/** Where Cognito's sign-in flow is after a step, mirrored for local mode. */
export type SignInOutcome = "signedIn" | "newPasswordRequired" | "totpSetupRequired" | "totpCodeRequired";

export interface TotpSetup {
  secret: string;
  uri: string;
}

interface AuthContextValue {
  user: UserInfo | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<SignInOutcome>;
  completeNewPassword: (newPassword: string) => Promise<SignInOutcome>;
  totpSetup: TotpSetup | null;
  confirmTotp: (code: string) => Promise<SignInOutcome>;
  requestPasswordReset: (email: string) => Promise<void>;
  confirmPasswordReset: (email: string, code: string, newPassword: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function configureAuth(): void {
  const config = getConfig();
  if (config.authMode === "cognito" && config.userPoolId && config.userPoolClientId) {
    Amplify.configure({ Auth: { Cognito: { userPoolId: config.userPoolId, userPoolClientId: config.userPoolClientId } } });
    setTokenProvider(async () => {
      try {
        return (await fetchAuthSession()).tokens?.idToken?.toString() ?? null;
      } catch {
        return null;
      }
    });
  } else {
    setTokenProvider(async () => localStorage.getItem(LOCAL_TOKEN_KEY));
  }
}

export class AuthFlowError extends Error {}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [totpSetup, setTotpSetup] = useState<TotpSetup | null>(null);
  const pendingEmail = useRef<string>("");

  const refresh = useCallback(async () => {
    try {
      setUser(await getMe());
    } catch {
      setUser(null);
      if (getConfig().authMode === "local") localStorage.removeItem(LOCAL_TOKEN_KEY);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await refresh();
      setLoading(false);
    })();
  }, [refresh]);

  const settle = useCallback(
    async (result: { isSignedIn: boolean; nextStep: { signInStep: string; totpSetupDetails?: { sharedSecret: string; getSetupUri: (app: string, account?: string) => URL } } }): Promise<SignInOutcome> => {
      const step = result.nextStep.signInStep;
      if (step === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED") return "newPasswordRequired";
      if (step === "CONTINUE_SIGN_IN_WITH_TOTP_SETUP" && result.nextStep.totpSetupDetails) {
        const details = result.nextStep.totpSetupDetails;
        setTotpSetup({ secret: details.sharedSecret, uri: details.getSetupUri("Audit Intelligence", pendingEmail.current).toString() });
        return "totpSetupRequired";
      }
      if (step === "CONFIRM_SIGN_IN_WITH_TOTP_CODE") return "totpCodeRequired";
      if (!result.isSignedIn) throw new AuthFlowError(`Sign-in needs a step this app does not handle (${step}).`);
      setTotpSetup(null);
      await refresh();
      return "signedIn";
    },
    [refresh],
  );

  const signIn = useCallback(
    async (email: string, password: string): Promise<SignInOutcome> => {
      pendingEmail.current = email;
      if (getConfig().authMode === "local") {
        const result = await apiLogin(email, password);
        localStorage.setItem(LOCAL_TOKEN_KEY, result.access_token);
        setUser(result.user);
        return "signedIn";
      }
      try {
        await amplifySignOut();
      } catch {
        // There was no stale session to clear.
      }
      return settle(await amplifySignIn({ username: email, password }));
    },
    [settle],
  );

  const completeNewPassword = useCallback(
    async (newPassword: string) => settle(await confirmSignIn({ challengeResponse: newPassword })),
    [settle],
  );

  const confirmTotp = useCallback(async (code: string) => settle(await confirmSignIn({ challengeResponse: code })), [settle]);

  const logout = useCallback(async () => {
    if (getConfig().authMode === "cognito") {
      await amplifySignOut();
    } else {
      localStorage.removeItem(LOCAL_TOKEN_KEY);
    }
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      signIn,
      completeNewPassword,
      totpSetup,
      confirmTotp,
      logout,
      requestPasswordReset: async (email: string) => {
        if (getConfig().authMode === "local") throw new ApiError(400, "Password reset is not available in local mode.");
        await resetPassword({ username: email });
      },
      confirmPasswordReset: async (email: string, code: string, newPassword: string) => {
        await confirmResetPassword({ username: email, confirmationCode: code, newPassword });
      },
    }),
    [user, loading, signIn, completeNewPassword, totpSetup, confirmTotp, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
