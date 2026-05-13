import { LogOut, MessageSquare, MessageSquareOff, Sparkles } from "lucide-react";

function Chip({ children }) {
    return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 bg-ink-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider text-ink-600">
            {children}
        </span>
    );
}

export function Header({ title, userEmail, chatOpen, onToggleChat, onLogout }) {
    return (
        <header className="flex items-center justify-between gap-4 border-b border-ink-200/80 bg-white/95 backdrop-blur-sm px-6 py-3 supports-[backdrop-filter]:bg-white/80">
            <div className="flex items-center gap-3">
                <div className="grid h-9 w-9 place-items-center rounded-lg bg-squidInk text-brand-500 shadow-glow">
                    <span className="font-black text-[15px] tracking-tight">AC</span>
                </div>
                <div className="leading-tight">
                    <div className="text-[15px] font-semibold text-ink-900">{title}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-500">
                        <span>Powered by AWS Quick Suite</span>
                        <span className="text-ink-300">·</span>
                        <Chip>
                            <Sparkles className="h-3 w-3" />
                            Live
                        </Chip>
                    </div>
                </div>
            </div>

            <div className="flex items-center gap-2">
                {userEmail ? (
                    <div className="hidden sm:block text-right leading-tight">
                        <div className="text-[12px] font-medium text-ink-700">{userEmail}</div>
                        <div className="text-[10px] uppercase tracking-wider text-ink-500">
                            Operations Manager
                        </div>
                    </div>
                ) : null}

                <button
                    type="button"
                    onClick={onToggleChat}
                    className={
                        "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-[13px] font-medium transition-colors " +
                        (chatOpen
                            ? "border-brand-500 bg-brand-500 text-squidInk hover:bg-brand-400"
                            : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50")
                    }
                    aria-pressed={chatOpen}
                >
                    {chatOpen ? (
                        <>
                            <MessageSquareOff className="h-4 w-4" />
                            Hide Chat Agents
                        </>
                    ) : (
                        <>
                            <MessageSquare className="h-4 w-4" />
                            Chat Agents
                        </>
                    )}
                </button>

                {userEmail ? (
                    <button
                        type="button"
                        onClick={onLogout}
                        className="inline-flex items-center gap-1.5 rounded-md border border-ink-200 bg-white px-3 py-1.5 text-[13px] font-medium text-ink-600 hover:bg-ink-50"
                    >
                        <LogOut className="h-4 w-4" />
                        Sign out
                    </button>
                ) : null}
            </div>
        </header>
    );
}
