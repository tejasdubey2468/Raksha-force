import os
import sys
from dotenv import load_dotenv

# Load .env before everything else
load_dotenv()

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_JWT_SECRET  = os.environ.get("SUPABASE_JWT_SECRET", "")
ADMIN_REGISTRATION_SECRET = os.environ.get("ADMIN_REGISTRATION_SECRET", "DEMO_MODE")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    print("CRITICAL ERROR: Missing required environment variables (SUPABASE_URL, SUPABASE_SERVICE_KEY).")
    sys.exit(1)

# Ensure the project root is on sys.path so 'api' is importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Import the API sub-apps
try:
    from api.sos       import app as sos_app
    from api.incidents import app as incidents_app
    from api.dispatch  import app as dispatch_app
    from api.gps       import app as gps_app
    from api.auth      import app as auth_app
    from api.volunteers import app as volunteers_app
except ImportError as e:
    print(f"Error importing API modules: {e}")
    sys.exit(1)

main_app = FastAPI(
    title="RAKSHA-FORCE Unified Server",
    description="Local development server combining all RAKSHA-FORCE backend services and the frontend."
)

main_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@main_app.middleware("http")
async def normalize_paths(request: Request, call_next):
    """Normalize double-slashes and trailing slashes in URL paths."""
    path = request.url.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    while "//" in path:
        path = path.replace("//", "/")
    if path != request.url.path:
        request.scope["path"] = path

    response = await call_next(request)
    return response


# Mount API routers
main_app.include_router(auth_app.router)
main_app.include_router(sos_app.router)
main_app.include_router(incidents_app.router)
main_app.include_router(dispatch_app.router)
main_app.include_router(gps_app.router)
main_app.include_router(volunteers_app.router)

# Serve all static HTML/CSS/JS from the project root
main_app.mount("/", StaticFiles(directory=os.path.dirname(os.path.abspath(__file__)), html=True), name="static")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print("\n" + "=" * 55)
    print("  RAKSHA-FORCE Local Server")
    print(f"  Frontend : http://127.0.0.1:{port}")
    print(f"  API Docs : http://127.0.0.1:{port}/docs")
    print(f"  Supabase : {SUPABASE_URL}")
    print("=" * 55 + "\n")
    uvicorn.run(main_app, host="127.0.0.1", port=port)
