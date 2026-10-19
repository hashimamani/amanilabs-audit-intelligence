import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import QRCode from "qrcode";
import { ApiError } from "../api/client";
import { useAuth, type SignInOutcome } from "../auth/AuthContext";
import { getConfig } from "../config";

type Step = "credentials" | "newPassword" | "totpSetup" | "totpCode" | "resetRequest" | "resetConfirm";

function messageFor(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) {
    if (err.name === "NotAuthorizedException" || err.name === "UserNotFoundException") return "Invalid email or password.";
    if (err.name === "CodeMismatchException") return "That code is not right. Try again.";
    if (err.name === "InvalidPasswordException") return "The password does not meet the policy: 12+ characters with upper and lower case, a digit and a symbol.";
    if (err.name === "LimitExceededException") return "Too many attempts. Wait a few minutes and try again.";
    return err.message || "Sign-in failed.";
  }
  return "Sign-in failed.";
}

export function LoginPage() {
  const { user, loading, signIn, completeNewPassword, totpSetup, confirmTotp, requestPasswordReset, confirmPasswordReset } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const cognito = getConfig().authMode === "cognito";

  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [code, setCode] = useState("");
  const [qr, setQr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (totpSetup) QRCode.toDataURL(totpSetup.uri, { margin: 1, width: 180 }).then(setQr).catch(() => setQr(null));
  }, [totpSetup]);

  if (!loading && user) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  function follow(outcome: SignInOutcome) {
    if (outcome === "signedIn") navigate("/", { replace: true });
    else if (outcome === "newPasswordRequired") setStep("newPassword");
    else if (outcome === "totpSetupRequired") setStep("totpSetup");
    else setStep("totpCode");
  }

  async function run(action: () => Promise<void>) {
    setSubmitting(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setSubmitting(false);
    }
  }

  const field = (label: string, props: React.InputHTMLAttributes<HTMLInputElement>) => {
    const id = `login-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`;
    return (
      <div>
        <label htmlFor={id} className="text-xs font-medium text-slate-500">
          {label}
        </label>
        <input id={id} {...props} className="input-field mt-1 block w-full" />
      </div>
    );
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-b from-indigo-50 via-slate-50 to-slate-50 px-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (step === "credentials") void run(async () => follow(await signIn(email, password)));
          else if (step === "newPassword") void run(async () => follow(await completeNewPassword(newPassword)));
          else if (step === "totpSetup" || step === "totpCode") void run(async () => follow(await confirmTotp(code)));
          else if (step === "resetRequest")
            void run(async () => {
              await requestPasswordReset(email);
              setInfo("If that address has an account, a code is on its way.");
              setStep("resetConfirm");
            });
          else
            void run(async () => {
              await confirmPasswordReset(email, code, newPassword);
              setInfo("Password changed. Sign in with it.");
              setCode("");
              setNewPassword("");
              setStep("credentials");
            });
        }}
        className="card w-full max-w-sm space-y-4 p-8"
      >
        <div className="flex flex-col items-center text-center">
          <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
            <ShieldCheck className="h-6 w-6" />
          </span>
          <h1 className="text-xl font-semibold text-slate-900">Audit Intelligence</h1>
          <p className="mt-1 text-sm text-slate-500">
            {step === "credentials" && "Sign in to continue"}
            {step === "newPassword" && "Choose your own password"}
            {step === "totpSetup" && "Set up your authenticator app"}
            {step === "totpCode" && "Enter the code from your authenticator app"}
            {step === "resetRequest" && "Reset your password"}
            {step === "resetConfirm" && "Enter the code we emailed you"}
          </p>
        </div>

        {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>}
        {info && !error && <div className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">{info}</div>}

        {step === "credentials" && (
          <>
            {field("Email", { type: "email", required: true, autoComplete: "username", value: email, onChange: (e) => setEmail(e.target.value) })}
            {field("Password", { type: "password", required: true, autoComplete: "current-password", value: password, onChange: (e) => setPassword(e.target.value) })}
          </>
        )}
        {step === "newPassword" &&
          field("New password", { type: "password", required: true, minLength: 12, autoComplete: "new-password", value: newPassword, onChange: (e) => setNewPassword(e.target.value) })}
        {step === "totpSetup" && totpSetup && (
          <div className="space-y-3 text-sm text-slate-600">
            <p>Scan this with Google Authenticator, Microsoft Authenticator or any TOTP app, then enter the 6-digit code it shows.</p>
            {qr ? <img src={qr} alt="Authenticator QR code" className="mx-auto rounded-md" /> : null}
            <p className="break-all text-xs text-slate-500">
              Can't scan? Enter this key by hand: <span className="font-mono">{totpSetup.secret}</span>
            </p>
            {field("Code", { inputMode: "numeric", required: true, pattern: "[0-9]{6}", value: code, onChange: (e) => setCode(e.target.value) })}
          </div>
        )}
        {step === "totpCode" && field("Code", { inputMode: "numeric", required: true, pattern: "[0-9]{6}", autoComplete: "one-time-code", value: code, onChange: (e) => setCode(e.target.value) })}
        {step === "resetRequest" && field("Email", { type: "email", required: true, value: email, onChange: (e) => setEmail(e.target.value) })}
        {step === "resetConfirm" && (
          <>
            {field("Code", { inputMode: "numeric", required: true, value: code, onChange: (e) => setCode(e.target.value) })}
            {field("New password", { type: "password", required: true, minLength: 12, autoComplete: "new-password", value: newPassword, onChange: (e) => setNewPassword(e.target.value) })}
          </>
        )}

        <button type="submit" disabled={submitting} className="btn-primary w-full">
          {submitting ? "Please wait…" : step === "credentials" ? "Sign in" : "Continue"}
        </button>

        {cognito && step === "credentials" && (
          <button type="button" onClick={() => { setError(null); setStep("resetRequest"); }} className="w-full text-center text-xs text-slate-500 hover:text-slate-800">
            Forgot your password?
          </button>
        )}
        {step !== "credentials" && (
          <button type="button" onClick={() => { setError(null); setInfo(null); setStep("credentials"); }} className="w-full text-center text-xs text-slate-500 hover:text-slate-800">
            Back to sign in
          </button>
        )}
      </form>
    </div>
  );
}
