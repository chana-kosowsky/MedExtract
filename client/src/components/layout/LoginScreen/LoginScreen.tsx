import { Info, LoaderCircle, LogIn, ScanText } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { Session } from "../../../api/types";
import "./LoginScreen.css";

interface Props {
  demo: Session["demo"];
  onLogin: (username: string, password: string) => Promise<string | null>;
}

/** מסך כניסה: שם משתמש וסיסמה, ומתחת פרטי משתמש הדמו (לחיצה ממלאת אותם). */
export default function LoginScreen({ demo, onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("צריך למלא שם משתמש וסיסמה.");
      return;
    }
    setSending(true);
    setError(await onLogin(username.trim(), password));
    setSending(false);
  }

  function fillDemo() {
    if (!demo) return;
    setUsername(demo.username);
    setPassword(demo.password);
    setError(null);
  }

  return (
    <div className="login">
      <form className="login-card" onSubmit={submit} noValidate>
        <div className="login-brand">
          <div className="login-logo">
            <ScanText />
          </div>
          <h1 className="login-title">MedExtract</h1>
          <p className="login-subtitle">כניסה למערכת</p>
        </div>

        <label className="login-field">
          <span>שם משתמש</span>
          <input
            className="login-input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            dir="ltr"
            autoFocus
          />
        </label>
        <label className="login-field">
          <span>סיסמה</span>
          <input
            className="login-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            dir="ltr"
          />
        </label>

        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}

        <button className="btn btn-primary login-submit" type="submit" disabled={sending}>
          {sending ? <LoaderCircle className="icon-sm spin" /> : <LogIn className="icon-sm" />}
          כניסה
        </button>

        {demo && (
          <button type="button" className="login-demo" onClick={fillDemo}>
            <Info className="icon-sm" />
            <span className="login-demo-text">
              <span>לצורך הדמו:</span>
              <span>
                שם משתמש <bdi className="login-demo-value">{demo.username}</bdi>
              </span>
              <span>
                סיסמה <bdi className="login-demo-value">{demo.password}</bdi>
              </span>
              <span className="login-demo-fill">לחיצה כאן ממלאת את הפרטים</span>
            </span>
          </button>
        )}
      </form>
    </div>
  );
}
