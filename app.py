import os
import sys

# Load environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
ADMIN_REGISTRATION_SECRET = os.environ.get("ADMIN_REGISTRATION_SECRET", "DEMO_MODE")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_JWT_SECRET]):
    print("CRITICAL ERROR: Missing required environment variables (SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_JWT_SECRET).")
    sys.exit(1)

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Ensure 'api' is importable
sys.path.append(os.path.dirname(__file__))

# Import the apps
try:
    from api.sos import app as sos_app
    from api.incidents import app as incidents_app
    from api.dispatch import app as dispatch_app
    from api.gps import app as gps_app
    from api.auth import app as auth_app
    from api.volunteers import app as volunteers_app
except ImportError as e:
    print(f"Error importing API modules: {e}")
    sys.exit(1)

main_app = FastAPI(
    title="RAKSHA-FORCE Unified Server",
    description="Development server combining all RAKSHA-FORCE backend services and the frontend."
)

main_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@main_app.middleware("http")
async def log_requests(request: Request, call_next):
    # Normalize path: remove double slashes and trailing slashes (except for root)
    path = request.url.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    
    # Check for double slashes
    while "//" in path:
        path = path.replace("//", "/")
    
    # If path changed, we should ideally redirect, but for POST we just continue with modified scope
    if path != request.url.path:
        print(f"DEBUG: Normalizing {request.url.path} -> {path}")
        request.scope["path"] = path

    print(f"DEBUG: {request.method} {path}")
    response = await call_next(request)
    print(f"DEBUG: Response status: {response.status_code}")
    return response

# Merge routes correctly using include_router
main_app.include_router(sos_app.router)
main_app.include_router(incidents_app.router)
main_app.include_router(dispatch_app.router)
main_app.include_router(gps_app.router)
main_app.include_router(auth_app.router)
main_app.include_router(volunteers_app.router)

# Serve static files
main_app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    print("\n" + "="*50)
    print("RAKSHA-FORCE Local Server starting...")
    print("Frontend: http://127.0.0.1:5000")
    print("API Docs: http://127.0.0.1:5000/docs")
    print("Mode:     DEMO_MODE (Secret: DEMO_MODE)")
    print("Supabase: https://xjjalkcmevxqkjqcbfge.supabase.co")
    print("="*50 + "\n")
    
    uvicorn.run(main_app, host="127.0.0.1", port=5000)
