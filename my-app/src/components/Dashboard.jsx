import { useEffect, useRef, useState } from "react";
import { AccessRequiredError, fetchDashboardEmbedUrl, SessionExpiredError } from "../lib/api.js";
import { mountDashboard } from "../lib/embedding.js";
import { PanelError, PanelLoading } from "./Panel.jsx";

export function Dashboard({ idToken, onSessionExpired }) {
    const containerRef = useRef(null);
    const experienceRef = useRef(null);
    const loadedForTokenRef = useRef(null);
    const [phase, setPhase] = useState("loading");
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!idToken || !containerRef.current) return;
        // Load exactly once per auth token. Re-renders (e.g. toggling the chat
        // sidebar) must not re-fetch or re-mount the dashboard.
        if (loadedForTokenRef.current === idToken) return;
        loadedForTokenRef.current = idToken;

        let cancelled = false;
        async function load() {
            setPhase("loading");
            setError(null);
            try {
                const { DashboardEmbedUrl } = await fetchDashboardEmbedUrl(idToken);
                if (cancelled) return;
                if (experienceRef.current?.unmount) {
                    try {
                        experienceRef.current.unmount();
                    } catch {
                        /* noop */
                    }
                }
                experienceRef.current = await mountDashboard(
                    containerRef.current,
                    DashboardEmbedUrl,
                    () => !cancelled && setPhase("ready"),
                );
            } catch (e) {
                if (cancelled) return;
                if (e instanceof SessionExpiredError) {
                    onSessionExpired?.();
                    return;
                }
                loadedForTokenRef.current = null; // allow retry after error
                setError(e);
                setPhase("error");
            }
        }
        load();
        return () => {
            cancelled = true;
        };
    }, [idToken, onSessionExpired]);

    return (
        <div className="relative h-full w-full bg-white">
            <div
                ref={containerRef}
                className="embed-root absolute inset-0"
                style={{ visibility: phase === "ready" ? "visible" : "hidden" }}
            />
            {phase === "loading" ? (
                <div className="absolute inset-0">
                    <PanelLoading label="Loading operations dashboard…" />
                </div>
            ) : null}
            {phase === "error" ? (
                <div className="absolute inset-0">
                    <PanelError
                        title={
                            error instanceof AccessRequiredError
                                ? "Dashboard access required"
                                : "Dashboard unavailable"
                        }
                        action={null}
                        message={error?.message || "Please refresh or contact an administrator."}
                    />
                </div>
            ) : null}
        </div>
    );
}
