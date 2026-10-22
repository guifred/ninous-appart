# Ninou’s appart · Bruxelles

Recherche d’appartements à louer et à vendre, carte, photos, pépites et favoris.

Le site est hébergé gratuitement sur GitHub Pages. Les critères, favoris et estimations personnelles restent dans le navigateur de chaque visiteur. Le bouton **Appliquer les filtres** parcourt les annonces déjà collectées ; il ne lance pas de collecte supplémentaire. Les photos supplémentaires sont celles déjà présentes dans le catalogue, avec accès à l’annonce d’origine.

## Collectes

Le workflow **Collecter et publier** lance les collectes vers 10 h et 17 h, heure de Bruxelles, et tient compte du changement d’heure. GitHub peut retarder les tâches programmées. Dans un dépôt public, GitHub désactive les planifications après 60 jours sans activité : vérifier l’onglet Actions si les dates n’avancent plus.

Pour relancer : onglet **Actions → Collecter et publier → Run workflow**, option de collecte cochée. Les nouvelles annonces sont publiées après le traitement. Les tarifs gratuits concernent GitHub Pages sur dépôt public et les runners GitHub standard ; aucun service payant n’est configuré.

Les données publiques sont enregistrées dans `public-data/` pour conserver les dates de première détection entre deux exécutions. Les annonces périmées sont exclues de l’interface. Les indisponibilités des sources restent indiquées ; la couverture n’est pas exhaustive. Les collecteurs n’utilisent ni proxy ni contournement de contrôle d’accès.

## Développement

Python 3.12, sans dépendance externe. Les filtres utilisent JavaScript natif.

```sh
python3 -m unittest discover -s tests -p 'test_public_site.py'
node --test tests/public-search.test.cjs
python3 public_site/build.py --output _site
python3 -m http.server 8766 --directory _site
```

Le script `scripts/bootstrap_cloud.py` est réservé à GitHub Actions afin de ne pas remplacer les préférences de l’installation locale.

Les annonces, leurs photos et leurs logos restent attribués aux agences ; consulter la source pour confirmer les informations et la disponibilité. Le dépôt public ne contient pas de paramètres personnels, de journaux du Mac, de mots de passe ou de justificatifs privés.
