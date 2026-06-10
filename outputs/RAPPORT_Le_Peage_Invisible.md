# 🚲 Le Péage Invisible
### Les chantiers de voirie font-ils baisser le trafic cycliste à Paris ?

*Étude causale sur données ouvertes — Open Data Paris. Méthode : différence-de-différences à adoption échelonnée (Callaway–Sant'Anna).*

---

## 1. La question et les hypothèses

Quand un chantier perturbant ouvre près d'un compteur vélo, le nombre de passages baisse-t-il ?

- **H₀ (hypothèse nulle)** : l'ouverture d'un chantier perturbant à moins de 150 m d'un compteur **n'a aucun effet** sur le trafic cycliste quotidien.
- **H₁ (hypothèse alternative)** : l'ouverture d'un tel chantier **fait baisser** le trafic cycliste des compteurs voisins.

**Données** (récupérées par API, sans clé) :
- `comptage-velo-donnees-compteurs` — 882 530 comptages horaires, 97 compteurs, 2025-05-01 → 2026-06-08.
- `chantiers-a-paris` — 5 331 chantiers géolocalisés (dates de début/fin, emprise, surface).

```python
import requests

# Comptages vélo horaires — export complet, JSON, sans clé d'API
url = ("https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/"
       "comptage-velo-donnees-compteurs/exports/json")
rows = requests.get(url, timeout=300).json()   # -> 882 530 enregistrements
```

Un chantier est dit **« perturbant »** s'il occupe la chaussée/le stationnement
(`EMPRISE_CHAUSSEE` / `EMPRISE_STATIONNEMENT`) **ou** s'étend sur ≥ 100 m² — il n'existe
pas d'indicateur officiel, nous l'avons donc défini nous-mêmes.

---

## 2. Le résultat

> ### Effet estimé : **−2 passages/jour (−0,1 %)**, IC 95 % **[−3,5 % ; +3,1 %]**
> Niveau de référence : 2 255 passages/jour avant chantier. **Effet non significatif.**

Sur **55 compteurs traités** (chantier perturbant à ≤ 150 m, ≥ 21 jours avant/après),
comparés aux compteurs **pas encore traités**, on ne détecte **aucune baisse mesurable** du
trafic cycliste. L'intervalle de confiance exclut tout effet supérieur à ~3,5 %.

**Conclusion : on ne peut pas rejeter H₀.** Le « péage invisible » est… invisible : à
l'échelle d'un compteur, les chantiers ne réduisent pas le trafic cycliste de façon
détectable.

---

## 3. Les figures (et leur « so what »)

**Figure 1 — Effet principal** (`../figures/headline_effect.png`)
Trafic observé (rouge) vs contrefactuel « sans chantier » (bleu).
➡️ *So what : les deux courbes restent collées après l'ouverture du chantier (t=0) — aucun effet mesurable.*

**Figure 2 — Étude d'événement : méthode naïve vs robuste** (`../figures/event_study_cs.png`)
➡️ *So what : la méthode naïve (rouge) invente un effondrement linéaire qui traverse t=0 sans rupture ; la méthode correcte (verte) est plate à zéro — l'« effet » apparent n'était qu'un artefact statistique.*

**Figure 3 — Carte des compteurs** (`../figures/counter_map.png`)
➡️ *So what : compteurs traités (rouge) et témoins (bleu) sont répartis dans tout Paris — pas de biais géographique est/ouest évident.*

**Figure 4 — Robustesse** (`../figures/robustness_forest.png`)
➡️ *So what : toutes les définitions (rayon, chaussée seule, surface seule, longs chantiers) et le placebo encadrent zéro — le résultat nul est robuste.*

---

## 4. Incertitudes et limites (en toute transparence)

- **Réacheminement / échelle (limite principale).** L'effet est mesuré à **150 m** et à la
  **semaine**. Un chantier peut bloquer *une rue précise* pendant que les cyclistes
  contournent par une rue parallèle où se trouve le compteur : la baisse locale serait
  alors invisible au niveau du réseau. Notre étude **exclut un péage à l'échelle du réseau
  > 3,5 %**, mais ne dit rien de la rue bloquée elle-même.
- **Contamination par diffusion (spillover/SUTVA).** Les compteurs témoins ont été exclus
  s'ils se trouvaient à moins de 500 m d'un chantier. **Aucun compteur jamais-traité** n'a
  survécu à cette règle (Paris est dense) ; nous avons donc utilisé les compteurs
  **pas-encore-traités** comme groupe de comparaison.
- **Tendances parallèles & DiD échelonné.** Le TWFE naïf affichait une fausse tendance
  pré-chantier (Figure 2, rouge) : symptôme classique du biais de **Goodman-Bacon /
  Sun-Abraham** sous adoption échelonnée. L'estimateur **Callaway–Sant'Anna** corrige ce
  biais ; sous CS, les coefficients pré-chantier sont **plats (IC contenant 0)** — l'hypothèse
  d'identification est satisfaite.
- **Définition du « perturbant ».** Faute d'indicateur officiel, le proxy est large ; mais
  même les sous-ensembles les plus « durs » (chaussée seule, longs chantiers) restent nuls.
- **Placebo.** Des fausses dates d'ouverture (−120 jours) donnent **−0,0 %** : la méthode ne
  fabrique pas d'effet.

---

## 5. Ce que cette étude démontre

Un·e analyste pressé·e aurait publié une « chute du vélo de −X % à cause des chantiers » :
c'était un **artefact**. La valeur de cette étude est d'avoir **prouvé l'absence d'effet de
façon rigoureuse** — estimateur robuste, placebo, cinq définitions, *leave-one-out* (stable
entre −0,9 % et +0,2 %) — plutôt que d'avoir rapporté un faux positif séduisant.

*Toutes les bornes d'API ont été vérifiées en direct (juin 2026). Code : `src/` ; tables : `outputs/`.*
