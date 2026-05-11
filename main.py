# """
# Resume Parser Web Application — FastAPI Backend
# ================================================
# Run with:  python main.py

# Routes:
#   GET  /            → upload page  (user)
#   GET  /admin       → upload page  (admin — unlocks Raw JSON + New button)
#   GET  /parse       → parse page   (user,  reached after auto-upload)
#   GET  /parse?admin=1 → parse page (admin)
#   POST /upload      → parse resume, return JSON
#   POST /save        → persist JSON + Excel
#   GET  /file/{name} → serve uploaded file
#   GET  /download    → download all_resumes.xlsx
#   GET  /warmup      → model warm-up status

# File layout expected:
#   main.py
#   templates/
#     upload.html
#     parse.html
#   static/
#     app.css
#     app.js
#   uploads/          (auto-created)
#   resumes/          (auto-created)
# """

# from __future__ import annotations

# import json
# import logging
# import sys
# import time
# import traceback
# from contextlib import asynccontextmanager
# from datetime import datetime
# from pathlib import Path
# from typing import Any

# import uvicorn
# from fastapi import FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
# from fastapi.staticfiles import StaticFiles



# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
#     datefmt="%H:%M:%S",
# )
# log = logging.getLogger("resume_api")

# # ── Paths ─────────────────────────────────────────────────────────────────────
# BASE_DIR      = Path(__file__).parent
# TEMPLATES_DIR = BASE_DIR / "templates"
# STATIC_DIR    = BASE_DIR / "static"
# UPLOAD_DIR    = BASE_DIR / "uploads"
# RESUME_DIR    = BASE_DIR / "resumes"
# EXCEL_PATH    = BASE_DIR / "all_resumes.xlsx"

# UPLOAD_DIR.mkdir(exist_ok=True)
# ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt"}

# # Sanity-check required folders
# for _d, _name in [(TEMPLATES_DIR, "templates"), (STATIC_DIR, "static")]:
#     if not _d.exists():
#         raise RuntimeError(
#             f"'{_name}/' folder not found at {_d}. "
#             "Make sure templates/ and static/ are next to main.py."
#         )

# # ── Load parser module ────────────────────────────────────────────────────────
# sys.path.insert(0, str(BASE_DIR))
# try:
#     import resume_extract as _rex
#     from resume_extract import process_resume as _process_resume
#     log.info("resume_extract imported ")
# except Exception as exc:
#     log.critical("Cannot import resume_extract: %s", exc)
#     raise


# # ── Lifespan (model pre-warming) ──────────────────────────────────────────────
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     log.info("=" * 55)
#     log.info("  PRE-WARMING MODELS — server will be ready shortly")
#     log.info("=" * 55)
#     t_start = time.perf_counter()

#     for label, fn in [
#         ("spaCy en_core_web_lg",     _rex.get_nlp),
#         ("SkillNer SkillExtractor",  _rex.get_skill_extractor),
#     ]:
#         t = time.perf_counter()
#         try:
#             fn()
#             log.info("   %-32s (%.1fs)", label, time.perf_counter() - t)
#         except Exception as exc:
#             log.warning("   %s load failed: %s", label, exc)

#     t = time.perf_counter()
#     try:
#         _rex._taxonomy.batch_categorize(["Python", "AWS", "Leadership"])
#         log.info("   %-32s (%.1fs)", "DynamicSkillTaxonomy warmed", time.perf_counter() - t)
#     except Exception as exc:
#         log.warning("   Taxonomy warm failed: %s", exc)

#     log.info("=" * 55)
#     log.info("  SERVER READY in %.1fs", time.perf_counter() - t_start)
#     log.info("=" * 55)
#     yield

#     log.info("Shutting down — saving taxonomy cache")
#     try:
#         _rex._taxonomy.save_cache()
#     except Exception:
#         pass


# # ── App ───────────────────────────────────────────────────────────────────────
# app = FastAPI(title="Resume Parser", version="4.0.0", lifespan=lifespan)

# # Mount /static → static/
# app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# # ── Template helper ───────────────────────────────────────────────────────────
# def _render(name: str) -> HTMLResponse:
#     """Read a template from templates/ and return it as HTMLResponse."""
#     path = TEMPLATES_DIR / name
#     if not path.exists():
#         raise HTTPException(404, f"Template '{name}' not found in templates/")
#     return HTMLResponse(path.read_text(encoding="utf-8"))


# # ── JSON serialiser ───────────────────────────────────────────────────────────
# def _to_json(obj: Any) -> Any:
#     if obj is None:
#         return None
#     if hasattr(obj, "__dataclass_fields__"):
#         from dataclasses import asdict
#         return _to_json(asdict(obj))
#     if hasattr(obj, "model_dump"):
#         return _to_json(obj.model_dump(by_alias=True, exclude_none=True))
#     if hasattr(obj, "dict"):
#         return _to_json(obj.dict(by_alias=True, exclude_none=True))
#     if isinstance(obj, dict):
#         return {k: _to_json(v) for k, v in obj.items() if v is not None}
#     if isinstance(obj, (list, tuple)):
#         return [_to_json(i) for i in obj]
#     if hasattr(obj, "isoformat"):
#         return obj.isoformat()
#     return obj


# # ── Skills helper ─────────────────────────────────────────────────────────────
# def _skills_to_str(data: dict) -> str:
#     raw = data.get("skills") or []
#     if not raw:
#         return ""
#     if isinstance(raw[0], str):
#         return ", ".join(raw)
#     return ", ".join(s.get("name", "") for s in raw if s.get("name"))


# # ── Recruiter fields ──────────────────────────────────────────────────────────
# RECRUITER_FIELDS = ["current_position_title", "current_salary", "expected_salary", "notice_period"]

# def _build_recruiter_block(data: dict) -> dict:
#     block: dict = {}
#     if title := data.get("current_position_title"):
#         block["current_position_title"] = title
#     if csal := data.get("current_salary"):
#         block["current_salary"] = {"value": int(csal), "currency": "INR", "formatted": f"₹{int(csal):,}"}
#     if esal := data.get("expected_salary"):
#         block["expected_salary"] = {"value": int(esal), "currency": "INR", "formatted": f"₹{int(esal):,}"}
#     if notice := data.get("notice_period"):
#         block["notice_period"] = notice
#     return block


# # ════════════════════════════════════════════════════════
# #  ROUTES
# # ════════════════════════════════════════════════════════

# # ── Upload page ───────────────────────────────────────────────────────────────

# @app.get("/", response_class=HTMLResponse)
# async def user_upload():
#     """User-facing upload screen (no admin controls)."""
#     return _render("upload.html")


# @app.get("/admin", response_class=HTMLResponse)
# async def admin_upload():
#     """
#     Admin upload screen — same HTML as user upload.
#     The JS detects /admin via window.location.pathname and enables
#     Raw JSON + ← New on the parse page.
#     """
#     log.info("Admin upload accessed")
#     return _render("upload.html")


# # ── Parse result page ─────────────────────────────────────────────────────────

# @app.get("/parse", response_class=HTMLResponse)
# async def serve_parse():
#     """
#     Parse result page.
#     Data is passed via sessionStorage (written by app.js after /upload succeeds).
#     Admin controls visible only when ?admin=1 or navigated from /admin.
#     """
#     return _render("parse.html")


# # ── Static file serving for uploaded resumes ──────────────────────────────────

# @app.get("/file/{filename:path}")
# async def serve_uploaded_file(filename: str):
#     path = UPLOAD_DIR / filename
#     if not path.exists():
#         raise HTTPException(404, f"File not found: {filename}")
#     ext = path.suffix.lower()
#     media_types = {
#         ".pdf":  "application/pdf",
#         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#         ".doc":  "application/msword",
#         ".txt":  "text/plain",
#     }
#     return FileResponse(path, media_type=media_types.get(ext, "application/octet-stream"))


# # ── Warmup check ─────────────────────────────────────────────────────────────

# @app.get("/warmup")
# async def warmup_check():
#     nlp_ok  = _rex._nlp is not None
#     snr_ok  = _rex._skill_extractor is not None
#     tax_ok  = _rex._taxonomy._cat_matrix is not None
#     return {
#         "status":   "ready" if (nlp_ok and snr_ok) else "warming",
#         "spacy":    nlp_ok,
#         "skillner": snr_ok,
#         "taxonomy": tax_ok,
#     }


# # ── Upload / parse ────────────────────────────────────────────────────────────

# @app.post("/upload")
# async def upload_resume(file: UploadFile = File(...)):
#     ext = Path(file.filename).suffix.lower()
#     if ext not in ALLOWED_EXT:
#         raise HTTPException(400, f"Unsupported type '{ext}'. Allowed: {', '.join(ALLOWED_EXT)}")

#     dest     = UPLOAD_DIR / file.filename
#     contents = await file.read()
#     dest.write_bytes(contents)
#     log.info("Saved: %s (%d bytes)", file.filename, len(contents))

#     t0 = time.perf_counter()
#     try:
#         raw     = _process_resume(dest)
#         parsed  = _to_json(raw)
#         elapsed = round(time.perf_counter() - t0, 2)

#         log.info(
#             "  Parsed %.2fs — sections: %s — skills: %d",
#             elapsed,
#             parsed.get("_sections_detected", []),
#             len(parsed.get("skills") or []),
#         )

#         return JSONResponse({
#             "success":         True,
#             "filename":        file.filename,
#             "elapsed_seconds": elapsed,
#             "file_url":        f"/file/{file.filename}",
#             "data":            parsed,
#         })
#     except Exception as exc:
#         elapsed = round(time.perf_counter() - t0, 2)
#         log.error("Parse failed after %.2fs: %s\n%s", elapsed, exc, traceback.format_exc())
#         raise HTTPException(500, f"Parsing failed after {elapsed}s: {exc}")


# # ── Save ──────────────────────────────────────────────────────────────────────

# @app.post("/save")
# async def save_resume(request: Request):
#     body:        dict = await request.json()
#     filename:    str  = body.get("filename", "unknown")
#     data:        dict = body.get("data", {})
#     # manual=True  → user clicked 💾 Save  (write Excel)
#     # manual=False → auto-save debounce    (JSON only, skip Excel)
#     is_manual:   bool = bool(body.get("manual", False))

#     stem      = Path(filename).stem
#     timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#     recruiter_block = _build_recruiter_block(data)
#     cleaned_data    = {k: v for k, v in data.items() if k not in RECRUITER_FIELDS}

#     payload = {
#         "meta":           {"saved_at": timestamp, "source_file": filename},
#         "recruiter_info": recruiter_block,
#         **cleaned_data,
#     }

#     # Always persist JSON (cheap, idempotent)
#     RESUME_DIR.mkdir(exist_ok=True)
#     json_path = RESUME_DIR / f"{stem}.json"
#     json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

#     log.info(
#         "Saved JSON: %s | manual=%s | salary: %s→%s | notice: %s",
#         json_path.name,
#         is_manual,
#         recruiter_block.get("current_salary", {}).get("formatted", "—"),
#         recruiter_block.get("expected_salary", {}).get("formatted", "—"),
#         recruiter_block.get("notice_period", "—"),
#     )

#     # ── Excel: only on manual save, and only when required fields are filled ──
#     excel_updated = False
#     if is_manual:
#         csal   = recruiter_block.get("current_salary", {}).get("value")
#         esal   = recruiter_block.get("expected_salary", {}).get("value")
#         notice = recruiter_block.get("notice_period")

#         if not (csal and esal and notice):
#             log.info("Excel skipped — salary/notice not fully filled")
#         else:
#             try:
#                 import pandas as pd

#                 def _name(d):
#                     n = d.get("candidate_name") or {}
#                     return " ".join(filter(None, [n.get("first_name", ""), n.get("family_name", "")])).strip() or "Unknown"

#                 def _loc(d):
#                     loc = d.get("location") or {}
#                     return ", ".join(filter(None, [loc.get("city"), loc.get("state"), loc.get("country")]))

#                 def _exp(d):
#                     return "; ".join(
#                         f"{e.get('work_experience_job_title', '')} @ {e.get('work_experience_organization', '')}"
#                         for e in (d.get("work_experience") or [])
#                     )

#                 # Primary email used as unique key
#                 email_list = data.get("email") or []
#                 primary_email = (email_list[0] if email_list else "").strip().lower()

#                 row = {
#                     "Saved_At":            timestamp,
#                     "Source_File":         filename,
#                     "Full_Name":           _name(data),
#                     "Email":               ", ".join(email_list[:2]),
#                     "Phone":               ", ".join(
#                         p.get("raw", "") or p.get("e164", "") for p in (data.get("phone_number") or [])
#                     ),
#                     "Location":            _loc(data),
#                     "Total_Exp_Years":     data.get("total_years_experience") or "",
#                     "Current_Position":    recruiter_block.get("current_position_title", ""),
#                     "Current_Salary_INR":  csal,
#                     "Expected_Salary_INR": esal,
#                     "Notice_Period":       notice,
#                     "Skills":              _skills_to_str(data),
#                     "Work_Experience":     _exp(data),
#                     "Summary":             " ".join(data.get("summary") or [])[:500],
#                 }

#                 if EXCEL_PATH.exists():
#                     df = pd.read_excel(EXCEL_PATH, engine="openpyxl")

#                     # Normalise Email column for matching
#                     df["_email_key"] = df["Email"].fillna("").str.split(",").str[0].str.strip().str.lower()

#                     if primary_email and primary_email in df["_email_key"].values:
#                         # ── UPDATE existing row ──
#                         idx = df.index[df["_email_key"] == primary_email][0]
#                         for col, val in row.items():
#                             df.at[idx, col] = val
#                         log.info("Excel: updated existing row for %s (idx %d)", primary_email, idx)
#                     else:
#                         # ── INSERT new row ──
#                         new_df = pd.DataFrame([row])
#                         df = pd.concat([df, new_df], ignore_index=True)
#                         log.info("Excel: inserted new row for %s", primary_email or "(no email)")

#                     df.drop(columns=["_email_key"], inplace=True)
#                 else:
#                     df = pd.DataFrame([row])
#                     log.info("Excel: created new file with first row")

#                 df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
#                 excel_updated = True
#                 log.info("Excel saved (%d rows)", len(df))

#             except ImportError:
#                 log.warning("pandas/openpyxl not installed — Excel skipped.")
#             except Exception as exc:
#                 log.error("Excel update failed: %s", exc)

#     return JSONResponse({
#         "success":       True,
#         "saved_at":      timestamp,
#         "json_file":     str(json_path),
#         "excel_updated": excel_updated,
#     })


# # ── Excel download ────────────────────────────────────────────────────────────

# @app.get("/download")
# async def download_excel():
#     if not EXCEL_PATH.exists():
#         raise HTTPException(404, "No Excel file yet — save at least one resume first.")
#     return FileResponse(
#         EXCEL_PATH, filename="all_resumes.xlsx",
#         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#     )


# # ── Entry-point ───────────────────────────────────────────────────────────────
# if __name__ == "__main__":
#     print("\n" + "=" * 60)
#     print("  Resume Parser  v4.0")
#     print(f"  User  →  http://localhost:8000/")
#     print(f"  Admin →  http://localhost:8000/admin")
#     print(f"  Docs  →  http://localhost:8000/docs")
#     print(f"  Check →  http://localhost:8000/warmup")
#     print("=" * 60 + "\n")
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)




# """
# Resume Parser Web Application — FastAPI Backend
# ================================================
# Run with:  python main.py

# Routes:
#   GET  /            → upload page  (user)
#   GET  /admin       → upload page  (admin — unlocks Raw JSON + New button)
#   GET  /parse       → parse page   (user,  reached after auto-upload)
#   GET  /parse?admin=1 → parse page (admin)
#   POST /upload      → parse resume, return JSON
#   POST /save        → persist JSON + Excel
#   GET  /file/{name} → serve uploaded file
#   GET  /download    → download all_resumes.xlsx
#   GET  /warmup      → model warm-up status

# File layout expected:
#   main.py
#   templates/
#     upload.html
#     parse.html
#   static/
#     app.css
#     app.js
#   uploads/          (auto-created)
#   resumes/          (auto-created)
# """

# from __future__ import annotations
# import os 
# import json
# import logging
# import sys
# import time
# import traceback
# from contextlib import asynccontextmanager
# from datetime import datetime
# from pathlib import Path
# from typing import Any

# import uvicorn
# from fastapi import FastAPI, File, HTTPException, Request, UploadFile
# from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
# from fastapi.staticfiles import StaticFiles

# import psycopg2


# import requests


# SITE_URL = "https://graph.microsoft.com/v1.0/sites/lexestechnologies.sharepoint.com:/sites/everyone:"



# # ── DB CONFIG ──
# db_config = {
#     "host": "localhost",
#     "database": "earlyjoiner_company",
#     "user": "postgres",
#     "password": "sa",
#     "port": 5432
# }



# def save_to_postgres(data, filename, sharepoint_link):
#     try:
#         conn = psycopg2.connect(**db_config)
#         cursor = conn.cursor()

#         # Name
#         name = ""
#         if data.get("candidate_name"):
#             n = data["candidate_name"]
#             name = f"{n.get('first_name','')} {n.get('family_name','')}"

#         # Email (PRIMARY KEY for duplicate handling)
#         email_list = data.get("email", [])
#         email = email_list[0] if email_list else None

#         # ✅ FIX: if email not present → generate unique fallback
#         if not email:
#             email = f"noemail_{filename}"

#         # Phone
#         phone = ", ".join(
#             p.get("raw", "") for p in data.get("phone_number", [])
#         )

#         # Location
#         city = data.get("location", {}).get("city", "")
#         country = data.get("location", {}).get("country", "")

#         # Experience
#         experience = data.get("total_years_experience", 0)

#         # Current Position
#         current_position = data.get("recruiter_info", {}).get("current_position_title", "")

#         # Skills
#         skills = ", ".join(data.get("skills", []))

#         # Summary
#         summary = " ".join(data.get("summary", []))[:1000]

#         cursor.execute("""
#         INSERT INTO candidates (
#             full_name, email, phone, city, country,
#             total_experience, current_position,
#             skills, summary, source_file, sharepoint_url
#         )
#         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#         ON CONFLICT (email) DO UPDATE SET
#             full_name = EXCLUDED.full_name,
#             phone = EXCLUDED.phone,
#             city = EXCLUDED.city,
#             country = EXCLUDED.country,
#             total_experience = EXCLUDED.total_experience,
#             current_position = EXCLUDED.current_position,
#             skills = EXCLUDED.skills,
#             summary = EXCLUDED.summary,
#             source_file = EXCLUDED.source_file,
#             sharepoint_url = EXCLUDED.sharepoint_url;
#         """, (
#             name,
#             email,
#             phone,
#             city,
#             country,
#             experience,
#             current_position,
#             skills,
#             summary,
#             filename,
#             sharepoint_link
#         ))

#         conn.commit()
#         cursor.close()
#         conn.close()

#         print("✅ Data saved to PostgreSQL")

#     except Exception as e:
#         print("❌ PostgreSQL Error:", e)

# # ── Token function(sharepoint) ───────────────────────────────────────────────────────────────────
# def get_access_token():
#     token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

#     data = {
#         "client_id": CLIENT_ID,
#         "scope": "https://graph.microsoft.com/.default",
#         "client_secret": CLIENT_SECRET,
#         "grant_type": "client_credentials"
#     }

#     res = requests.post(token_url, data=data)
#     return res.json().get("access_token")



# # ── upload function(sharepoint) ───────────────────────────────────────────────────────────────────
# def upload_to_sharepoint(file_path: Path, folder_name: str, filename: str):
#     try:
#         token = get_access_token()
#         headers = {"Authorization": f"Bearer {token}"}

#         # Get Site ID
#         site_res = requests.get(SITE_URL, headers=headers).json()
#         site_id = site_res["id"]

#         # Get Drive ID
#         drive_res = requests.get(
#             f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive",
#             headers=headers
#         ).json()
#         drive_id = drive_res["id"]

#         # ✅ Folder-wise upload
#         upload_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/Resumes/{folder_name}/{filename}:/content"

#         with open(file_path, "rb") as f:
#             upload_res = requests.put(upload_url, headers=headers, data=f)

#         if upload_res.status_code in [200, 201]:
#             file_url = upload_res.json().get("webUrl")
#             print("✅ Uploaded:", file_url)
#             return file_url
#         else:
#             print("❌ Upload failed:", upload_res.text)
#             return None

#     except Exception as e:
#         print("❌ SharePoint Error:", e)
#         return None


# # ── sharepoint(excel) ───────────────────────────────────────────────────────────────────
# def create_candidate_excel(data, filepath):
#     import pandas as pd

#     name = ""
#     if data.get("candidate_name"):
#         n = data["candidate_name"]
#         name = f"{n.get('first_name','')} {n.get('family_name','')}"

#     row = {
#         "Full Name": name,
#         "Email": ", ".join(data.get("email", [])),
#         "Phone": ", ".join(p.get("raw", "") for p in data.get("phone_number", [])),
#         "City": data.get("location", {}).get("city", ""),
#         "Country": data.get("location", {}).get("country", ""),
#         "Experience (Years)": data.get("total_years_experience", ""),
#         "Current Role": data.get("recruiter_info", {}).get("current_position_title", ""),
#         "Skills": ", ".join(data.get("skills", [])),
#         "Summary": " ".join(data.get("summary", []))[:500],
#     }

#     df = pd.DataFrame([row])
#     df.to_excel(filepath, index=False)

# # ── Logging ───────────────────────────────────────────────────────────────────
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
#     datefmt="%H:%M:%S",
# )
# log = logging.getLogger("resume_api")

# # ── Paths ─────────────────────────────────────────────────────────────────────
# BASE_DIR      = Path(__file__).parent
# TEMPLATES_DIR = BASE_DIR / "templates"
# STATIC_DIR    = BASE_DIR / "static"
# UPLOAD_DIR    = BASE_DIR / "uploads"
# RESUME_DIR    = BASE_DIR / "resumes"
# EXCEL_PATH    = BASE_DIR / "all_resumes.xlsx"

# UPLOAD_DIR.mkdir(exist_ok=True)
# ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt"}

# # Sanity-check required folders
# for _d, _name in [(TEMPLATES_DIR, "templates"), (STATIC_DIR, "static")]:
#     if not _d.exists():
#         raise RuntimeError(
#             f"'{_name}/' folder not found at {_d}. "
#             "Make sure templates/ and static/ are next to main.py."
#         )

# # ── Load parser module ────────────────────────────────────────────────────────
# sys.path.insert(0, str(BASE_DIR))
# try:
#     import resume_extract as _rex
#     from resume_extract import process_resume as _process_resume
#     log.info("resume_extract imported ")
# except Exception as exc:
#     log.critical("Cannot import resume_extract: %s", exc)
#     raise


# # ── Lifespan (model pre-warming) ──────────────────────────────────────────────
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     log.info("=" * 55)
#     log.info("  PRE-WARMING MODELS — server will be ready shortly")
#     log.info("=" * 55)
#     t_start = time.perf_counter()

#     for label, fn in [
#         ("spaCy en_core_web_lg",     _rex.get_nlp),
#         ("SkillNer SkillExtractor",  _rex.get_skill_extractor),
#     ]:
#         t = time.perf_counter()
#         try:
#             fn()
#             log.info("   %-32s (%.1fs)", label, time.perf_counter() - t)
#         except Exception as exc:
#             log.warning("   %s load failed: %s", label, exc)

#     t = time.perf_counter()
#     try:
#         _rex._taxonomy.batch_categorize(["Python", "AWS", "Leadership"])
#         log.info("   %-32s (%.1fs)", "DynamicSkillTaxonomy warmed", time.perf_counter() - t)
#     except Exception as exc:
#         log.warning("   Taxonomy warm failed: %s", exc)

#     log.info("=" * 55)
#     log.info("  SERVER READY in %.1fs", time.perf_counter() - t_start)
#     log.info("=" * 55)
#     yield

#     log.info("Shutting down — saving taxonomy cache")
#     try:
#         _rex._taxonomy.save_cache()
#     except Exception:
#         pass


# # ── App ───────────────────────────────────────────────────────────────────────
# app = FastAPI(title="Resume Parser", version="4.0.0", lifespan=lifespan)

# # Mount /static → static/
# app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# # ── Template helper ───────────────────────────────────────────────────────────
# def _render(name: str) -> HTMLResponse:
#     """Read a template from templates/ and return it as HTMLResponse."""
#     path = TEMPLATES_DIR / name
#     if not path.exists():
#         raise HTTPException(404, f"Template '{name}' not found in templates/")
#     return HTMLResponse(path.read_text(encoding="utf-8"))


# # ── JSON serialiser ───────────────────────────────────────────────────────────
# def _to_json(obj: Any) -> Any:
#     if obj is None:
#         return None
#     if hasattr(obj, "__dataclass_fields__"):
#         from dataclasses import asdict
#         return _to_json(asdict(obj))
#     if hasattr(obj, "model_dump"):
#         return _to_json(obj.model_dump(by_alias=True, exclude_none=True))
#     if hasattr(obj, "dict"):
#         return _to_json(obj.dict(by_alias=True, exclude_none=True))
#     if isinstance(obj, dict):
#         return {k: _to_json(v) for k, v in obj.items() if v is not None}
#     if isinstance(obj, (list, tuple)):
#         return [_to_json(i) for i in obj]
#     if hasattr(obj, "isoformat"):
#         return obj.isoformat()
#     return obj


# # ── Skills helper ─────────────────────────────────────────────────────────────
# def _skills_to_str(data: dict) -> str:
#     raw = data.get("skills") or []
#     if not raw:
#         return ""
#     if isinstance(raw[0], str):
#         return ", ".join(raw)
#     return ", ".join(s.get("name", "") for s in raw if s.get("name"))


# # ── Recruiter fields ──────────────────────────────────────────────────────────
# RECRUITER_FIELDS = ["current_position_title", "current_salary", "expected_salary", "notice_period"]

# def _build_recruiter_block(data: dict) -> dict:
#     block: dict = {}
#     if title := data.get("current_position_title"):
#         block["current_position_title"] = title
#     if csal := data.get("current_salary"):
#         block["current_salary"] = {"value": int(csal), "currency": "INR", "formatted": f"₹{int(csal):,}"}
#     if esal := data.get("expected_salary"):
#         block["expected_salary"] = {"value": int(esal), "currency": "INR", "formatted": f"₹{int(esal):,}"}
#     if notice := data.get("notice_period"):
#         block["notice_period"] = notice
#     return block


# # ════════════════════════════════════════════════════════
# #  ROUTES
# # ════════════════════════════════════════════════════════

# # ── Upload page ───────────────────────────────────────────────────────────────

# @app.get("/", response_class=HTMLResponse)
# async def user_upload():
#     """User-facing upload screen (no admin controls)."""
#     return _render("upload.html")


# @app.get("/admin", response_class=HTMLResponse)
# async def admin_upload():
#     """
#     Admin upload screen — same HTML as user upload.
#     The JS detects /admin via window.location.pathname and enables
#     Raw JSON + ← New on the parse page.
#     """
#     log.info("Admin upload accessed")
#     return _render("upload.html")


# # ── Parse result page ─────────────────────────────────────────────────────────

# @app.get("/parse", response_class=HTMLResponse)
# async def serve_parse():
#     """
#     Parse result page.
#     Data is passed via sessionStorage (written by app.js after /upload succeeds).
#     Admin controls visible only when ?admin=1 or navigated from /admin.
#     """
#     return _render("parse.html")


# # ── Static file serving for uploaded resumes ──────────────────────────────────

# @app.get("/file/{filename:path}")
# async def serve_uploaded_file(filename: str):
#     path = UPLOAD_DIR / filename
#     if not path.exists():
#         raise HTTPException(404, f"File not found: {filename}")
#     ext = path.suffix.lower()
#     media_types = {
#         ".pdf":  "application/pdf",
#         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#         ".doc":  "application/msword",
#         ".txt":  "text/plain",
#     }
#     return FileResponse(path, media_type=media_types.get(ext, "application/octet-stream"))


# # ── Warmup check ─────────────────────────────────────────────────────────────

# @app.get("/warmup")
# async def warmup_check():
#     nlp_ok  = _rex._nlp is not None
#     snr_ok  = _rex._skill_extractor is not None
#     tax_ok  = _rex._taxonomy._cat_matrix is not None
#     return {
#         "status":   "ready" if (nlp_ok and snr_ok) else "warming",
#         "spacy":    nlp_ok,
#         "skillner": snr_ok,
#         "taxonomy": tax_ok,
#     }


# # ── Upload / parse ────────────────────────────────────────────────────────────

# @app.post("/upload")
# async def upload_resume(file: UploadFile = File(...)):
#     ext = Path(file.filename).suffix.lower()
#     if ext not in ALLOWED_EXT:
#         raise HTTPException(400, f"Unsupported type '{ext}'. Allowed: {', '.join(ALLOWED_EXT)}")

#     dest     = UPLOAD_DIR / file.filename
#     contents = await file.read()
#     dest.write_bytes(contents)
#     log.info("Saved: %s (%d bytes)", file.filename, len(contents))

#     t0 = time.perf_counter()
#     try:
#         raw     = _process_resume(dest)
#         parsed  = _to_json(raw)
#         elapsed = round(time.perf_counter() - t0, 2)

#         log.info(
#             "  Parsed %.2fs — sections: %s — skills: %d",
#             elapsed,
#             parsed.get("_sections_detected", []),
#             len(parsed.get("skills") or []),
#         )

#         return JSONResponse({
#             "success":         True,
#             "filename":        file.filename,
#             "elapsed_seconds": elapsed,
#             "file_url":        f"/file/{file.filename}",
#             "data":            parsed,
#         })
#     except Exception as exc:
#         elapsed = round(time.perf_counter() - t0, 2)
#         log.error("Parse failed after %.2fs: %s\n%s", elapsed, exc, traceback.format_exc())
#         raise HTTPException(500, f"Parsing failed after {elapsed}s: {exc}")


# # ── Save ──────────────────────────────────────────────────────────────────────
# # ── Save (FINAL CLEAN VERSION) ───────────────────────────────────────────────

# @app.post("/save")
# async def save_resume(request: Request):
#     body = await request.json()
#     filename = body.get("filename", "unknown")
#     data = body.get("data", {})

#     timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#     # ── Candidate Name ─────────────────────
#     candidate_name = data.get("candidate_name", {})
#     first = candidate_name.get("first_name", "")
#     last = candidate_name.get("family_name", "")
#     folder_name = f"{first}_{last}".strip("_") or "Unknown"

#     # ── Create Folder ─────────────────────
#     candidate_dir = RESUME_DIR / folder_name
#     candidate_dir.mkdir(parents=True, exist_ok=True)

#     # ── File Paths ─────────────────────
#     resume_path = UPLOAD_DIR / filename
#     excel_path = candidate_dir / "profile.xlsx"

#     # ── 1. Create Excel (HR friendly) ─────────────────────
#     create_candidate_excel(data, excel_path)

#     # ── 2. Upload Resume to SharePoint ─────────────────────
#     resume_link = upload_to_sharepoint(resume_path, folder_name, filename)

#     # ── 3. Upload Excel to SharePoint ─────────────────────
#     excel_link = upload_to_sharepoint(excel_path, folder_name, "profile.xlsx")

#     # ── 4. Final Link (prefer resume) ─────────────────────
#     sharepoint_link = resume_link or excel_link

#     # ── 5. Save to DB ─────────────────────
#     save_to_postgres(data, filename, sharepoint_link)

#     # ── Logs ─────────────────────
#     log.info(f"Saved candidate: {folder_name}")
#     log.info(f"SharePoint Link: {sharepoint_link}")

#     return JSONResponse({
#         "success": True,
#         "candidate": folder_name,
#         "sharepoint_link": sharepoint_link
#     })


# # ── Excel download ────────────────────────────────────────────────────────────

# @app.get("/download")
# async def download_excel():
#     if not EXCEL_PATH.exists():
#         raise HTTPException(404, "No Excel file yet — save at least one resume first.")
#     return FileResponse(
#         EXCEL_PATH, filename="all_resumes.xlsx",
#         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#     )


# # ── Entry-point ───────────────────────────────────────────────────────────────
# if __name__ == "__main__":
#     print("\n" + "=" * 60)
#     print("  Resume Parser  v4.0")
#     print(f"  User  →  http://localhost:8000/")
#     print(f"  Admin →  http://localhost:8000/admin")
#     print(f"  Docs  →  http://localhost:8000/docs")
#     print(f"  Check →  http://localhost:8000/warmup")
#     print("=" * 60 + "\n")
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)





"""
Resume Parser Web Application — FastAPI Backend
================================================
Run with:  python main.py

Routes:
  GET  /            → upload page  (user)
  GET  /admin       → upload page  (admin — unlocks Raw JSON + New button)
  GET  /parse       → parse page   (user,  reached after auto-upload)
  GET  /parse?admin=1 → parse page (admin)
  POST /upload      → parse resume, return JSON
  POST /save        → persist JSON + Excel
  GET  /file/{name} → serve uploaded file
  GET  /download    → download all_resumes.xlsx
  GET  /warmup      → model warm-up status
"""

from __future__ import annotations
import os
import json
import logging
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import psycopg2
import pandas as pd
import requests


from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

SITE_URL = "https://graph.microsoft.com/v1.0/sites/lexestechnologies.sharepoint.com:/sites/everyone:"

# ── DB CONFIG ──
db_config = {
    "host": "localhost",
    "database": "earlyjoiner_company",
    "user": "postgres",
    "password": "sa",
    "port": 5432
}


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("resume_api")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
RESUME_DIR = BASE_DIR / "resumes"
EXCEL_PATH = BASE_DIR / "all_resumes.xlsx"

UPLOAD_DIR.mkdir(exist_ok=True)
RESUME_DIR.mkdir(exist_ok=True)

ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt"}

# Sanity-check required folders
for _d, _name in [(TEMPLATES_DIR, "templates"), (STATIC_DIR, "static")]:
    if not _d.exists():
        raise RuntimeError(
            f"'{_name}/' folder not found at {_d}. "
            "Make sure templates/ and static/ are next to main.py."
        )

# ── Load parser module ────────────────────────────────────────────────────────
sys.path.insert(0, str(BASE_DIR))

try:
    import resume_extract as _rex
    from resume_extract import process_resume as _process_resume
    log.info("resume_extract imported ")
except Exception as exc:
    log.critical("Cannot import resume_extract: %s", exc)
    raise


# ── PostgreSQL Save ───────────────────────────────────────────────────────────

# ── PostgreSQL Save ───────────────────────────────────────────────────────────
def save_to_postgres(data, filename, sharepoint_link):
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        # ── Name ─────────────────────
        name = ""

        if data.get("candidate_name"):
            n = data["candidate_name"]

            first = n.get("first_name", "")
            last = n.get("family_name", "")

            name = f"{first} {last}".strip()

        # ── Email ─────────────────────
        email_data = data.get("email", [])

        if isinstance(email_data, list):
            email = email_data[0] if email_data else None

        elif isinstance(email_data, str):
            email = email_data

        else:
            email = None

        if not email:
            email = f"noemail_{filename}"

        # ── Phone Fix ─────────────────────
        phone_numbers = data.get("phone_number", [])

        if isinstance(phone_numbers, list):

            cleaned_numbers = []

            for p in phone_numbers:

                if isinstance(p, dict):

                    raw = str(
                        p.get("raw", "")
                    ).strip()

                    # remove spaces/dashes
                    raw = (
                        raw.replace(" ", "")
                        .replace("-", "")
                    )

                    # avoid scientific notation issue
                    if raw:
                        cleaned_numbers.append(raw)

            phone = ", ".join(cleaned_numbers)

        else:
            phone = ""

        # ── Location ─────────────────────
        location = data.get("location", {})

        if isinstance(location, dict):
            city = location.get("city", "")
            country = location.get("country", "")

        else:
            city = ""
            country = ""

        # ── Experience ─────────────────────
        experience = data.get(
            "total_years_experience",
            0
        )

        # ── Current Position ─────────────────────
        recruiter_info = data.get(
            "recruiter_info",
            {}
        )

        if isinstance(recruiter_info, dict):
            current_position = recruiter_info.get(
                "current_position_title",
                ""
            )

        else:
            current_position = ""

        # ── Skills Fix ─────────────────────
        skills_data = data.get("skills", [])

        if isinstance(skills_data, list):

            skills = ", ".join(
                str(skill)
                for skill in skills_data
            )

        elif isinstance(skills_data, str):

            skills = skills_data

        else:
            skills = ""

        # ── Summary Fix ─────────────────────
        summary_data = data.get("summary", [])

        if isinstance(summary_data, list):

            summary = " ".join(
                str(x)
                for x in summary_data
            )[:1000]

        elif isinstance(summary_data, str):

            summary = summary_data[:1000]

        else:
            summary = ""

        # ── Insert Query ─────────────────────
        cursor.execute("""
        INSERT INTO candidates (
            full_name,
            email,
            phone,
            city,
            country,
            total_experience,
            current_position,
            skills,
            summary,
            source_file,
            sharepoint_url
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

        ON CONFLICT (email) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            phone = EXCLUDED.phone,
            city = EXCLUDED.city,
            country = EXCLUDED.country,
            total_experience = EXCLUDED.total_experience,
            current_position = EXCLUDED.current_position,
            skills = EXCLUDED.skills,
            summary = EXCLUDED.summary,
            source_file = EXCLUDED.source_file,
            sharepoint_url = EXCLUDED.sharepoint_url;
        """, (
            name,
            email,
            phone,
            city,
            country,
            experience,
            current_position,
            skills,
            summary,
            filename,
            sharepoint_link
        ))

        conn.commit()

        cursor.close()
        conn.close()

        print("✅ Data saved to PostgreSQL")

    except Exception as e:
        print("❌ PostgreSQL Error:", e)


# ── SharePoint Token ──────────────────────────────────────────────────────────
def get_access_token():
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

    data = {
        "client_id": CLIENT_ID,
        "scope": "https://graph.microsoft.com/.default",
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    res = requests.post(token_url, data=data)
    return res.json().get("access_token")


# ── Upload to SharePoint ──────────────────────────────────────────────────────
def upload_to_sharepoint(file_path: Path, folder_name: str, filename: str):
    try:
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Get Site ID
        site_res = requests.get(SITE_URL, headers=headers).json()
        site_id = site_res["id"]

        # Get Drive ID
        drive_res = requests.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive",
            headers=headers
        ).json()

        drive_id = drive_res["id"]

        # Upload URL
        upload_url = (
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
            f"/root:/Resumes/{folder_name}/{filename}:/content"
        )

        with open(file_path, "rb") as f:
            upload_res = requests.put(upload_url, headers=headers, data=f)

        if upload_res.status_code in [200, 201]:
            file_url = upload_res.json().get("webUrl")
            print("✅ Uploaded:", file_url)
            return file_url
        else:
            print("❌ Upload failed:", upload_res.text)
            return None

    except Exception as e:
        print("❌ SharePoint Error:", e)
        return None


# ── MASTER EXCEL UPDATE ───────────────────────────────────────────────────────

# ── MASTER EXCEL UPDATE ───────────────────────────────────────────────────────
def update_master_excel(data, filepath):

    # Candidate Name
    name = ""

    if data.get("candidate_name"):
        n = data["candidate_name"]
        name = f"{n.get('first_name','')} {n.get('family_name','')}"

    # Email
    email = ", ".join(data.get("email", []))

    # Summary Fix
    summary_data = data.get("summary", [])

    if isinstance(summary_data, list):
        summary_text = " ".join(summary_data)

    elif isinstance(summary_data, str):
        summary_text = summary_data

    else:
        summary_text = ""

    # Skills Fix
    skills_data = data.get("skills", [])

    if isinstance(skills_data, list):
        skills_text = ", ".join(
            str(skill) for skill in skills_data
        )

    else:
        skills_text = str(skills_data)

    # Phone Fix
    phone_numbers = data.get("phone_number", [])

    if isinstance(phone_numbers, list):
        phone_text = ", ".join(
            p.get("raw", "")
            for p in phone_numbers
            if isinstance(p, dict)
        )
    else:
        phone_text = ""

    # Row Data
    row = {
        "Full Name": name,
        "Email": email,
        "Phone": phone_text,
        "City": data.get("location", {}).get("city", ""),
        "Country": data.get("location", {}).get("country", ""),
        "Experience (Years)": data.get("total_years_experience", ""),
        "Current Role": data.get(
            "recruiter_info", {}
        ).get("current_position_title", ""),
        "Skills": skills_text,
        "Summary": summary_text[:500],
    }

    new_df = pd.DataFrame([row])

    # Existing Excel
    if filepath.exists():

        try:
            old_df = pd.read_excel(filepath)

        except Exception:
            old_df = pd.DataFrame()

        # Remove duplicate email
        if (
            not old_df.empty
            and "Email" in old_df.columns
        ):
            old_df = old_df[
                old_df["Email"] != email
            ]

        # Add new row
        final_df = pd.concat(
            [old_df, new_df],
            ignore_index=True
        )

    else:
        final_df = new_df

    # Save Excel
    final_df.to_excel(
        filepath,
        index=False
    )

    print("✅ Master Excel Updated")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=" * 55)
    log.info("  PRE-WARMING MODELS — server will be ready shortly")
    log.info("=" * 55)

    t_start = time.perf_counter()

    for label, fn in [
        ("spaCy en_core_web_lg", _rex.get_nlp),
        ("SkillNer SkillExtractor", _rex.get_skill_extractor),
    ]:
        t = time.perf_counter()

        try:
            fn()
            log.info(
                "   %-32s (%.1fs)",
                label,
                time.perf_counter() - t
            )
        except Exception as exc:
            log.warning("   %s load failed: %s", label, exc)

    t = time.perf_counter()

    try:
        _rex._taxonomy.batch_categorize(
            ["Python", "AWS", "Leadership"]
        )

        log.info(
            "   %-32s (%.1fs)",
            "DynamicSkillTaxonomy warmed",
            time.perf_counter() - t
        )

    except Exception as exc:
        log.warning("   Taxonomy warm failed: %s", exc)

    log.info("=" * 55)
    log.info(
        "  SERVER READY in %.1fs",
        time.perf_counter() - t_start
    )
    log.info("=" * 55)

    yield

    log.info("Shutting down — saving taxonomy cache")

    try:
        _rex._taxonomy.save_cache()
    except Exception:
        pass


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Resume Parser",
    version="4.0.0",
    lifespan=lifespan
)

# Mount static
app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static"
)


# ── Template helper ───────────────────────────────────────────────────────────
def _render(name: str) -> HTMLResponse:
    path = TEMPLATES_DIR / name

    if not path.exists():
        raise HTTPException(
            404,
            f"Template '{name}' not found in templates/"
        )

    return HTMLResponse(
        path.read_text(encoding="utf-8")
    )


# ── JSON serialiser ───────────────────────────────────────────────────────────
def _to_json(obj: Any) -> Any:
    if obj is None:
        return None

    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return _to_json(asdict(obj))

    if hasattr(obj, "model_dump"):
        return _to_json(
            obj.model_dump(
                by_alias=True,
                exclude_none=True
            )
        )

    if hasattr(obj, "dict"):
        return _to_json(
            obj.dict(
                by_alias=True,
                exclude_none=True
            )
        )

    if isinstance(obj, dict):
        return {
            k: _to_json(v)
            for k, v in obj.items()
            if v is not None
        }

    if isinstance(obj, (list, tuple)):
        return [_to_json(i) for i in obj]

    if hasattr(obj, "isoformat"):
        return obj.isoformat()

    return obj


# ── Upload Page ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def user_upload():
    return _render("upload.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin_upload():
    log.info("Admin upload accessed")
    return _render("upload.html")


# ── Parse Page ────────────────────────────────────────────────────────────────
@app.get("/parse", response_class=HTMLResponse)
async def serve_parse():
    return _render("parse.html")


# ── Serve Uploaded File ───────────────────────────────────────────────────────
@app.get("/file/{filename:path}")
async def serve_uploaded_file(filename: str):
    path = UPLOAD_DIR / filename

    if not path.exists():
        raise HTTPException(
            404,
            f"File not found: {filename}"
        )

    ext = path.suffix.lower()

    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
    }

    return FileResponse(
        path,
        media_type=media_types.get(
            ext,
            "application/octet-stream"
        )
    )


# ── Warmup ────────────────────────────────────────────────────────────────────
@app.get("/warmup")
async def warmup_check():
    nlp_ok = _rex._nlp is not None
    snr_ok = _rex._skill_extractor is not None
    tax_ok = _rex._taxonomy._cat_matrix is not None

    return {
        "status": "ready" if (nlp_ok and snr_ok) else "warming",
        "spacy": nlp_ok,
        "skillner": snr_ok,
        "taxonomy": tax_ok,
    }


# ── Upload Resume ─────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()

    if ext not in ALLOWED_EXT:
        raise HTTPException(
            400,
            f"Unsupported type '{ext}'. Allowed: {', '.join(ALLOWED_EXT)}"
        )

    dest = UPLOAD_DIR / file.filename

    contents = await file.read()

    dest.write_bytes(contents)

    log.info(
        "Saved: %s (%d bytes)",
        file.filename,
        len(contents)
    )

    t0 = time.perf_counter()

    try:
        raw = _process_resume(dest)

        parsed = _to_json(raw)

        elapsed = round(
            time.perf_counter() - t0,
            2
        )

        log.info(
            "  Parsed %.2fs — sections: %s — skills: %d",
            elapsed,
            parsed.get("_sections_detected", []),
            len(parsed.get("skills") or []),
        )

        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "elapsed_seconds": elapsed,
            "file_url": f"/file/{file.filename}",
            "data": parsed,
        })

    except Exception as exc:
        elapsed = round(
            time.perf_counter() - t0,
            2
        )

        log.error(
            "Parse failed after %.2fs: %s\n%s",
            elapsed,
            exc,
            traceback.format_exc()
        )

        raise HTTPException(
            500,
            f"Parsing failed after {elapsed}s: {exc}"
        )


# ── Save Resume ───────────────────────────────────────────────────────────────
@app.post("/save")
async def save_resume(request: Request):
    body = await request.json()

    filename = body.get("filename", "unknown")
    data = body.get("data", {})

    # ── Candidate Name ─────────────────────
    candidate_name = data.get("candidate_name", {})

    first = candidate_name.get("first_name", "")
    last = candidate_name.get("family_name", "")

    folder_name = f"{first}_{last}".strip("_") or "Unknown"

    # ── Candidate Folder ─────────────────────
    candidate_dir = RESUME_DIR / folder_name

    candidate_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    # ── Resume Path ─────────────────────
    resume_path = UPLOAD_DIR / filename

    # ── MASTER EXCEL ─────────────────────
    master_excel_path = BASE_DIR / "all_resumes.xlsx"

    # Update Excel
    update_master_excel(
        data,
        master_excel_path
    )

    # ── Upload Resume ─────────────────────
    resume_link = upload_to_sharepoint(
        resume_path,
        folder_name,
        filename
    )

    # ── Upload Master Excel ─────────────────────
    master_excel_link = upload_to_sharepoint(
        master_excel_path,
        "MasterData",
        "all_resumes.xlsx"
    )

    # ── Save to PostgreSQL ─────────────────────
    save_to_postgres(
        data,
        filename,
        resume_link
    )

    # ── Logs ─────────────────────
    log.info(f"Saved candidate: {folder_name}")
    log.info(f"Resume Link: {resume_link}")
    log.info(f"Master Excel Link: {master_excel_link}")

    return JSONResponse({
        "success": True,
        "candidate": folder_name,
        "sharepoint_link": resume_link,
        "master_excel": master_excel_link
    })


# ── Download Excel ────────────────────────────────────────────────────────────
@app.get("/download")
async def download_excel():
    if not EXCEL_PATH.exists():
        raise HTTPException(
            404,
            "No Excel file yet — save at least one resume first."
        )

    return FileResponse(
        EXCEL_PATH,
        filename="all_resumes.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Resume Parser  v4.0")
    print(f"  User  →  http://localhost:8000/")
    print(f"  Admin →  http://localhost:8000/admin")
    print(f"  Docs  →  http://localhost:8000/docs")
    print(f"  Check →  http://localhost:8000/warmup")
    print("=" * 60 + "\n")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )