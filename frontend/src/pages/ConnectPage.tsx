import { Lock, Network } from "lucide-react";
import type { Me } from "../types/graph";
import { AndroidLogo, GithubLogo, JavaLogo, KotlinLogo, PythonLogo } from "../graph/style";

const ERRORS: Record<string, string> = {
  access_denied: "GitHub authorization was cancelled.",
  invalid_state: "The sign-in request could not be verified (state mismatch). Please try again.",
  token_exchange_failed: "GitHub did not return an access token. Check the OAuth app credentials.",
  user_fetch_failed: "Signed in, but the GitHub account could not be read.",
};

export default function ConnectPage({ me }: { me: Me | null }) {
  const err = new URLSearchParams(window.location.search).get("auth_error");
  return (
    <div className="connect">
      <div className="connect-card">
        <Network size={44} color="#3ddc84" />
        <h1>CodeAtlas</h1>
        <p>Deterministic code graphs for Python and Android projects. Python, Kotlin, and Java source are analyzed locally — no LLM or AI APIs.</p>
        <div className="logos"><PythonLogo size={26} /><AndroidLogo size={26} /><KotlinLogo size={26} /><JavaLogo size={26} /></div>
        {err && <div className="alert error">{ERRORS[err] ?? "Authentication failed."}</div>}
        {me && !me.oauth_configured && (
          <div className="alert error">GitHub OAuth is not configured on the backend. Add GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET to .env (see README).</div>
        )}
        <a className="btn primary" href="/auth/github"><GithubLogo size={16} color="currentColor" /> Connect GitHub</a>
        <small>Requests no scopes and lists public repositories only.</small>
        <a className="btn" href="/auth/github?private=true"><Lock size={16} /> Connect with private repository access</a>
        <small>Requests GitHub's <code>repo</code> scope and lists private repositories only. Read-only usage; the token stays on the server.</small>
      </div>
    </div>
  );
}
