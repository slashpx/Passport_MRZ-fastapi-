# Zuplo Setup Guide — elMRZ API Gateway

## 1. Create a Zuplo Project

1. Go to https://zuplo.com and log in
2. Click **New Project** → choose **"Start from scratch"**
3. Name it: `elmrz-api`

---

## 2. Set Environment Variables

Go to **Settings → Environment Variables** (or the lock icon in the left sidebar):

| Variable | Value | Secret? |
|---|---|---|
| `BACKEND_BASE_URL` | `https://myqd2iza11.execute-api.eu-north-1.amazonaws.com/prod` | No |
| `AWS_API_KEY` | `Te4pSwwsTW4jVGeqYOJz67N1OgIqcw9M4GBi3jD3` | ✅ Yes |
| `BACKEND_SECRET` | *(generate — see below)* | ✅ Yes |

Generate a backend secret:
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

---

## 3. Create Routes

Go to the **Routes** tab (Code > routes.oas.json). You can either:
- **Import**: Click the `⋮` menu → Import OpenAPI → paste contents of `routes.oas.json`
- **Manual**: Create each route by hand (see below)

### Route 1: Health Check
- **Method**: `GET`
- **Path**: `/health`
- **Handler**: URL Forward → Base URL: `$env(BACKEND_BASE_URL)`
- **Inbound Policies**: `add-aws-api-key-inbound` only (no auth needed)

### Route 2: MRZ Process (multipart)
- **Method**: `POST`
- **Path**: `/api/mrz/process`
- **Handler**: URL Forward → Base URL: `$env(BACKEND_BASE_URL)`
- **Inbound Policies** (in this order):
  1. `api-key-inbound`
  2. `rate-limit-inbound`
  3. `add-aws-api-key-inbound`
  4. `add-backend-secret-inbound`

### Route 3: MRZ Process (base64)
- **Method**: `POST`
- **Path**: `/api/mrz/process-base64`
- **Handler**: URL Forward → Base URL: `$env(BACKEND_BASE_URL)`
- **Inbound Policies**: Same as Route 2

---

## 4. Set Up Policies (Step by Step)

Go to **Code → policies.json** in the left sidebar file tree.

Your `policies.json` should look like this (paste this entire thing):

```json
{
  "policies": [
    {
      "handler": {
        "export": "ApiKeyInboundPolicy",
        "module": "$import(@zuplo/runtime)",
        "options": {
          "allowUnauthenticatedRequests": false,
          "cacheTtlSeconds": 60
        }
      },
      "name": "api-key-inbound",
      "policyType": "api-key-inbound"
    },
    {
      "handler": {
        "export": "RateLimitInboundPolicy",
        "module": "$import(@zuplo/runtime)",
        "options": {
          "rateLimitBy": "user",
          "requestsAllowed": 10000,
          "timeWindowMinutes": 1440
        }
      },
      "name": "rate-limit-inbound",
      "policyType": "rate-limit-inbound"
    },
    {
      "handler": {
        "export": "SetHeadersInboundPolicy",
        "module": "$import(@zuplo/runtime)",
        "options": {
          "headers": [
            {
              "name": "x-api-key",
              "value": "$env(AWS_API_KEY)",
              "overwrite": true
            }
          ]
        }
      },
      "name": "add-aws-api-key-inbound",
      "policyType": "set-headers-inbound"
    },
    {
      "handler": {
        "export": "SetHeadersInboundPolicy",
        "module": "$import(@zuplo/runtime)",
        "options": {
          "headers": [
            {
              "name": "x-backend-secret",
              "value": "$env(BACKEND_SECRET)",
              "overwrite": true
            }
          ]
        }
      },
      "name": "add-backend-secret-inbound",
      "policyType": "set-headers-inbound"
    }
  ]
}
```

### What each policy does:

| Policy | Purpose |
|---|---|
| `api-key-inbound` | ✅ You already have this. Requires customers to send `Authorization: Bearer <key>` |
| `rate-limit-inbound` | ✅ You already have this. **Changed**: `rateLimitBy` should be `"user"` (not `"ip"`) so limits are per API key. Set 10,000 requests per 1,440 minutes (1 day) to allow for load testing and scaling |
| `add-aws-api-key-inbound` | 🆕 **You need this.** Injects `x-api-key: <your AWS key>` on every outbound request so your AWS API Gateway accepts it |
| `add-backend-secret-inbound` | 🆕 **You need this.** Injects `x-backend-secret` so the backend knows the request came through Zuplo |

---

## 5. Create API Consumers (Step by Step)

This is how customers get their API keys.

### Via Dashboard (Manual — for testing):

1. In the left sidebar, click **Services → API Key Consumers** (the people icon)
2. Click **"+ Add Consumer"**
3. Fill in:
   - **Name**: `test-customer` (or an email like `demo@example.com`)
   - **Description**: `Demo customer for testing`
4. Click **Create**
5. The system auto-generates an API key. Click the **eye icon** to reveal it
6. **Copy the key** — this is what the customer uses in `Authorization: Bearer <key>`

### To add more consumers:
Repeat step 2-6 for each new customer. Each consumer gets their own key and their own rate limit counter.

### Test the consumer key:

```bash
# Replace with YOUR Zuplo URL and the consumer's API key
curl -X POST https://elmrz-api-main-xxxxxxxx.zuplo.app/api/mrz/process \
  -H "Authorization: Bearer <consumer-api-key>" \
  -F "image=@test_passport.jpg"
```

### Via Zuplo API (Programmatic — for production):

If you want to auto-create consumers after PayPal payment:

```bash
# 1. Get your Zuplo API token from: Settings → Zuplo API Keys
ZUPLO_TOKEN="YOUR_ZUPLO_TOKEN"

# 2. Create a consumer
curl -X POST "https://dev.zuplo.com/v1/projects/<project-name>/env/production/consumers" \
  -H "Authorization: Bearer $ZUPLO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "customer@email.com",
    "description": "Starter plan customer",
    "tags": { "plan": "starter" }
  }'

# Response will include the auto-generated API key
```

---

## 6. Attach Policies to Routes

After creating policies, you must attach them to routes.

In your `routes.oas.json`, each route has a `policies` section. Make sure each MRZ route has:

```json
"policies": {
  "inbound": [
    "api-key-inbound",
    "rate-limit-inbound",
    "add-aws-api-key-inbound",
    "add-backend-secret-inbound"
  ]
}
```

**The order matters.** Policies run top to bottom:
1. First checks the API key ← rejects if invalid
2. Then checks rate limit ← rejects if exceeded  
3. Then adds the AWS x-api-key header
4. Then adds the backend-secret header
5. Finally forwards to your AWS backend

---

## 7. Your Zuplo Gateway URL

After saving, your URL is shown at the top of the dashboard:
```
https://elmrz-api-main-xxxxxxxx.zuplo.app
```

Update the frontend's `BACKEND_URL` in `frontend/app.js` with this URL.

---

## 8. Test It

```bash
# 1. Health check (no API key needed)
curl https://your-zuplo-url.zuplo.app/health

# 2. MRZ scan (requires consumer API key)
curl -X POST https://your-zuplo-url.zuplo.app/api/mrz/process \
  -H "Authorization: Bearer <consumer-api-key-from-step-5>" \
  -F "image=@passport.jpg"

# 3. Should return 401 without key
curl -X POST https://your-zuplo-url.zuplo.app/api/mrz/process \
  -F "image=@passport.jpg"
# Expected: {"status":401,"title":"Unauthorized"}
```

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `401 Unauthorized` | Consumer API key is missing or wrong. Check `Authorization: Bearer <key>` header |
| `403 Forbidden` from backend | `BACKEND_SECRET` env var doesn't match between Zuplo and your ECS task |
| `Missing Authentication Token` from AWS | `add-aws-api-key-inbound` policy is not attached to the route, or `AWS_API_KEY` env var is not set |
| `429 Too Many Requests` | Rate limit hit. Increase `requestsAllowed` or wait for window to reset |
| Policies not showing in route editor | Make sure `policies.json` is saved. Then go back to the route and add them from the dropdown |
