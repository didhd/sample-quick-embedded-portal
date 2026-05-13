// APP_CONFIG is injected at deploy time via /config.js (see inject-config.sh).
// During local dev, config.js can be placed in public/ with placeholder values.
export const config = (typeof window !== "undefined" && window.APP_CONFIG) || {};

export const getApiUrl = () => config.apiUrl || "";
export const getPortalTitle = () =>
    config.portalTitle || "AnyCompany Financial — Operations Portal";
export const getCognito = () => ({
    domainUrl: config.cognitoDomainUrl,
    clientId: config.cognitoClientId,
    redirectUri: config.redirectUri,
});
export const getChatConfig = () => config.chatConfig || {};
