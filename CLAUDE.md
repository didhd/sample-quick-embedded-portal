# CLAUDE.md — engineering notes for AI agents and contributors

This file is the *engineering counterpart* to `README.md`. README is for someone deploying or using the portal; CLAUDE.md is for the next person (human or AI agent) who has to **change the code** without breaking it.

It captures: how the codebase is laid out, the design tradeoffs that don't show up in the diff, the AWS-side gotchas we already paid for, and the dev workflows that actually work versus the ones that look right but fail.

---

## 1. Repository layout

```
clearone-quick-demo/
├── my-app/                 React 18 + Vite + Tailwind SPA (the only frontend)
│   ├── index.html          Loads the QS Embedding SDK + window.APP_CONFIG
│   ├── public/config.js    Placeholder; replaced at deploy by inject-config.sh
│   ├── src/
│   │   ├── main.jsx        ReactDOM.createRoot — no StrictMode (see §5)
│   │   ├── App.jsx         Auth state machine + layout
│   │   ├── components/
│   │   │   ├── Header.jsx        Brand bar + Chat Agents toggle + Sign out
│   │   │   ├── Dashboard.jsx     embedDashboard, loads exactly once per token
│   │   │   ├── ChatSidebar.jsx   Sliding drawer + embedQuickChat + reload
│   │   │   └── Panel.jsx         Loading / Error / Empty cells
│   │   └── lib/
│   │       ├── config.js         Reads window.APP_CONFIG
│   │       ├── auth.js           Cookie + JWT helpers, redirectToLogin, exchangeCodeForTokens
│   │       ├── api.js            Typed wrappers around the Lambda; AccessRequiredError, SessionExpiredError
│   │       └── embedding.js      createEmbeddingContext (memoised), mountDashboard, mountChat
│   ├── tailwind.config.js  Custom palette: brand (AWS orange), squidInk, ink scale
│   ├── postcss.config.js
│   └── vite.config.js
│
├── lambda/
│   ├── embed_oidc_federation.py  Single handler; routes by ?mode=getDashboardUrl|getChatUrl|?code=
│   └── requirements.txt          boto3, requests, PyJWT, cryptography
│
├── webapp/                 AWS CDK v2 (TypeScript)
│   ├── bin/webapp.ts       App entrypoint; pulls CDK_DEFAULT_REGION/_ACCOUNT
│   └── lib/webapp-stack.ts Single stack: Cognito, OIDC, IAM, Lambda, API GW, WAF,
│                           CloudFront, S3, BucketDeployment from ../my-app/dist
│
├── data/
│   ├── generate_clearone_data.py  Synthetic CSV generator (deterministic, seed=42)
│   ├── manifests/                 QS S3 manifest JSONs, one per CSV
│   ├── qs-s3-policy.json          Replacement for AWSQuickSightS3Policy
│   ├── create_datasets.py         Creates 5 SPICE datasets via boto3 with cast operations
│   └── create_dashboard.py        Builds analysis+dashboard from a Definition object
│
├── scripts/                Cognito / Quick Suite user management (Python, boto3)
│   ├── create_cognito_user.py
│   ├── delete_cognito_user.py
│   ├── create_quicksuite_user.py
│   └── delete_quicksuite_user.py
│
├── frontend/               LEGACY (vanilla JS); kept around for reference but
│                           not deployed since the React app exists.
│
├── inject-config.sh        Writes my-app/dist/config.js from cdk-outputs.json
├── setup.sh                End-to-end deploy script (interactive prompts)
├── cleanup.sh              Inverse of setup.sh
├── security-check.sh       cdk-nag wrapper invoked by setup.sh
├── README.md               User-facing docs
└── CLAUDE.md               (this file)
```

The legacy `frontend/` directory is **not** deployed by the current CDK stack. The stack's `BucketDeployment` was repointed to `../my-app/dist`. Before you delete `frontend/`, verify nothing else references it; it's a useful reference for the older vanilla-JS-only flow.

---

## 2. The full request lifecycle

### 2.1 First page load

1. User opens `https://<cf-domain>/`.
2. CloudFront serves `index.html` from S3. The HTML preloads + defers the Quick Suite Embedding SDK from unpkg, then loads `config.js` (sync) so `window.APP_CONFIG` is populated before React mounts.
3. `App.jsx` checks `URLSearchParams` for `?code=` and `document.cookie` for `openIdToken`.
   - If neither: builds the Cognito hosted-login URL and `window.location = ...`.
   - If `?code=`: POSTs `code` to the Lambda (which exchanges it server-side using the Cognito client secret-less `authorization_code` flow), gets `id_token`, stores in cookie, replaces history state.
   - If `openIdToken` exists and isn't expired (we check `exp - 60s` locally): authenticated.
4. Once authenticated, `Dashboard.jsx`'s effect runs **once per id_token** (guarded by `loadedForTokenRef`). It calls `getDashboardUrl` and mounts via `embedDashboard`.

### 2.2 Opening Chat Agents

1. User clicks `Header → Chat Agents`. `App.jsx` sets `chatOpen = true`.
2. `ChatSidebar`'s effect fires: if no live experience or its mount age is older than 4 minutes, it unmounts the previous one, calls `getChatUrl`, then `embedQuickChat` with `{ agentOptions: { fixedAgentId } }`.
3. The reveal trigger is the *first* of `FRAME_MOUNTED` or `FRAME_LOADED`. We don't wait for `FRAME_LOADED` alone because it can lag visibly behind mount.
4. The ↻ icon increments `reloadKey`, which forces a fresh fetch + mount.

### 2.3 Lambda routing (`embed_oidc_federation.py`)

```
GET /prod/embed-sample?code=<auth-code>            → handle_auth_code_callback
GET /prod/embed-sample?mode=getDashboardUrl        → handle_embed_request("dashboard")
GET /prod/embed-sample?mode=getChatUrl             → handle_embed_request("chat")
OPTIONS                                            → CORS pre-flight
```

Both `handle_embed_request` modes share: JWT verification, web-identity role assumption, federated-user lookup, embed-URL generation. They diverge at `ExperienceConfiguration`:

- Dashboard: `{"Dashboard": {"InitialDashboardId": dashboard_id, "FeatureConfigurations": {...}}}`
- Chat: `{"QuickChat": {}}`. The `boto3` schema for `QuickChat` is currently an empty dict — there is **no** `InitialAgentId` field yet. That's why we layer two pre-selection mechanisms:
  1. Lambda appends `&agentId=<uuid>` as a query parameter to the embed URL (best-effort).
  2. The frontend's `embedQuickChat` `contentOptions.agentOptions.fixedAgentId` does the actual UI lock.

### 2.4 Federated user identity

Each Cognito user has a corresponding Quick Suite user whose `UserName` is `<role-name>/<email-local-part>`. The Lambda enforces this exact format:

```
expected_quicksight_username = f"{web_identity_role_name}/{email.split('@')[0]}"
```

It paginates through `list_users` and matches by `UserName == expected` AND `Email == claimed`. If you change the role name or the way `create_quicksuite_user.py` constructs `SessionName`, you must update both sides.

---

## 3. CDK stack (`webapp/lib/webapp-stack.ts`)

The stack is one file because it's a demo. If you split it later, keep these constraints:

- **Same region** for everything except CloudFront (which is global). The Lambda relies on `AWS_REGION` matching where Cognito and Quick Suite live.
- **`CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION` must be set in env**. `bin/webapp.ts` throws otherwise.
- The web-identity role's IAM policy lists Quick Suite ARNs across **four regions**: `us-east-1`, `us-west-2`, `ap-southeast-2`, `eu-west-1`. These are the four current QS embedded-experience regions. If AWS adds more, extend both `webIdentityRole.inlinePolicies` and the matching `NagSuppressions.appliesTo` entries — otherwise `cdk-nag` will fail the synth with `AwsSolutions-IAM5`.
- The Cognito User Pool has `selfSignUpEnabled: false`. Admins create users via `scripts/create_cognito_user.py`.
- `BucketDeployment` source is `'../my-app/dist'`. **Always run `npm run build` before `cdk deploy`**, otherwise CDK uploads stale assets.
- Lambda is bundled in Docker (or Finch via the shim, see README). The bundling command is:
  ```
  pip install -r requirements.txt -t /asset-output && cp -au embed_oidc_federation.py /asset-output
  ```
  We exclude `build/` and `__pycache__` to keep the asset hash stable.
- `cdk-nag` is wired up in `bin/webapp.ts` (`AwsSolutionsChecks`). Most expected suppressions live next to the resource that triggers them. New suppressions should always include a human-readable `reason`.

### 3.1 Context flags worth knowing

| Context | Used by | Notes |
| --- | --- | --- |
| `portalTitle` | Lambda env, `CfnOutput.PortalTitle`, `inject-config.sh` | Avoid em-dashes here; CDK + cdk-outputs.json sometimes mangle non-ASCII into `?`. Use a hyphen. |
| `stackName` | Resource prefix; must be ≤ 12 chars |
| `quicksightIdentityRegion` | Lambda env `QUICKSIGHT_IDENTITY_REGION` |
| `dashboardId` | Lambda env `DASHBOARD_ID` |
| `chatAgentId` | Lambda env `CHAT_AGENT_ID` (Lambda appends `&agentId=...` to chat URLs) |

---

## 4. Quick Suite gotchas we already paid for

These are the things that ate hours during initial development. They are easy to re-introduce.

### 4.1 SPICE capacity

A fresh Quick Suite account has **0 GB** SPICE. Calling `CreateDataSet --import-mode SPICE` fails with `LimitExceededException: Insufficient SPICE capacity`. Fix:

```bash
aws quicksight update-spice-capacity-configuration --purchase-mode AUTO_PURCHASE
```

### 4.2 S3 physical tables emit `STRING` only

`CreateDataSet` rejects any `InputColumns` typed as `INTEGER`/`DECIMAL`/`DATETIME` for an `S3Source` physical table. Pattern: declare all input columns as `STRING`, then add a `LogicalTableMap` with `CastColumnTypeOperation` transforms. See `data/create_datasets.py`. The API also requires **at least one** transform per logical table — we fall back to a no-op `ProjectOperation` if no casts are needed.

### 4.3 KPI visuals can't have advanced display options without TrendGroup

`InvalidParameterValueException: Only PrimaryValueFontSize display property can be defined when TargetValue and TrendGroup fields are empty`. We dropped `KPIOptions` entirely on plain KPIs. If you want sparklines, you must add a `TrendGroup` (a date dimension) to the field wells.

### 4.4 BarChart sort options changed name

`SortConfiguration.CategoryItemsLimitConfiguration` → `CategoryItemsLimit`. The official AWS docs still show the older name in places; trust the boto3 service model.

### 4.5 String columns must use `CategoricalMeasureField`

You can't put a `client_id` (STRING) inside a `NumericalMeasureField` even with `aggregation=COUNT`. Use `CategoricalMeasureField` with `AggregationFunction='COUNT'` for STRING columns. `data/create_dashboard.py` keeps a curated set of `_STRING_COUNT_COLS` to dispatch correctly.

### 4.6 READER_PRO can't be granted dataset permissions

`UpdateDataSetPermissions` rejects READER_PRO principals: `roles less privileged than AUTHOR`. We don't need this — sharing the dashboard is enough for embedded users to query through it. If you do need direct dataset access (for Q topics, e.g.), the user must be AUTHOR or above.

### 4.7 Identity region vs embed region

The QS account lives in exactly one identity region (`describe-account-subscription` tells you). Calling `list-users` from a different region's endpoint fails with `Operation is being called from endpoint X, but your identity region is Y`. The Lambda creates two `quicksight` clients: one for identity (`qs_identity`, used for `list_users`) and one for embed (`qs_embed`, used for `generate_embed_url_for_registered_user`). Today they use the same region; the split is there for future flexibility.

### 4.8 `delete-account-subscription` is global and irreversible

It deletes every QS asset in **every** region for that account. The CLI requires `--region`, but the operation isn't scoped by region. Termination protection must be off first. Don't run this casually.

### 4.9 QuickChat session weirdness

If `embedQuickChat` is called but the user has no chat agents shared (or hasn't had any agent open in this account before), the iframe shows either an empty agent-builder ("Build chat agents with unique personas…") or "Your session has expired. Please refresh." This isn't a real session expiry — it's the QuickChat UI's catch-all when there's nothing to render. Two fixes:
  - Share at least one agent with the federated user.
  - Pass `agentOptions.fixedAgentId` so the SDK opens directly on that agent.

### 4.10 SDK option `fixedAgentId` (not `agentId`)

The Embedding SDK option that locks the chat dropdown to a specific agent is `contentOptions.agentOptions.fixedAgentId`. Passing `agentId` does nothing.

---

## 5. Frontend gotchas

### 5.1 No StrictMode

`React.StrictMode` double-invokes effects in dev. With `Dashboard.jsx`'s "fetch + mount" effect, that meant two `embedDashboard` calls in quick succession against a single-use embed URL — the second one fails. We removed `StrictMode` from `main.jsx`. If you re-enable it, you also need to make the dashboard mount idempotent (the current `loadedForTokenRef` guard handles re-renders but not StrictMode's double-effect specifically).

### 5.2 Dashboard must not re-mount when ChatSidebar opens

`useAuth`'s `onSessionExpired` was being recreated every render, which made it a *new* dependency value for `Dashboard`'s effect, causing a re-mount whenever any `App` state changed (e.g. `chatOpen` toggling). Two-layer fix:
1. `useAuth` wraps `onSessionExpired` in `useCallback([])` so its identity is stable.
2. `Dashboard` adds `loadedForTokenRef` so it loads exactly once per `idToken`. On error it nulls the ref to allow retry.

If you ever see the dashboard re-loading every time the chat panel toggles, suspect a new dependency identity in the props chain.

### 5.3 `initialPrompt` auto-fires

`contentOptions.promptOptions.initialPrompt` is sent as the **first user message** by QuickChat — not displayed as placeholder text. Setting it auto-asks the agent and the user sees an unwanted exchange before they've typed anything. We removed it. If you want a visible placeholder, use the QS console's agent settings instead.

### 5.4 Embed URL freshness window

QS embed URLs must be redeemed within 5 minutes of generation. `ChatSidebar` re-fetches if the local mount age exceeds 4 minutes. The Dashboard panel doesn't re-fetch on its own; if it goes stale (e.g. tab left open for hours), an error in any subsequent operation will route through `onSessionExpired` and trigger a re-login.

### 5.5 SDK pin

We pin `amazon-quicksight-embedding-sdk@2.11.3` (pinned in `package.json`, the `<script>` tag, and the `<link rel="preload">` tag). Bumping requires updating all three places. We deliberately don't ship an SRI hash because we re-pin frequently; if you stabilise the version, regenerate the integrity hash and add it back.

---

## 6. Build / deploy commands at a glance

```bash
# React only
cd my-app && npm run build && cd ..
./inject-config.sh
aws s3 sync my-app/dist/ s3://<frontend-bucket>/ --region us-west-2 \
    --exclude "access-logs/*" --delete
aws cloudfront create-invalidation --distribution-id <DIST_ID> --paths "/*"

# Lambda + infra
rm -rf lambda/__pycache__   # avoid stale cache landing in the asset
cd webapp && cdk deploy clearone --context ... --outputs-file cdk-outputs.json && cd ..

# Reset
cd webapp && cdk destroy clearone && cd ..
```

`--exclude "access-logs/*"` matters: the CloudFront logs bucket and the frontend bucket share a prefix when deployed via the same `BucketDeployment`, and a naive `--delete` would wipe live access logs.

---

## 7. Secrets, secrets, secrets

There aren't many.

- **No long-lived AWS credentials** are present in the browser. The Cognito ID token is short-lived (1h refresh, 1h access). The Lambda assumes a web-identity role with 1h sessions.
- **No client secret on the Cognito client** (we use the public OAuth code flow with a single-page app). If you ever switch to a confidential client, you must move the token exchange to the Lambda *and* never expose the secret in `config.js`.
- **`config.js` is public** — it contains the Cognito client ID, the Cognito domain, the API GW URL, and the CloudFront URL. None of these are secrets.
- The Lambda log group retains for 1 week (`logs.RetentionDays.ONE_WEEK`). It logs JWT-validation failures and embed-URL generation events at INFO level (host + path only — never the embed URL with its KMS-wrapped `code` query param).

---

## 8. Working with this repo as an AI agent

- Default region is **us-west-2**. Never assume `us-east-1`.
- Don't run `delete-account-subscription` for any reason without an explicit, current-message confirmation from the user. It's globally destructive.
- Termination protection on Quick Suite must be off before destructive QS operations. Always re-enable it after.
- For any deploy that touches CloudFront (bucket contents change), an explicit `cloudfront create-invalidation` is required for the user to see the change immediately. CDK does this for `BucketDeployment.distributionPaths: ['/*']`, but if you `aws s3 sync` directly, you must invalidate by hand.
- When the user says "Cmd+Shift+R" they mean: their browser still has the old bundle cached. Look at `assets/index-<hash>.js` — if the hash has changed since the last `npm run build`, you've shipped successfully and the user just needs to bypass cache.
- Don't introduce new top-level files (especially Markdown) without an explicit request. README and CLAUDE.md exist; keep new info in them.
- When troubleshooting, prefer to look at:
  1. `aws logs tail /aws/lambda/clearone-quickchat-embed-function`
  2. The browser DevTools Network tab for the `?mode=...` call's response body
  3. `aws quicksight describe-dashboard` / `describe-user` for permission state
- Don't add `console.log` in committed code. The app already routes errors through the Panel components with actionable messages.

---

## 9. Roadmap-shaped TODOs

These are intentional gaps, not bugs.

- [ ] Production-grade auth: enforce MFA on Cognito and rotate refresh tokens.
- [ ] Custom domain + ACM cert in front of CloudFront.
- [ ] Per-user RLS on the dashboard datasets (currently all federated users see all rows).
- [ ] Replace synthetic data with a Glue/Athena pipeline reading real CRM exports.
- [ ] Move the legacy `frontend/` and `setup.sh` interactive flow out of the repo (they're vestigial; the React app + manual `cdk deploy` is canonical).
- [ ] Bake `chatAgentId` into a Quick Suite "default agent" attribute on the federated user, once that API exists, so we can drop the SDK-side `fixedAgentId` workaround.
