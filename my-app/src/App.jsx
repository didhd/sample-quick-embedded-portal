import { useCallback, useEffect, useState } from "react";
import { ChatSidebar } from "./components/ChatSidebar.jsx";
import { Dashboard } from "./components/Dashboard.jsx";
import { Header } from "./components/Header.jsx";
import { PanelError, PanelLoading } from "./components/Panel.jsx";
import {
    clearIdToken,
    decodeJwtPayload,
    exchangeCodeForTokens,
    getIdToken,
    isTokenLive,
    logout,
    redirectToLogin,
    storeIdToken,
} from "./lib/auth.js";
import { getPortalTitle } from "./lib/config.js";

function useAuth() {
    const [phase, setPhase] = useState("init"); // init | authed | redirecting | error
    const [idToken, setIdToken] = useState(null);
    const [fatal, setFatal] = useState(null);

    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        const code = params.get("code");
        const existing = getIdToken();

        if (code) {
            (async () => {
                try {
                    const token = await exchangeCodeForTokens(code);
                    storeIdToken(token);
                    window.history.replaceState({}, document.title, window.location.pathname);
                    setIdToken(token);
                    setPhase("authed");
                } catch (e) {
                    setFatal(e);
                    setPhase("error");
                }
            })();
            return;
        }
        if (existing && isTokenLive(existing)) {
            setIdToken(existing);
            setPhase("authed");
            return;
        }
        clearIdToken();
        setPhase("redirecting");
        try {
            redirectToLogin();
        } catch (e) {
            setFatal(e);
            setPhase("error");
        }
    }, []);

    // Stable identity so Dashboard/ChatSidebar effects don't re-run on every
    // parent render (e.g. when chat sidebar toggles open/closed).
    const onSessionExpired = useCallback(() => {
        clearIdToken();
        setPhase("redirecting");
        try {
            redirectToLogin();
        } catch (e) {
            setFatal(e);
            setPhase("error");
        }
    }, []);

    return { phase, idToken, fatal, onSessionExpired };
}

export default function App() {
    const { phase, idToken, fatal, onSessionExpired } = useAuth();
    const [chatOpen, setChatOpen] = useState(false);

    const email = idToken ? decodeJwtPayload(idToken)?.email : null;

    return (
        <div className="flex h-full flex-col bg-ink-50">
            <Header
                title={getPortalTitle()}
                userEmail={email}
                chatOpen={chatOpen}
                onToggleChat={() => setChatOpen((v) => !v)}
                onLogout={logout}
            />

            <div className="relative flex flex-1 min-h-0 overflow-hidden">
                <main className="flex-1 min-w-0 p-4">
                    <div className="h-full w-full overflow-hidden rounded-xl border border-ink-200 bg-white shadow-panel">
                        {phase === "authed" && idToken ? (
                            <Dashboard idToken={idToken} onSessionExpired={onSessionExpired} />
                        ) : phase === "error" ? (
                            <PanelError
                                title="Unable to load portal"
                                message={fatal?.message || "An unexpected error occurred."}
                            />
                        ) : (
                            <PanelLoading
                                label={
                                    phase === "redirecting"
                                        ? "Redirecting to sign-in…"
                                        : "Preparing your portal…"
                                }
                            />
                        )}
                    </div>
                </main>

                <ChatSidebar
                    idToken={idToken}
                    open={chatOpen && phase === "authed"}
                    onClose={() => setChatOpen(false)}
                    onSessionExpired={onSessionExpired}
                />
            </div>
        </div>
    );
}
