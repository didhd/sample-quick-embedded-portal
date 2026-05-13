import { Loader2 } from "lucide-react";

export function PanelLoading({ label }) {
    return (
        <div className="flex h-full w-full items-center justify-center">
            <div className="flex items-center gap-3 rounded-full border border-ink-200 bg-white px-4 py-2 text-[13px] text-ink-600 shadow-sm">
                <Loader2 className="h-4 w-4 animate-spin text-brand-500" />
                {label}
            </div>
        </div>
    );
}

export function PanelError({ title, message, action }) {
    return (
        <div className="flex h-full w-full items-center justify-center p-8">
            <div className="max-w-md rounded-xl border border-rose-200 bg-rose-50 p-6 text-rose-900 shadow-sm">
                <div className="text-[14px] font-semibold">{title}</div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-rose-800/90">{message}</p>
                {action ? <div className="mt-4">{action}</div> : null}
            </div>
        </div>
    );
}

export function PanelEmpty({ title, message, action }) {
    return (
        <div className="flex h-full w-full items-center justify-center p-8">
            <div className="max-w-md rounded-xl border border-ink-200 bg-white p-6 text-center shadow-sm">
                <div className="text-[14px] font-semibold text-ink-800">{title}</div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink-600">{message}</p>
                {action ? <div className="mt-4">{action}</div> : null}
            </div>
        </div>
    );
}
