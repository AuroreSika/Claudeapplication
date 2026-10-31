import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import compta as c


class Montants(unittest.TestCase):
    def test_parse(self):
        for raw, exp in [("12,50", 1250), ("1 234.5", 123450), ("0,05", 5), ("7", 700), ("9,99 €", 999)]:
            self.assertEqual(c.parse_amount(raw), exp)

    def test_invalid(self):
        for raw in ["", "abc", "1,234", "-5"]:
            with self.assertRaises(c.ValidationError):
                c.parse_amount(raw)

    def test_format(self):
        self.assertEqual(c.fmt_amount(-1250), "-12,50")
        self.assertEqual(c.fmt_amount(5), "0,05")

    def test_date(self):
        self.assertEqual(c.parse_date("31/01/2026"), "2026-01-31")
        with self.assertRaises(c.ValidationError):
            c.parse_date("31/02/2026")


class Base(unittest.TestCase):
    def setUp(self):
        self.db = c.connect(":memory:")

    def add(self, d, label, amount, kind, cat=None):
        self.db.execute("INSERT INTO transactions(date,label,amount_cents,kind,category_id,account_id) VALUES(?,?,?,?,?,1)",
                        (d, label, c.parse_amount(amount), kind, cat))


class Calculs(Base):
    def test_dashboard(self):
        self.add("2026-03-01", "Salaire", "2000", "recette")
        self.add("2026-03-05", "Courses", "49,90", "depense")
        self.add("2026-02-10", "Loyer", "600", "depense")
        d = c.dashboard(self.db, "2026-03")
        self.assertEqual((d["recettes_cents"], d["depenses_cents"], d["resultat_cents"]), (200000, 4990, 195010))
        self.assertEqual(d["total_balance_cents"], 200000 - 4990 - 60000)

    def test_export_import_roundtrip(self):
        self.add("2026-03-05", "Café", "2,50", "depense")
        text = c.export_csv(self.db, {})
        self.assertIn("-2,50", text)
        db2 = c.connect(":memory:")
        self.assertEqual(c.import_csv(db2, "Date;Libellé;Montant\n05/03/2026;Salaire;1 500,00\n06/03/2026;Pain;-1,20\n", 1), 2)
        self.assertEqual(c.dashboard(db2, "2026-03")["resultat_cents"], 150000 - 120)

    def test_filtre_mois(self):
        self.add("2026-03-05", "A", "1", "depense")
        self.add("2026-04-05", "B", "1", "depense")
        self.assertEqual([t["label"] for t in c.list_transactions(self.db, {"month": "2026-03"})], ["A"])
        self.assertIn("A", c.export_csv(self.db, {"month": "2026-03"}))

    def test_validation(self):
        with self.assertRaises(c.ValidationError):
            c.clean_transaction(self.db, {"kind": "depense", "label": "", "amount": "1", "date": "2026-01-01", "account_id": 1})


if __name__ == "__main__":
    unittest.main()
