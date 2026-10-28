import { Network } from "lucide-react";
import type { Me } from "../types/graph";
import { GithubLogo, LanguageLogo, type Theme } from "../graph/style";

const ERRORS: Record<string, string> = {
  access_denied: "GitHub authorization was cancelled.",
  invalid_state: "The sign-in request could not be verified (state mismatch). Please try again.",
  token_exchange_failed: "GitHub did not return an access token. Check the OAuth app credentials.",
  user_fetch_failed: "Signed in, but the GitHub account could not be read.",
};

export default function ConnectPage({ me, theme }: { me: Me | null; theme: Theme }) {
  const err = new URLSearchParams(window.location.search).get("auth_error");
  return (
    <div className="connect">
      <div className="connect-card">
        <div className="brand-mark"><Network size={44} /></div>
        <p className="eyebrow">Code intelligence for software teams</p>
        <h1>Map dependencies before they become hidden risk.</h1>
        <p>Deterministic code graphs for Python and Android projects. Python, Kotlin, and Java source are analyzed locally — no LLM or AI APIs.</p>

        <div className="logos" aria-label="Supported languages">
          <LanguageLogo lang="python" size={26} theme={theme} />
          <LanguageLogo lang="android" size={26} theme={theme} />
          <LanguageLogo lang="kotlin" size={26} theme={theme} />
          <LanguageLogo lang="java" size={26} theme={theme} />
        </div>

        <div className="feature-grid">
          <div className="feature-item"><strong>Deterministic</strong><span>Static graph analysis, no model guesses.</span></div>
          <div className="feature-item"><strong>Focused</strong><span>Entry points, callers, dependencies, and members.</span></div>
          <div className="feature-item"><strong>Safe</strong><span>Repository contents are parsed locally and never executed.</span></div>
        </div>

        {err && <div className="alert error">{ERRORS[err] ?? "Authentication failed."}</div>}
        {me && !me.oauth_configured && (
          <div className="alert error">GitHub OAuth is not configured on the backend. Add GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET to .env (see README).</div>
        )}

        <a className="btn primary" href="/auth/github"><GithubLogo size={16} color="currentColor" /> Connect GitHub</a>
        <small>Browse public and private repositories from separate filters in CodeAtlas. GitHub's <code>repo</code> permission is requested for private access; CodeAtlas only reads repository contents, and your token remains server-side.</small>
      </div>
    </div>
  );
}
