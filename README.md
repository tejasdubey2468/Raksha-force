# RAKSHA-FORCE

Single-folder RAKSHA-FORCE platform merged from your frontend and backend codebases.

## Structure

```text
raksha-force/
├── index.html
├── citizen.html
├── admin.html
├── gps.js
├── supabase-client.js
├── schema.sql
├── requirements.txt
├── vercel.json
├── dev_server.py
└── api/
    ├── auth.py
    ├── dispatch.py
    ├── gps.py
    ├── incidents.py
    ├── sos.py
    ├── volunteers.py
    └── utils/
        ├── auth.py
        ├── db.py
        ├── geo.py
        ├── logger.py
        └── rate_limit.py
```

## Connected flow

- `index.html` uses the backend for auth, SOS, incident reports, and volunteer registration.
- `citizen.html` uses the backend for auth, SOS, and incident submission.
- `admin.html` uses the shared client for auth/session handling and keeps Supabase realtime for live command data.
- `supabase-client.js` is the bridge between the static frontend and Python API.
- `gps.js` now saves GPS through the backend contract.

## Deploy

1. Run `schema.sql` in Supabase SQL Editor.
2. Add Vercel environment variables:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
   - `SUPABASE_JWT_SECRET`
   - `ADMIN_REGISTRATION_SECRET`
3. Deploy this whole folder to Vercel.

## Notes

- Admin registration only works when `ADMIN_REGISTRATION_SECRET=DEMO_MODE` or a valid `X-Admin-Secret` is supplied.
- The backend now has the correct `api/` and `api/utils/` package layout expected by its imports.
- The previous aggregated dev server was intentionally replaced because it mounted already-prefixed routes incorrectly.
