// Thin wrapper around the globally-loaded Quick Suite Embedding SDK.
let ctxPromise = null;

function waitForSdk() {
    if (window.QuickSightEmbedding) return Promise.resolve(window.QuickSightEmbedding);
    return new Promise((resolve, reject) => {
        const start = Date.now();
        const id = setInterval(() => {
            if (window.QuickSightEmbedding) {
                clearInterval(id);
                resolve(window.QuickSightEmbedding);
            } else if (Date.now() - start > 10000) {
                clearInterval(id);
                reject(new Error("Quick Suite Embedding SDK failed to load"));
            }
        }, 50);
    });
}

async function getContext() {
    if (!ctxPromise) {
        ctxPromise = waitForSdk().then((sdk) => sdk.createEmbeddingContext());
    }
    return ctxPromise;
}

// Fire onReady on the earliest usable iframe signal. FRAME_MOUNTED fires sooner
// than FRAME_LOADED in practice; either one is enough to reveal the iframe.
function onChangeReveal(onReady) {
    let fired = false;
    return (ev) => {
        if (fired) return;
        if (ev.eventName === "FRAME_MOUNTED" || ev.eventName === "FRAME_LOADED") {
            fired = true;
            onReady?.();
        }
    };
}

export async function mountDashboard(containerEl, url, onReady) {
    const ctx = await getContext();
    return ctx.embedDashboard(
        {
            url,
            container: containerEl,
            height: "100%",
            width: "100%",
            onChange: onChangeReveal(onReady),
        },
        {
            toolbarOptions: { export: true, undoRedo: true, reset: true },
            attributionOptions: { overlayContent: false },
        },
    );
}

export async function mountChat(containerEl, url, chatConfig = {}, onReady) {
    const ctx = await getContext();
    const contentOptions = {
        promptOptions: {
            allowFileAttachments: !!chatConfig.allowFileAttachments,
            showAgentKnowledgeBoundary: chatConfig.showAgentKnowledgeBoundary !== false,
            showWebSearch: !!chatConfig.showWebSearch,
            showInitialPromptMessage: false,
            showChatHistory: true,
            showPromptArea: true,
            enablePrivateMode: false,
        },
        footerOptions: {
            showBrandAttribution: !!chatConfig.showBrandAttribution,
            showUsagePolicy: chatConfig.showUsagePolicy !== false,
        },
    };
    if (chatConfig.fixedAgentId) {
        contentOptions.agentOptions = { fixedAgentId: chatConfig.fixedAgentId };
    }
    return ctx.embedQuickChat(
        {
            url,
            container: containerEl,
            height: "100%",
            width: "100%",
            onChange: onChangeReveal(onReady),
        },
        contentOptions,
    );
}
