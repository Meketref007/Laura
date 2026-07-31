# Secure Setup

This project now exposes a structured Shopee namespace at `shopee_agent.shopee`.
The existing top-level modules remain available for compatibility, but new code
should import from the namespace package when possible.

## Required Secrets

Keep all secrets out of git. Store them in `.env` locally and rely on the
existing `secrets/` directory only for runtime-managed artifacts that are
already ignored by the repository.

Minimum required variables for Shopee integration:

- `SHOPEE_PARTNER_ID`
- `SHOPEE_PARTNER_KEY`
- `SHOPEE_REDIRECT_URL`

Optional but commonly used:

- `SHOPEE_DEFAULT_SHOP_ID`
- `SHOPEE_DEFAULT_ACCESS_TOKEN`
- `SHOPEE_DEFAULT_REFRESH_TOKEN`
- `SHOPEE_BASE_URL`

## Safe Bootstrap

```bash
cp .env.example .env
chmod 600 .env
python -m shopee_agent.cli --help
```

## Operational Notes

- Do not commit `.env`, tokens, or webhook secrets.
- Prefer the existing CLI health and diagnostic commands before enabling
  automation in production.
- Rotate access and refresh tokens together and verify webhook callbacks before
  enabling automated order flows.