import { getApiUrl } from "./config.js";

export class AccessRequiredError extends Error {
    constructor(payload) {
        super(payload.message || "Access required");
        this.name = "AccessRequiredError";
        this.payload = payload;
    }
}

export class SessionExpiredError extends Error {
    constructor(message = "Session expired") {
        super(message);
        this.name = "SessionExpiredError";
    }
}

async function call(mode, idToken) {
    const api = getApiUrl();
    if (!api) throw new Error("API URL missing");
    const res = await fetch(`${api}?mode=${mode}`, {
        headers: { Authorization: `Bearer ${idToken}` },
    });
    const text = await res.text();
    const body = text ? JSON.parse(text) : {};
    if (res.status === 401) throw new SessionExpiredError(body.error);
    if (res.status === 403 && body.access_required) throw new AccessRequiredError(body);
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
}

export const fetchDashboardEmbedUrl = (token) => call("getDashboardUrl", token);
export const fetchChatEmbedUrl = (token) => call("getChatUrl", token);
