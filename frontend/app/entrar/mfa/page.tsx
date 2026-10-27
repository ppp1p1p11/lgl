"use client";

import { useRouter, useSearchParams } from "next/navigation";
import QRCode from "qrcode";
import { Suspense, useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/errors";
import { t } from "@/lib/i18n";

function CodeField() {
  return (
    <label>
      {t.mfa.code}
      <input
        name="code"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="\d{6}"
        maxLength={6}
        required
      />
    </label>
  );
}

function Setup({ onDone }: { onDone: (codes: string[]) => void }) {
  const [secret, setSecret] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.POST("/api/auth/mfa/setup").then(async ({ data, error: apiError }) => {
      if (!data) {
        setError(errorMessage(apiError));
        return;
      }
      setSecret(data.secret);
      setQr(await QRCode.toDataURL(data.otpauth_uri, { margin: 1, width: 200 }));
    });
  }, []);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code"));
    const { data, error: apiError } = await api.POST("/api/auth/mfa/confirm", { body: { code } });
    if (!data) {
      setError(errorMessage(apiError));
      return;
    }
    onDone(data.recovery_codes);
  }

  return (
    <>
      <h1>{t.mfa.setupTitle}</h1>
      <p className="muted">{t.mfa.setupIntro}</p>
      <p>{t.mfa.setupScan}</p>
      {/* eslint-disable-next-line @next/next/no-img-element -- local data: URL */}
      {qr && <img src={qr} alt="QR code" width={200} height={200} />}
      {secret && (
        <p>
          {t.mfa.setupManual} <code className="secret">{secret}</code>
        </p>
      )}
      <p>{t.mfa.setupEnterCode}</p>
      <form onSubmit={onSubmit}>
        <CodeField />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit">{t.mfa.submit}</button>
      </form>
    </>
  );
}

function Verify({ onDone }: { onDone: () => void }) {
  const router = useRouter();
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = useRecovery
      ? { recovery_code: String(form.get("recovery_code")) }
      : { code: String(form.get("code")) };
    const { response, error: apiError } = await api.POST("/api/auth/mfa/verify", { body });
    if (response.ok) {
      onDone();
      return;
    }
    if (response.status === 401 && errorMessage(apiError) === t.errors.not_authenticated) {
      router.replace("/entrar");
      return;
    }
    setError(errorMessage(apiError));
  }

  return (
    <>
      <h1>{t.mfa.verifyTitle}</h1>
      <p className="muted">{t.mfa.verifyIntro}</p>
      <form onSubmit={onSubmit}>
        {useRecovery ? (
          <label>
            {t.mfa.recoveryCode}
            <input name="recovery_code" autoComplete="off" required />
          </label>
        ) : (
          <CodeField />
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit">{t.mfa.submit}</button>
        <button type="button" className="link" onClick={() => setUseRecovery(!useRecovery)}>
          {useRecovery ? t.mfa.useTotp : t.mfa.useRecovery}
        </button>
      </form>
    </>
  );
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <>
      <h1>{t.mfa.recoveryTitle}</h1>
      <p>{t.mfa.recoveryIntro}</p>
      <div className="codes">
        {codes.map((c) => (
          <span key={c}>{c}</span>
        ))}
      </div>
      <p>
        <button type="button" onClick={onDone}>
          {t.mfa.recoveryDone}
        </button>
      </p>
    </>
  );
}

function MfaFlow() {
  const router = useRouter();
  const step = useSearchParams().get("etapa");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const goToApp = () => router.replace("/processos");

  return (
    <main className="auth">
      <div className="card">
        {recoveryCodes ? (
          <RecoveryCodes codes={recoveryCodes} onDone={goToApp} />
        ) : step === "configurar" ? (
          <Setup onDone={setRecoveryCodes} />
        ) : (
          <Verify onDone={goToApp} />
        )}
      </div>
    </main>
  );
}

export default function MfaPage() {
  return (
    <Suspense>
      <MfaFlow />
    </Suspense>
  );
}
