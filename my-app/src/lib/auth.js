import { getApiUrl, getCognito } from "./config.js";

const COOKIE_NAME = "openIdToken";

export function getCookie(name) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const m = document.cookie.match("(^|;) ?" + escaped + "=([^;]*)(;|$)");
    return m ? decodeURIComponent(m[2]) : null;
}

export function setCookie(name, value, maxAgeSec = 3600) {
    if (!/^[A-Za-z0-9_-]+$/.test(name)) throw new Error("invalid cookie name");
    if (/[;\r\n]/.test(value)) throw new Error("invalid cookie value");
    document.cookie = `${name}=${encodeURIComponent(
        value,
    )}; Max-Age=${maxAgeSec}; SameSite=Strict; Secure; Path=/`;
}

export function clearCookie(name) {
    document.cookie = `${name}=; Max-Age=0; SameSite=Strict; Secure; Path=/`;
}

export function getIdToken() {
    return getCookie(COOKIE_NAME);
}

export function storeIdToken(token) {
    setCookie(COOKIE_NAME, token);
}

export function clearIdToken() {
    clearCookie(COOKIE_NAME);
}

export function decodeJwtPayload(token) {
    try {
        const [, payload] = token.split(".");
        const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
        return JSON.parse(json);
    } catch {
        return null;
    }
}

export function isTokenLive(token) {
    const p = token && decodeJwtPayload(token);
    if (!p || typeof p.exp !== "number") return false;
    return Date.now() / 1000 < p.exp - 60;
}

export function redirectToLogin() {
    const { domainUrl, clientId, redirectUri } = getCognito();
    if (!domainUrl || !clientId || !redirectUri) {
        throw new Error("Cognito configuration missing");
    }
    const url =
        `${domainUrl}/oauth2/authorize?client_id=${encodeURIComponent(clientId)}` +
        `&response_type=code&scope=openid+profile&redirect_uri=${encodeURIComponent(redirectUri)}`;
    window.location.href = url;
}

export function logout() {
    clearIdToken();
    const { domainUrl, clientId, redirectUri } = getCognito();
    if (domainUrl && clientId && redirectUri) {
        window.location.href =
            `${domainUrl}/logout?client_id=${encodeURIComponent(clientId)}` +
            `&logout_uri=${encodeURIComponent(redirectUri)}`;
    } else {
        window.location.reload();
    }
}

export async function exchangeCodeForTokens(authCode) {
    const api = getApiUrl();
    if (!api) throw new Error("API URL missing");
    const res = await fetch(`${api}?code=${encodeURIComponent(authCode)}`);
    if (!res.ok) throw new Error(`token exchange HTTP ${res.status}`);
    const body = await res.json();
    if (!body.id_token) throw new Error("no id_token in response");
    return body.id_token;
}
