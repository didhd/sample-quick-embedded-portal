import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, Sparkles, X } from "lucide-react";
import { AccessRequiredError, fetchChatEmbedUrl, SessionExpiredError } from "../lib/api.js";
import { mountChat } from "../lib/embedding.js";
import { getChatConfig } from "../lib/config.js";
import { PanelError, PanelLoading } from "./Panel.jsx";

// Re-fetch a fresh embed URL if it's older than this. QuickSight embed URLs
// must be redeemed within 5 minutes; the resulting iframe session then lives
// for SessionLifetimeInMinutes. This guards against stale URLs on re-open.
const EMBED_URL_MAX_AGE_MS = 4 * 60 * 1000;

export function ChatSidebar({ idToken, open, onClose, onSessionExpired }) {
    const containerRef = useRef(null);
    const experienceRef = useRef(null);
    const mountedAtRef = useRef(0);
    const [phase, setPhase] = useState("idle");
    const [error, setError] = useState(null);
    const [reloadKey, setReloadKey] = useState(0);

    const unmountExperience = useCallback(() => {
        if (experienceRef.current?.unmount) {
            try {
                experienceRef.current.unmount();
            } catch {
                /* noop */
            }
        }
        experienceRef.current = null;
        if (containerRef.current) containerRef.current.textContent = "";
    }, []);

    const reload = useCallback(() => {
        unmountExperience();
        mountedAtRef.current = 0;
        setReloadKey((k) => k + 1);
    }, [unmountExperience]);

    useEffect(() => {
        if (!open || !idToken || !containerRef.current) return;

        const age = Date.now() - mountedAtRef.current;
        if (experienceRef.current && age < EMBED_URL_MAX_AGE_MS && phase === "ready") {
            return;
        }

        let cancelled = false;

        async function load() {
            unmountExperience();
            setPhase("loading");
            setError(null);
            try {
                const { ChatEmbedUrl } = await fetchChatEmbedUrl(idToken);
                if (cancelled) return;
                experienceRef.current = await mountChat(
                    containerRef.current,
                    ChatEmbedUrl,
                    getChatConfig(),
                    () => {
                        if (cancelled) return;
                        mountedAtRef.current = Date.now();
                        setPhase("ready");
                    },
                );
            } catch (e) {
                if (cancelled) return;
                if (e instanceof SessionExpiredError) {
                    onSessionExpired?.();
                    return;
                }
                setError(e);
                setPhase("error");
            }
        }
        load();
        return () => {
            cancelled = true;
        };
    }, [open, idToken, reloadKey, onSessionExpired, unmountExperience, phase]);

    return (
        <>
            {/* backdrop on narrow screens only */}
            <div
                onClick={onClose}
                className={
                    "fixed inset-0 z-30 bg-ink-900/30 backdrop-blur-[2px] transition-opacity lg:hidden " +
                    (open ? "opacity-100" : "pointer-events-none opacity-0")
                }
            />

            <aside
                className={
                    "z-40 flex flex-col border-l border-ink-200 bg-white shadow-panel transition-[width] duration-300 ease-out " +
                    "overflow-hidden h-full " +
                    (open ? "w-[min(420px,100vw)] lg:w-[28rem]" : "w-0")
                }
                aria-hidden={!open}
            >
                <div className="flex items-center justify-between border-b border-ink-200 bg-gradient-to-br from-squidInk to-squid px-4 py-3 text-white">
                    <div className="flex items-center gap-2.5">
                        <div className="grid h-7 w-7 place-items-center rounded-md bg-brand-500/20 text-brand-400">
                            <Sparkles className="h-4 w-4" />
                        </div>
                        <div className="leading-tight">
                            <div className="text-[14px] font-semibold">Chat Agents</div>
                            <div className="text-[11px] text-ink-300">
                                Natural language for your ops data
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-1">
                        <button
                            type="button"
                            onClick={reload}
                            className="rounded-md p-1 text-ink-300 hover:bg-white/10 hover:text-white disabled:opacity-40"
                            aria-label="Reload Chat Agents session"
                            disabled={phase === "loading"}
                            title="Reload session"
                        >
                            <RefreshCw className={"h-4 w-4 " + (phase === "loading" ? "animate-spin" : "")} />
                        </button>
                        <button
                            type="button"
                            onClick={onClose}
                            className="rounded-md p-1 text-ink-300 hover:bg-white/10 hover:text-white"
                            aria-label="Close Chat Agents panel"
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                </div>

                <div className="relative flex-1 min-h-0">
                    <div
                        ref={containerRef}
                        className="embed-root absolute inset-0"
                        style={{ visibility: phase === "ready" ? "visible" : "hidden" }}
                    />
                    {phase === "loading" ? (
                        <div className="absolute inset-0">
                            <PanelLoading label="Loading Chat Agents…" />
                        </div>
                    ) : null}
                    {phase === "error" ? (
                        <div className="absolute inset-0">
                            <PanelError
                                title={
                                    error instanceof AccessRequiredError
                                        ? "Chat agent not shared"
                                        : "Chat Agents unavailable"
                                }
                                message={
                                    error instanceof AccessRequiredError
                                        ? "An administrator needs to create and share a Chat agent with this user before you can ask questions."
                                        : error?.message || "Click the reload icon to retry."
                                }
                                action={
                                    <button
                                        type="button"
                                        onClick={reload}
                                        className="inline-flex items-center gap-1.5 rounded-md border border-rose-300 bg-white px-2.5 py-1 text-[12px] font-medium text-rose-800 hover:bg-rose-100"
                                    >
                                        <RefreshCw className="h-3.5 w-3.5" />
                                        Reload
                                    </button>
                                }
                            />
                        </div>
                    ) : null}
                </div>
            </aside>
        </>
    );
}
