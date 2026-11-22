"""Tests de bout en bout d'ESSE Fleet. Données entièrement fictives ; aucune requête réseau (OpenAI simulé).

Lancer : pytest -q
"""
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["ESSE_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.sqlite3")
os.environ["OPENAI_API_KEY"] = ""  # jamais de vraie clé dans les tests
os.environ["AUTH_RATE_LIMIT_PER_MIN"] = "1000"  # les tests créent de nombreux comptes depuis la même IP
os.environ["RATE_LIMIT_PER_MIN"] = "100000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

TD = date.today().isoformat()
PASSWORD = "mot-de-passe-test-1"


def payload(email, vehicles=True):
    return {
        "email": email, "password": PASSWORD, "first_name": "Test", "last_name": "PROPRIETAIRE",
        "phone": "060000000", "city": "Pointe-Noire", "account_type": "particulier", "role": None, "company": None,
        "fleet": {"vehicle_count": 2, "operation": "Les deux", "acquisition": "Comptant"},
        "vehicles": [
            {"brand": "Toyota", "model": "Corolla", "year": 2013, "plate": "xx 100 aa", "driver_name": "Chauffeur Un", "avg_daily_revenue": 25000},
            {"brand": "Hyundai", "model": None, "year": None, "plate": None, "driver_name": None, "avg_daily_revenue": 20000},
        ] if vehicles else [],
        "goals": {"types": ["revenu"], "monthly_revenue": 1000000},
    }


@pytest.fixture(scope="module")
def c():
    return TestClient(main.app)


def signup(c, email, vehicles=True):
    r = c.post("/api/auth/register", json=payload(email, vehicles))
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_comptes_et_sessions(c):
    reg = payload("comptes@example.com")
    r = c.post("/api/auth/register", json=reg)
    assert r.status_code == 200 and r.json()["access_token"]
    assert c.post("/api/auth/register", json=reg).status_code == 409
    assert c.post("/api/auth/register", json={**reg, "email": "pas-un-email"}).status_code == 422
    assert c.post("/api/auth/register", json={**reg, "email": "court@example.com", "password": "abc"}).status_code == 422
    assert c.post("/api/auth/login", json={"email": "comptes@example.com", "password": "faux"}).status_code == 401
    tok = c.post("/api/auth/login", json={"email": "COMPTES@example.com", "password": PASSWORD}).json()["access_token"]
    H = {"Authorization": "Bearer " + tok}
    assert c.get("/api/auth/me", headers=H).json()["email"] == "comptes@example.com"
    assert c.get("/api/bootstrap").status_code == 401
    assert c.get("/api/bootstrap", headers={"Authorization": "Bearer " + "z" * 30}).status_code == 401
    assert c.post("/api/auth/logout", headers=H).status_code == 200
    assert c.get("/api/auth/me", headers=H).status_code == 401
    # session expirée
    H = signup(c, "expire@example.com", vehicles=False)
    with main.db(write=True) as db:
        db.execute("UPDATE sessions SET expires_at=1")
    assert c.get("/api/auth/me", headers=H).status_code == 401


def test_flotte_recettes_depenses(c):
    H = signup(c, "flotte@example.com")
    b = c.get("/api/bootstrap", headers=H).json()
    assert b["role"] == "proprietaire" and b["profile"]["company"] == "Test PROPRIETAIRE"
    v1, v2 = b["vehicles"]
    assert v1["plate"] == "XX 100 AA" and v1["driver"] == "Chauffeur Un" and v2["driver"] == "Test PROPRIETAIRE"

    ok = lambda r: r.status_code == 200  # noqa: E731
    assert ok(c.post("/api/logs/entry", headers=H, json={"vehicle_id": v1["id"], "date": TD, "kind": "revenue", "amount": 22000}))
    assert ok(c.post("/api/logs/entry", headers=H, json={"vehicle_id": v1["id"], "date": TD, "kind": "expense", "amount": 2000, "motif": "Panne"}))
    r = c.put("/api/logs", headers=H, json={"vehicle_id": v1["id"], "date": TD, "status": "Exploité", "revenue": 24000, "other_expenses": 3000, "motif": "Entretien"})
    assert r.json()["revenue"] == 24000 and r.json()["other_expenses"] == 3000
    assert ok(c.post("/api/logs/bulk", headers=H, json={"date": TD, "items": [{"vehicle_id": v2["id"], "rest": True}]}))
    b = c.get("/api/bootstrap", headers=H).json()
    assert len(b["logs"]) == 2
    assert b["expenses"] == [{"date": TD, "vehicle_id": v1["id"], "amount": 3000, "motif": "Entretien"}]

    # validations financières
    bad = {"vehicle_id": v1["id"], "date": TD}
    assert c.post("/api/logs/entry", headers=H, json={**bad, "kind": "revenue", "amount": -5}).status_code == 422
    assert c.post("/api/logs/entry", headers=H, json={**bad, "kind": "revenue", "amount": 0}).status_code == 422
    assert c.post("/api/logs/entry", headers=H, json={**bad, "kind": "revenue", "amount": 2e9}).status_code == 422
    assert c.post("/api/logs/entry", headers=H, json={**bad, "kind": "revenue", "amount": 1e9}).status_code == 422  # 24 000 déjà saisis
    assert c.post("/api/logs/entry", headers=H, json={**bad, "kind": "revenue", "amount": 1e9 - 24000}).status_code == 200
    assert c.post("/api/logs/entry", headers=H, json={**bad, "kind": "revenue", "amount": 1}).status_code == 422  # total plafonné
    assert c.post("/api/logs/entry", headers=H, json={**bad, "date": "2999-01-01", "kind": "revenue", "amount": 1}).status_code == 422
    assert c.post("/api/logs/entry", headers=H, json={**bad, "date": "pas-une-date", "kind": "revenue", "amount": 1}).status_code == 422
    assert c.put("/api/logs", headers=H, json={**bad, "status": "Inconnu", "revenue": 1}).status_code == 422
    assert c.post("/api/logs/bulk", headers=H, json={"date": TD, "items": [{"vehicle_id": v1["id"]}]}).status_code == 422


def test_vehicules_chauffeurs_maintenance(c):
    H = signup(c, "vehicules@example.com", vehicles=False)
    nv = c.post("/api/vehicles", headers=H, json={"brand": "Kia", "model": "Rio", "plate": "bz 1", "year": 2020, "km": 0})
    assert nv.status_code == 200 and nv.json()["plate"] == "BZ 1"
    vid = nv.json()["id"]
    assert c.post("/api/vehicles", headers=H, json={"brand": "Kia", "model": "Rio", "plate": "BZ  1"}).status_code == 409

    assert c.post(f"/api/vehicles/{vid}/driver", headers=H, json={"name": "Paul Test", "phone": "060000001"}).status_code == 200
    assert c.post(f"/api/vehicles/{vid}/driver", headers=H, json={"name": "Marc Test"}).status_code == 200
    b = c.get("/api/bootstrap", headers=H).json()
    assert b["vehicles"][0]["driver"] == "Marc Test"
    assert [(a["driver"], a["end"] is None) for a in b["assignments"]] == [("Paul Test", False), ("Marc Test", True)]
    assert c.delete(f"/api/vehicles/{vid}/driver", headers=H).status_code == 200
    assert c.get("/api/bootstrap", headers=H).json()["vehicles"][0]["driver"] == "À assigner"

    m = c.post("/api/maintenance", headers=H, json={"vehicle_id": vid, "type": "Panne", "description": "Surchauffe", "cost": 5000, "date": TD}).json()
    assert m["status"] == "En cours"
    veh = lambda: c.get("/api/bootstrap", headers=H).json()["vehicles"][0]["status"]  # noqa: E731
    assert veh() == "down"
    assert c.patch(f"/api/maintenance/{m['id']}", headers=H, json={"status": "Terminé"}).status_code == 200
    assert veh() == "ok"
    e = c.post("/api/maintenance", headers=H, json={"vehicle_id": vid, "type": "Entretien", "date": TD}).json()
    assert e["status"] == "Planifié"
    assert c.patch(f"/api/vehicles/{vid}", headers=H, json={"status": "down"}).json()["status"] == "down"
    assert c.patch(f"/api/vehicles/{vid}", headers=H, json={"status": "n'importe quoi"}).status_code == 422
    assert c.post("/api/maintenance", headers=H, json={"vehicle_id": 99999, "type": "Panne", "date": TD}).status_code == 404


def test_isolation_entre_entreprises(c):
    A = signup(c, "entreprise-a@example.com")
    B = signup(c, "entreprise-b@example.com", vehicles=False)
    va = c.get("/api/bootstrap", headers=A).json()["vehicles"][0]["id"]
    assert c.get("/api/bootstrap", headers=B).json()["vehicles"] == []
    m = c.post("/api/maintenance", headers=A, json={"vehicle_id": va, "type": "Panne", "date": TD}).json()
    attaques = [
        c.put("/api/logs", headers=B, json={"vehicle_id": va, "date": TD, "status": "Exploité", "revenue": 1}),
        c.post("/api/logs/entry", headers=B, json={"vehicle_id": va, "date": TD, "kind": "revenue", "amount": 1}),
        c.post("/api/logs/bulk", headers=B, json={"date": TD, "items": [{"vehicle_id": va, "rest": True}]}),
        c.patch(f"/api/vehicles/{va}", headers=B, json={"status": "down"}),
        c.post(f"/api/vehicles/{va}/driver", headers=B, json={"name": "Intrus"}),
        c.delete(f"/api/vehicles/{va}/driver", headers=B),
        c.post("/api/maintenance", headers=B, json={"vehicle_id": va, "type": "Panne", "date": TD}),
        c.patch(f"/api/maintenance/{m['id']}", headers=B, json={"status": "Terminé"}),
    ]
    assert [r.status_code for r in attaques] == [404] * len(attaques)
    # la même plaque peut exister dans deux entreprises différentes
    assert c.post("/api/vehicles", headers=B, json={"brand": "Toyota", "model": "Corolla", "plate": "XX 100 AA"}).status_code == 200


def test_roles_mecanicien(c):
    owner = signup(c, "chef@example.com")
    meca = signup(c, "mecanicien@example.com", vehicles=False)
    owner_id = c.get("/api/auth/me", headers=owner).json()["id"]
    with main.db(write=True) as db:  # rattache le mécanicien à l'entreprise du chef (pas encore d'invitation dans l'appli)
        db.execute("UPDATE users SET role='mecanicien', org_id=? WHERE email='mecanicien@example.com'", (owner_id,))
    vid = c.get("/api/bootstrap", headers=owner).json()["vehicles"][0]["id"]
    c.post("/api/logs/entry", headers=owner, json={"vehicle_id": vid, "date": TD, "kind": "revenue", "amount": 1000})
    b = c.get("/api/bootstrap", headers=meca).json()
    assert b["role"] == "mecanicien" and len(b["vehicles"]) == 2 and b["logs"] == [] and b["expenses"] == [] and b["assignments"] == []
    assert c.put("/api/logs", headers=meca, json={"vehicle_id": vid, "date": TD, "status": "Exploité", "revenue": 1}).status_code == 403
    assert c.post("/api/vehicles", headers=meca, json={"brand": "X", "model": "Y", "plate": "Z 1"}).status_code == 403
    assert c.post("/api/maintenance", headers=meca, json={"vehicle_id": vid, "type": "Entretien", "date": TD}).status_code == 200


def test_esse_ai(c, monkeypatch):
    H = signup(c, "ia@example.com")
    # sans clé : le front retombe sur sa simulation
    assert c.post("/api/assistant", headers=H, json={"message": "Bilan ?"}).json()["mode"] == "unavailable"
    assert c.post("/api/assistant", json={"message": "Bilan ?"}).status_code == 401

    async def faux_openai(messages):
        assert "<donnees_flotte>" in messages[1]["content"] and messages[-1]["content"] == "Bilan ?"
        return "Bonjour", {"prompt_tokens": 1000, "completion_tokens": 100}

    monkeypatch.setattr(main, "API_KEY", "cle-factice-de-test")
    monkeypatch.setattr(main, "call_openai", faux_openai)
    monkeypatch.setattr(main, "BUDGET_USD", 0.0001)
    r = c.post("/api/assistant", headers=H, json={"message": "Bilan ?", "history": [{"role": "user", "content": "Salut"}]}).json()
    assert r == {"mode": "ok", "text": "Bonjour", "usage": {"tin": 1000, "tout": 100}}
    assert c.post("/api/assistant", headers=H, json={"message": "Encore ?"}).json()["mode"] == "limit"
    assert c.post("/api/assistant", headers=H, json={"message": ""}).status_code == 422


def test_appels_du_html_couverts_par_le_backend():
    """Chaque api('/...') du fichier HTML doit correspondre à une route du backend."""
    html = Path(main.HTML).read_text(encoding="utf-8")
    appels = set()
    for m in re.finditer(r"api\('(/[^']*)'(?:\s*\+\s*([A-Za-z_.]+)\s*(?:\+\s*'([^']*)')?)?(?:,\{method:'([A-Z]+)')?", html):
        chemin = m.group(1) + ("{id}" + (m.group(3) or "") if m.group(2) else "")
        appels.add((m.group(4) or "GET", chemin))
    assert appels, "aucun appel api() trouvé dans le HTML"
    norm = lambda p: re.sub(r"\{[^}]+\}", "{id}", p)  # noqa: E731
    routes = {(meth, norm(r.path.replace("/api", "", 1))) for r in main.app.routes if hasattr(r, "methods") for meth in r.methods}
    manquants = sorted(a for a in appels if (a[0], norm(a[1])) not in routes)
    assert not manquants, f"Routes manquantes dans le backend : {manquants}"


def test_pages(c):
    assert c.get("/health").json()["status"] == "ok"
    r = c.get("/")
    assert r.status_code == 200 and "ESSE" in r.text
