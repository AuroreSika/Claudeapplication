# 📒 Compta

Application de comptabilité personnelle simple (France, en euros). Aucune dépendance : Python 3 suffit.

## Lancer
```bash
python3 compta.py
```
Puis ouvrir http://localhost:8000. Les données sont dans `compta.db` (SQLite, local, accessible uniquement depuis votre ordinateur).

## Fonctions
- Saisie de recettes et dépenses (modifier / supprimer), montants stockés en centimes
- Plusieurs comptes (banque, espèces…) avec solde initial, catégories personnalisables
- Tableau de bord mensuel : solde, recettes, dépenses, résultat, répartition par catégorie
- Recherche, export CSV (compatible Excel), import CSV `Date;Libellé;Montant[;Catégorie]` (montant négatif = dépense)

## Tests
```bash
python3 -m unittest discover -s tests
```

## Sauvegarde
Copiez simplement le fichier `compta.db`.

## Pistes suivantes
Budgets par catégorie, opérations récurrentes, pièces justificatives, TVA/factures (auto-entrepreneur), graphiques sur l'année.
