from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import get_settings
from app.core.rate_limit import is_rate_limited
from app.routes import (
    appeals,
    auth,
    autopilot,
    customer_refunds,
    dashboard,
    drafts,
    email,
    evidence_tasks,
    evidence,
    evidence_imports,
    followups,
    health,
    imports,
    live_evidence,
    orders,
    recovery,
    reports,
    response_reviews,
    restaurants,
    smart_import,
    uber,
    users,
    workspace,
)
from app.services.file_storage_service import ensure_evidence_storage
from app.services.gmail_inbound_auto_sync_service import GmailInboundAutoSyncScheduler
from app.services.local_storage import ensure_local_storage
from app.services.order_import_service import ensure_import_storage


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_local_storage()
    ensure_evidence_storage()
    ensure_import_storage()
    gmail_auto_sync_scheduler = GmailInboundAutoSyncScheduler()
    await gmail_auto_sync_scheduler.start()
    try:
        yield
    finally:
        await gmail_auto_sync_scheduler.stop()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    debug=settings.debug,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def production_hardening_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    if is_rate_limited(request):
        response = JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
        )
    else:
        response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.runtime_environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
def password_recovery_page() -> str:
    return """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TENNET — Récupération</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#07090d;color:#f6f7f9;font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}.card{width:min(520px,100%);background:#10141b;border:1px solid #232a35;border-radius:22px;padding:30px;box-shadow:0 24px 70px #0008}.brand{font-weight:900;letter-spacing:.14em;font-size:24px;margin-bottom:28px}.brand span{opacity:.55}h1{font-size:30px;margin:0 0 8px}p{color:#9aa5b4;line-height:1.55;margin:0 0 24px}.field{margin:16px 0}label{display:block;font-size:13px;font-weight:700;margin-bottom:8px}input{width:100%;border:1px solid #303846;background:#0b0e13;color:#fff;border-radius:12px;padding:14px 15px;font:inherit;outline:none}input:focus{border-color:#eef2f7}button{width:100%;border:0;border-radius:12px;background:#f4f5f7;color:#090b0f;padding:14px 16px;font-weight:900;font-size:15px;cursor:pointer;margin-top:10px}button:disabled{opacity:.55;cursor:wait}.msg{margin-top:18px;padding:13px;border-radius:11px;background:#171d26;color:#dce3ec;display:none}.bad{border:1px solid #733}.good{border:1px solid #365}.back{display:block;text-align:center;color:#aab4c1;text-decoration:none;margin-top:18px;font-size:14px}
</style>
</head>
<body>
<main class="card">
<div class="brand">TENNET <span>RECOVERY</span></div>
<div id="requestBox">
<h1>Récupérer l’accès</h1>
<p>Un lien sécurisé à usage unique sera envoyé à l’adresse owner TENNET.</p>
<form id="requestForm"><div class="field"><label for="email">Email owner</label><input id="email" type="email" autocomplete="email" required></div><button id="requestBtn" type="submit">Envoyer le lien sécurisé</button></form>
</div>
<div id="confirmBox" hidden>
<h1>Nouveau mot de passe</h1>
<p>Choisissez votre nouveau mot de passe. Le lien expire après 30 minutes et ne peut être utilisé qu’une fois.</p>
<form id="confirmForm"><div class="field"><label for="password">Nouveau mot de passe</label><input id="password" type="password" autocomplete="new-password" minlength="12" required></div><div class="field"><label for="password2">Confirmer</label><input id="password2" type="password" autocomplete="new-password" minlength="12" required></div><button id="confirmBtn" type="submit">Réinitialiser le mot de passe</button></form>
</div>
<div id="msg" class="msg"></div><a class="back" href="/login">Retour à la connexion</a>
</main>
<script>
const q=new URLSearchParams(location.search),token=q.get('token'),requestBox=document.getElementById('requestBox'),confirmBox=document.getElementById('confirmBox'),msg=document.getElementById('msg');
function show(t,ok){msg.textContent=t;msg.className='msg '+(ok?'good':'bad');msg.style.display='block'}
if(token){requestBox.hidden=true;confirmBox.hidden=false}
document.getElementById('requestForm').addEventListener('submit',async e=>{e.preventDefault();const b=document.getElementById('requestBtn');b.disabled=true;msg.style.display='none';try{const r=await fetch('/api/v1/auth/password-reset/request',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value.trim()})});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Impossible d’envoyer le lien.');show('Lien envoyé. Vérifiez votre boîte e-mail.',true)}catch(err){show(err.message||'Erreur de récupération.',false)}finally{b.disabled=false}});
document.getElementById('confirmForm').addEventListener('submit',async e=>{e.preventDefault();const b=document.getElementById('confirmBtn'),p=document.getElementById('password').value,p2=document.getElementById('password2').value;if(p.length<12){show('Le mot de passe doit contenir au moins 12 caractères.',false);return}if(p!==p2){show('Les deux mots de passe ne correspondent pas.',false);return}b.disabled=true;msg.style.display='none';try{const r=await fetch('/api/v1/auth/password-reset/confirm',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({token,password:p})});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Réinitialisation impossible.');show('Mot de passe réinitialisé. Redirection vers la connexion…',true);setTimeout(()=>location.href='/login',900)}catch(err){show(err.message||'Réinitialisation impossible.',false)}finally{b.disabled=false}});
</script>
</body></html>"""


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(appeals.router)
app.include_router(autopilot.router)
app.include_router(customer_refunds.router)
app.include_router(customer_refunds.reviews_router)
app.include_router(restaurants.router)
app.include_router(orders.router)
app.include_router(recovery.router)
app.include_router(reports.router)
app.include_router(evidence.router)
app.include_router(evidence_imports.router)
app.include_router(evidence_tasks.router)
app.include_router(drafts.router)
app.include_router(email.router)
app.include_router(followups.router)
app.include_router(imports.router)
app.include_router(live_evidence.router)
app.include_router(dashboard.router)
app.include_router(response_reviews.router)
app.include_router(users.router)
app.include_router(smart_import.router)
app.include_router(uber.router)
app.include_router(workspace.router)
