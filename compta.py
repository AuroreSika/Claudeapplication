#!/usr/bin/env python3
"""Compta : application de comptabilité personnelle simple (stdlib uniquement).

Lancer :  python3 compta.py   puis ouvrir http://localhost:8000
"""
import csv
import io
import json
import os
import re
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.environ.get("COMPTA_DB", os.path.join(os.path.dirname(__file__), "compta.db"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

DEFAULT_CATEGORIES = [
    ("Salaire", "recette"), ("Autres revenus", "recette"),
    ("Logement", "depense"), ("Alimentation", "depense"), ("Transport", "depense"),
    ("Santé", "depense"), ("Loisirs", "depense"), ("Abonnements", "depense"),
    ("Impôts et taxes", "depense"), ("Autres dépenses", "depense"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, opening_cents INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('recette','depense')));
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,                       -- AAAA-MM-JJ
  label TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,            -- toujours positif
  kind TEXT NOT NULL CHECK(kind IN ('recette','depense')),
  category_id INTEGER REFERENCES categories(id),
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
"""


class ValidationError(ValueError):
    pass


def parse_amount(value):
    """'12,50' / '1 234.5' / 12.5 -> 1250 (centimes, entier). Jamais de flottants."""
    s = str(value).strip().replace(" ", "").replace("\xa0", "").replace(" ", "").replace("€", "")
    s = s.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        raise ValidationError(f"Montant invalide : {value!r}")
    euros, _, cents = s.partition(".")
    return int(euros) * 100 + int((cents + "0")[:2] if cents else 0)


def fmt_amount(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100},{cents % 100:02d}"


def parse_date(value):
    s = str(value).strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        s = f"{m[3]}-{m[2]}-{m[1]}"
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise ValidationError(f"Date invalide : {value!r}")


def connect(path=None):
    db = sqlite3.connect(path or DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    if not db.execute("SELECT 1 FROM accounts").fetchone():
        db.execute("INSERT INTO accounts(name) VALUES('Compte courant')")
    if not db.execute("SELECT 1 FROM categories").fetchone():
        db.executemany("INSERT INTO categories(name,kind) VALUES(?,?)", DEFAULT_CATEGORIES)
    db.commit()
    return db


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def clean_transaction(db, d):
    kind = d.get("kind")
    if kind not in ("recette", "depense"):
        raise ValidationError("Type invalide (recette ou depense)")
    label = str(d.get("label", "")).strip()
    if not label:
        raise ValidationError("Libellé obligatoire")
    cents = parse_amount(d.get("amount", ""))
    if cents == 0:
        raise ValidationError("Le montant doit être supérieur à 0")
    account_id = int(d.get("account_id") or 0)
    if not db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
        raise ValidationError("Compte inconnu")
    cat = d.get("category_id")
    cat = int(cat) if cat not in (None, "", 0) else None
    return (parse_date(d.get("date", "")), label, cents, kind, cat, account_id, str(d.get("note", "")).strip())


def list_transactions(db, q):
    where, args = [], []
    if q.get("month"):
        where.append("t.date LIKE ?"); args.append(q["month"] + "%")
    if q.get("account_id"):
        where.append("t.account_id=?"); args.append(int(q["account_id"]))
    if q.get("category_id"):
        where.append("t.category_id=?"); args.append(int(q["category_id"]))
    if q.get("search"):
        where.append("(t.label LIKE ? OR t.note LIKE ?)"); args += [f"%{q['search']}%"] * 2
    sql = ("SELECT t.*, c.name AS category, a.name AS account FROM transactions t "
           "LEFT JOIN categories c ON c.id=t.category_id JOIN accounts a ON a.id=t.account_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    return rows(db, sql + " ORDER BY t.date DESC, t.id DESC", args)


def dashboard(db, month):
    def total(kind, where="", args=()):
        return db.execute(f"SELECT COALESCE(SUM(amount_cents),0) FROM transactions WHERE kind=? {where}",
                          (kind, *args)).fetchone()[0]
    rec, dep = total("recette", "AND date LIKE ?", (month + "%",)), total("depense", "AND date LIKE ?", (month + "%",))
    accounts = rows(db, """
        SELECT a.id, a.name, a.opening_cents + COALESCE(SUM(CASE t.kind WHEN 'recette' THEN t.amount_cents
               ELSE -t.amount_cents END),0) AS balance_cents
        FROM accounts a LEFT JOIN transactions t ON t.account_id=a.id GROUP BY a.id ORDER BY a.name""")
    by_cat = rows(db, """
        SELECT COALESCE(c.name,'Sans catégorie') AS category, t.kind, SUM(t.amount_cents) AS cents
        FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.date LIKE ? GROUP BY c.id, t.kind ORDER BY cents DESC""", (month + "%",))
    return {"month": month, "recettes_cents": rec, "depenses_cents": dep, "resultat_cents": rec - dep,
            "total_balance_cents": sum(a["balance_cents"] for a in accounts),
            "accounts": accounts, "by_category": by_cat}


def export_csv(db, q):
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Date", "Libellé", "Type", "Catégorie", "Compte", "Montant", "Note"])
    for t in reversed(list_transactions(db, q)):
        signed = t["amount_cents"] if t["kind"] == "recette" else -t["amount_cents"]
        w.writerow([t["date"], t["label"], t["kind"], t["category"] or "", t["account"], fmt_amount(signed), t["note"]])
    return "﻿" + out.getvalue()   # BOM : Excel ouvre correctement les accents


def import_csv(db, text, account_id):
    """Colonnes attendues : Date;Libellé;Montant (négatif = dépense). Catégorie facultative en 4e colonne."""
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text), delimiter=";" if ";" in text.split("\n")[0] else ",")
    count = 0
    for i, r in enumerate(reader):
        if i == 0 and r and not re.match(r"\d", r[0].strip()):
            continue  # en-tête
        if len(r) < 3:
            continue
        amount = r[2].strip()
        kind = "depense" if amount.startswith("-") else "recette"
        cat = None
        if len(r) > 3 and r[3].strip():
            row = db.execute("SELECT id FROM categories WHERE name=?", (r[3].strip(),)).fetchone()
            cat = row["id"] if row else None
        db.execute("INSERT INTO transactions(date,label,amount_cents,kind,category_id,account_id) VALUES(?,?,?,?,?,?)",
                   (parse_date(r[0]), r[1].strip(), parse_amount(amount.lstrip("+-")), kind, cat, account_id))
        count += 1
    db.commit()
    return count


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8") if n else ""

    def _route(self, method):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        parts = [p for p in url.path.split("/") if p]
        db = connect()
        try:
            if method == "GET" and not parts:
                return self._static("index.html")
            if method == "GET" and parts[0] != "api":
                return self._static("/".join(parts))
            if parts[0] != "api":
                return self._send(404, {"error": "Introuvable"})
            res, rid = parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            if res == "meta" and method == "GET":
                return self._send(200, {"accounts": rows(db, "SELECT * FROM accounts ORDER BY name"),
                                        "categories": rows(db, "SELECT * FROM categories ORDER BY kind, name")})
            if res == "dashboard" and method == "GET":
                return self._send(200, dashboard(db, q.get("month") or date.today().strftime("%Y-%m")))
            if res == "export" and method == "GET":
                return self._send(200, export_csv(db, q), "text/csv; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="compta.csv"'})
            if res == "import" and method == "POST":
                n = import_csv(db, self._body(), int(q.get("account_id") or 1))
                return self._send(200, {"imported": n})
            if res == "transactions":
                if method == "GET":
                    return self._send(200, list_transactions(db, q))
                if method == "POST":
                    cur = db.execute("INSERT INTO transactions(date,label,amount_cents,kind,category_id,account_id,note)"
                                     " VALUES(?,?,?,?,?,?,?)", clean_transaction(db, json.loads(self._body())))
                    db.commit()
                    return self._send(201, {"id": cur.lastrowid})
                if method == "PUT" and rid:
                    db.execute("UPDATE transactions SET date=?,label=?,amount_cents=?,kind=?,category_id=?,account_id=?,"
                               "note=? WHERE id=?", (*clean_transaction(db, json.loads(self._body())), rid))
                    db.commit()
                    return self._send(200, {"ok": True})
                if method == "DELETE" and rid:
                    db.execute("DELETE FROM transactions WHERE id=?", (rid,)); db.commit()
                    return self._send(200, {"ok": True})
            if res in ("accounts", "categories") and method == "POST":
                d = json.loads(self._body()); name = str(d.get("name", "")).strip()
                if not name:
                    raise ValidationError("Nom obligatoire")
                if res == "accounts":
                    db.execute("INSERT INTO accounts(name,opening_cents) VALUES(?,?)",
                               (name, parse_amount(d.get("opening") or "0")))
                else:
                    if d.get("kind") not in ("recette", "depense"):
                        raise ValidationError("Type invalide")
                    db.execute("INSERT INTO categories(name,kind) VALUES(?,?)", (name, d["kind"]))
                db.commit()
                return self._send(201, {"ok": True})
            return self._send(404, {"error": "Introuvable"})
        except (ValidationError, ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})
        except sqlite3.IntegrityError as e:
            return self._send(400, {"error": f"Donnée refusée (doublon ou référence) : {e}"})
        finally:
            db.close()

    def _static(self, name):
        path = os.path.realpath(os.path.join(STATIC, name))
        if not path.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(path):
            return self._send(404, {"error": "Introuvable"})
        ctype = {"html": "text/html", "js": "text/javascript", "css": "text/css"}.get(path.rsplit(".", 1)[-1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype + "; charset=utf-8")

    do_GET = lambda self: self._route("GET")
    do_POST = lambda self: self._route("POST")
    do_PUT = lambda self: self._route("PUT")
    do_DELETE = lambda self: self._route("DELETE")


def main():
    port = int(os.environ.get("PORT", 8000))
    connect().close()
    print(f"Compta disponible sur http://localhost:{port}  (base : {DB_PATH})")
    # 127.0.0.1 : accessible uniquement depuis votre ordinateur (données financières)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
