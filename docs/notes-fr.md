# Notes en français

Explications courtes de chaque phase, pour comprendre ce qui a été construit et pourquoi.

## FOO-06 : la page « Live match »

### Ce que fait la page

Pendant que `make replay` rejoue un match dans Kafka, la page affiche le terrain avec les 22 joueurs et le ballon, le score,
l'horloge, la possession, la dernière action importante (but, tir, tacle, faute) et la largeur et la longueur de chaque
équipe à la seconde en cours. Quand la caméra ne filme plus le terrain, la page l'écrit (« No tracking: camera off the
pitch ») au lieu de laisser des points figés.

### Les trois fichiers

| Fichier | Rôle |
|---|---|
| `app/streamlit/live.py` | le cœur : une fonction `apply(état, table, message, heure_kafka)` qui rend un nouvel état, et des fonctions qui lisent un état (score, possession, horloge, statut, forme de l'équipe). Aucun accès à Kafka ni à Streamlit : on le teste avec de simples listes de messages |
| `app/streamlit/live_feed.py` | la coquille : un seul consommateur Kafka pour toute l'application, dans un thread créé une fois (`st.cache_resource`). Il applique chaque message au bon match et garde le dernier état |
| `app/streamlit/pages/0_Live_match.py` | la page : un fragment Streamlit relancé chaque seconde (`st.fragment(run_every=1)`) qui prend une copie de l'état et dessine. Elle n'attend jamais Kafka |

### Pourquoi c'est construit ainsi

- **Noyau fonctionnel, coquille impérative.** Toute la logique (score, possession, trou de caméra) est dans des fonctions
  pures. La partie qui parle au réseau est mince et sans logique. Résultat : 8 tests de logique tournent en 0,1 s sans Kafka.
- **Un seul consommateur.** Sans `st.cache_resource`, chaque onglet ouvert créerait son propre consommateur et relirait
  tout. Avec, l'application en a un seul, partagé.
- **Le topic garde tous les anciens replays.** Le consommateur lit depuis le début, donc il voit aussi les replays d'avant.
  Chaque message est daté par Kafka ; un replay commence à l'heure de son message `matches`. Tout ce qui est plus ancien est
  ignoré. Comme chaque information garde sa date, l'ordre de lecture des topics n'a pas d'importance : un but du nouveau
  replay lu avant son message `matches` est conservé, un but d'un vieux replay lu en retard est ignoré.
- **Le trou de caméra est déduit du temps.** Pendant un trou, Kafka n'envoie rien : il n'y a pas de message « caméra
  coupée ». La page mesure le rythme du replay (environ 200 ms par seconde de match à x5) et, si plus rien n'arrive depuis
  plus de trois secondes de match, elle affiche le message et l'horloge continue de tourner.

### Les deux idées à retenir

1. **Séparer la logique du réseau.** Une fonction pure « message en entrée, nouvel état en sortie » se teste, se relit et se
   rejoue sans infrastructure.
2. **Dater les données plutôt que faire confiance à l'ordre.** Entre plusieurs topics Kafka, l'ordre n'est pas garanti ; la
   date de chaque message, si.

### Ce qu'on n'a pas choisi

- **Spark pour la page live** : inutile ici. Afficher la dernière position et compter les buts ne demande aucun calcul
  distribué. Spark Structured Streaming servira à FOO-08 (statistiques sur 5 minutes).
- **Lire seulement les nouveaux messages** (`latest`) : plus rapide au démarrage, mais une page ouverte au milieu d'un match
  n'aurait pas les buts déjà marqués.
- **Un service séparé** (une API ou une base) : interdit par la consigne, et pas nécessaire. Le conteneur `app` existant suffit.

### Limites connues

- Au premier affichage après le démarrage du conteneur `app`, le consommateur relit tout l'historique des topics (537 939
  messages en 16 s au plus, mesuré) ; la page montre des états intermédiaires pendant ce temps.
- Deux replays du même match lancés en même temps se mélangeaient. Depuis l'étape 6, chaque message porte un
  `replay_id` et la page ne montre que le replay le plus récent du match.
- La page bouge une fois par seconde : le mouvement fluide est prévu pour la page « Match replay ».

## Les tables Gold de MatchLens (section 7 de `product.md`)

### Ce qui a été ajouté

Neuf tables Gold qui répondent chacune à des questions de `product.md` (F1 à F8 pour les fans, C1 à C7 pour les
entraîneurs, S1 et E1-E2), et trois tables intermédiaires qui les préparent.

| Fichier | Rôle |
|---|---|
| `dbt/macros/attack_frame.sql` | `x_att` et `y_att` : le terrain vu par l'équipe de la ligne (distance à son propre but, sa gauche), plus les tiers et les couloirs. Écrit une fois, utilisé partout |
| `models/intermediate/int_events.sql` | les événements Silver avec `x_att` et deux drapeaux : passe progressive (+10 m vers l'avant) et action défensive (pressure + tackle + foul, jamais une course) |
| `models/intermediate/int_team_shape_second.sql` | pour chaque équipe et chaque seconde filmée : largeur, longueur, ligne défensive des joueurs de champ, et qui a le ballon |
| `models/intermediate/int_space_control_second.py` | un modèle **Python** dans dbt : chaque case d'une grille de 1 m appartient au joueur le plus proche ; part de HOME par seconde |
| `gold_match_timeline`, `gold_pressing`, `gold_space_control` | les chiffres par fenêtre de 5 ou 15 minutes (possession, field tilt, pressing, espace) |
| `gold_player_card`, `gold_player_fatigue` | un joueur par ligne : scores classés dans le match, fatigue entre le début et la fin |
| `gold_team_shape`, `gold_team_build_up`, `gold_team_profile` | une équipe par ligne : forme, progression du ballon, profil complet et écarts F7 |
| `gold_events` | tous les événements, courses comprises, prêts pour l'explorateur |

### Pourquoi c'est construit ainsi

- **Les formules viennent du document, pas du code.** Chaque table cite la question qu'elle sert. Pour vérifier qu'on
  n'a rien inventé, 27 chiffres ont été recalculés en pandas directement depuis les fichiers Parquet de Silver, sans dbt :
  tous identiques.
- **Les petits échantillons sont signalés, pas cachés.** Un joueur de moins de 20 minutes garde sa ligne, avec
  `is_eligible = false` et sans score ; une fenêtre avec moins de 60 secondes de possession connue a
  `possession_greyed = true`. L'application décidera comment griser.
- **Les tables intermédiaires évitent de répéter le calcul.** `x_att` ou la forme d'équipe par seconde servent à
  plusieurs tables ; on les calcule une fois. Elles ne sont pas exportées : ce ne sont pas des produits.
- **Le contrôle d'espace en Python, pas en SQL.** En SQL il faudrait comparer 7 140 cases x 22 joueurs x 4 400 secondes,
  soit 690 millions de lignes. En numpy, une seconde est une petite matrice : 8 s par match. Une première version qui
  traitait 64 secondes d'un coup était plus lente (43 s) car elle créait d'énormes tableaux temporaires : la version
  simple, seconde par seconde, est aussi la plus rapide.

### Les deux idées à retenir

1. **Une vérification indépendante vaut mieux qu'une relecture.** Recalculer quelques chiffres par un autre chemin
   (pandas au lieu de SQL, une autre formulation pour l'espace) attrape les erreurs que l'on ne voit pas en relisant son
   propre code.
2. **Comparer avec une source externe révèle les définitions cachées.** La largeur d'équipe est identique à celle de
   SkillCorner (écart médian 0,24 m). La longueur est 21 m plus courte : SkillCorner compte le gardien, notre formule
   (C1) ne compte que les joueurs de champ. Ce n'est pas une erreur, c'est une définition différente, à trancher.

### Ce qu'on n'a pas choisi

- **Une grille de 2 m** : prévue seulement si le calcul dépassait 60 s par match ; il prend 8 s.
- **Une bibliothèque de géométrie (Voronoi exact)** : une dépendance de plus pour une précision dont aucune question n'a
  besoin ; la grille de 1 m suffit.
- **Filtrer les joueurs non éligibles** : on perdrait l'information « ce joueur a trop peu joué », que la page doit
  montrer.

### Corrections après la revue

- **Longueur d'équipe** : on garde les joueurs de champ seulement, sous le nom « outfield block length ». SkillCorner
  compte le gardien ; avec lui, notre mesure retombe sur la sienne (écart médian 0,26 m). Ce n'est donc pas une erreur
  de calcul mais un choix de définition, écrit dans `product.md`.
- **Taux d'équipe** : divisés par les minutes filmées de l'équipe (secondes distinctes / 60), pas par la somme des
  minutes de ses joueurs, et montrés pour 90 minutes. Avant, le chiffre était 11 fois trop petit et sans unité parlante.
- **Vitesse maximale** : une vitesse relie deux positions à une seconde d'écart. Toutes les vitesses au-dessus de
  33 km/h avaient une position estimée à un bout. La carte joueur n'utilise plus que les vitesses dont les deux
  positions sont vues par la caméra : 33,0 km/h au plus dans m001 au lieu de 39,2.
- **Taux de réussite des passes progressives** : supprimé. Une passe ratée n'a pas de point de réception ; on garde
  alors la fin de la possession du passeur, à 1,5 m de son départ. Une passe ratée n'a donc presque jamais l'air
  « progressive », et le taux était gonflé (89 à 96 %). Les passes progressives réussies restent fiables.
- **Distance par minute** : gardée, avec le libellé « par minute de jeu filmé (surtout ballon en jeu) ».

### L'idée à retenir

**Un chiffre bizarre est souvent une question de définition des données sources.** Pour la vitesse comme pour les
passes, le calcul était juste ; c'est ce que la donnée contient (une position estimée, une fin de passe manquante) qui
faussait le résultat. Avant de corriger une formule, on regarde d'où vient chaque valeur.

## Étape 2 : le squelette du site MatchLens

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `app/streamlit/sitemap.py` | la carte du site : chaque page avec sa section, sa question et son public, et la fonction `menu(vue)` qui donne le menu d'une vue. Que des données et des fonctions pures : on le teste sans Streamlit |
| `app/streamlit/app.py` | le routeur : il construit le menu selon la vue choisie (`st.navigation`), dessine la barre latérale (choix de la vue, choix du match) et lance la page |
| `pages/home.py` | l'accueil : le logo texte, les cartes de match, « I am a Fan / I am a Coach » |
| `pages/match_library.py` | la bibliothèque : tous les matchs stockés ; choisir une ligne change le match de toutes les pages |
| `dbt/models/marts/gold_match_library.sql` | une ligne par match : équipes, score, date, compétition, part du match filmée |
| les autres pages | les anciennes pages déplacées (section 8.3 de `product.md`), et les nouvelles en « coming soon » avec leur question |

### Pourquoi c'est construit ainsi

- **Un seul endroit décrit le site.** Le menu, les titres et les questions viennent tous de `sitemap.py`. Ajouter une
  page, c'est ajouter une ligne ; les tests vérifient que chaque page a son fichier et sa question.
- **La vue et le match sont des clés simples de `st.session_state`, jamais des clés de widget.** Streamlit peut effacer
  la valeur d'un widget quand on change de page ; un test l'a montré (le match disparaissait). Les widgets lisent donc ces
  clés et y écrivent le nouveau choix.
- **Un thème, une fois.** Les couleurs (stade de nuit, vert pelouse) sont dans `.streamlit/config.toml`, avec un contraste
  vérifié, et les graphiques utilisent le même fond.

### L'idée à retenir

**Séparer la carte du site de son affichage.** Le « quoi » (quelles pages, dans quelle section, pour qui) est une donnée
pure et testée ; le « comment » (Streamlit, CSS) est une couche fine autour. C'est le même principe que le noyau
fonctionnel de la page live.

### Ce qu'on n'a pas choisi

- **Le dossier `pages/` comme menu automatique** (l'ancien système) : il ne sait ni grouper les pages en sections, ni
  montrer un menu différent selon la vue.
- **Deux sites séparés (fan et coach)** : LIVE, MATCHES et BEHIND THE DATA sont communs ; un seul site avec un menu qui
  change évite de tout dupliquer.

## Étape 3 : le terrain cliquable, la page Squad et la page joueur

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `app/web3d/pitch.js` | le terrain : un `<canvas>` dessiné en JavaScript, avec des couches (joueurs et ballon, match entier joué dans le navigateur, heatmap, tirs, passes, flèches d'attaque, message). Un clic sur un joueur renvoie son identifiant à Python |
| `app/streamlit/pitch.py` | l'enveloppe Python : un composant Streamlit « v2 » (HTML et JS passés en texte, sans compilation) qui prépare les données et rend le joueur cliqué |
| `app/streamlit/playerstats.py` | les formules joueur écrites une seule fois : position comme Silver (miroir, bornes du terrain), distance, efforts de sprint, vitesse max sur positions détectées, heatmap 6 x 4. Utilisées par la page live |
| `sections/squad.py` | l'effectif en cartes maillot (couleur de l'équipe, numéro, nom, poste), par équipe ; un clic ouvre la page joueur |
| `sections/player.py` | la page joueur, un seul fichier, deux modes : fan (carte, badges, 5 scores, terrain, autres matchs) et coach (valeurs brutes, seuils, fatigue, événements, classement) |

### Pourquoi c'est construit ainsi

- **Mesurer avant de construire.** Le premier test a mis un match entier (4 428 secondes) dans le composant, rafraîchi
  chaque seconde pendant 160 s. Résultat : 60 images par seconde, mémoire stable, 2 à 3 ms par rafraîchissement en
  mode live. Le match entier envoyé à chaque seconde reste fluide mais coûte 150 ms au serveur : le replay l'enverra
  une seule fois.
- **Une formule, un seul endroit.** Les stats live d'un joueur utilisent `playerstats.py`, qui reproduit les règles de
  Silver et de Gold. Un test rejoue tous les messages Kafka d'un match et compare à Gold : sur m001 et m002, les
  320 valeurs (32 joueurs x 5 valeurs x 2 matchs) sont identiques.
- **L'état reste pur, mais pas lent.** Garder chaque seconde de chaque joueur en copiant un dictionnaire à chaque
  message rendait le rattrapage Kafka 4 fois plus lent. Les secondes sont maintenant rangées en petits blocs figés de
  64 : un message ne copie que le dernier bloc.

### Les deux idées à retenir

1. **Tester le pire cas d'abord.** Si le composant n'avait pas tenu un match entier, il aurait fallu changer de
   technologie avant d'écrire les pages ; on l'a su en une heure au lieu de le découvrir à la fin.
2. **Un nom de dossier peut changer le comportement d'un outil.** Un dossier `pages/` active l'ancien mode multipage
   de Streamlit tant que le routeur n'a pas tourné : après un redémarrage, la première page ouverte montrait un menu
   brut. Le dossier s'appelle maintenant `sections/`.

### Ce qu'on n'a pas choisi

- **Plotly pour le terrain** : le clic marche aussi, mais chaque mouvement relance Python, donc pas de replay fluide.
- **Calculer les stats live dans Spark** : décidé en revue, Spark ne fera que les fenêtres de 5 minutes (étape 6).

## Étape 4 : la page « Match story » pour les fans

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `app/streamlit/story.py` | les phrases sous les graphiques. Chaque fonction rend la phrase **et** les chiffres Gold qui l'ont produite, pour qu'on puisse la vérifier |
| `app/streamlit/charts.py` | les frises du match (buts, danger créé, possession, territoire), alignées sur les mêmes minutes |
| `sections/match_story.py` | la page : score et frise des buts, « qui dominait » par tranche de 5 minutes, les 3 grandes différences, tirs et réseau de passes sur le terrain du composant, tableau côte à côte |
| `sections/live_match.py` | correction : « Now playing » ne montre que les matchs rejoués en ce moment, ouvre le match de la barre latérale s'il joue, et sinon dit « No match live right now » avec un lien vers Replay |

### Pourquoi c'est construit ainsi

- **Une phrase ne doit rien inventer.** Le texte et les chiffres sortent de la même fonction. La preuve relit Gold
  avec ses propres requêtes SQL et compare : sur m001 et m002, aucune des 23 phrases n'a un chiffre différent de Gold.
- **Décrire, pas expliquer.** Les phrases disent « had more », jamais « won because » : un écart de possession ne
  prouve pas pourquoi un match a été gagné. Un test vérifie que « because » et « won » n'apparaissent pas.
- **Lire la preuve comme un fan.** Les chiffres étaient justes, mais la relecture a trouvé trois défauts : « passs »,
  « the most of the team » alors qu'un coéquipier avait fait plus de passes, et une phrase qui répétait une autre.

### L'idée à retenir

**Une donnée juste peut quand même donner une phrase fausse.** « J. O'Shea, le plus impliqué » est vrai ; « celui qui
a fait le plus de passes » ne l'est pas. Il faut vérifier les chiffres **et** le sens des mots.

### Ce qu'on n'a pas choisi

- **Un modèle de langage pour écrire les phrases** : plus varié, mais impossible à garantir sans invention. Des modèles
  de phrases fixes, remplis avec Gold, se vérifient un par un.

## Correction : l'horloge du football et le nom des équipes

### Le problème

Nos minutes venaient de `ts`, qui compte les secondes depuis le coup d'envoi **sans s'arrêter** : il inclut le temps
additionnel de la première mi-temps et la pause. Le but de Clough apparaissait à la 49e, celui de Goodwin à la 65e,
alors que le compte rendu officiel dit 46' et 63'.

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `app/streamlit/clock.py` | une seule fonction pour la minute « comme à la télé » : 1re mi-temps 1'...45' puis 45+1', 2e mi-temps qui repart à 45:00 au second coup d'envoi, puis 90+1'. Utilisée par Live, Match story, la page joueur, Team analysis et les graphiques |
| `dbt/seeds/team_names.csv` | le nom que les supporters utilisent pour les 13 équipes des données SkillCorner (« Brisbane Roar », pas « Brisbane FC ») |
| `gold_match_library` | garde maintenant le début et la fin de chaque période, ce dont l'horloge a besoin |

### Pourquoi c'est construit ainsi

- **Une fonction, partout.** Si chaque page calculait sa minute, elles finiraient par ne plus être d'accord.
- **Vérifier contre une source extérieure.** Les tests internes ne pouvaient pas voir l'erreur : ils comparaient nos
  chiffres à nos chiffres. Le compte rendu du club et FBref l'ont montrée. Résultat : 6', 33', 43', 46', 62' pour m001
  (le club écrit 63' pour Goodwin : notre donnée place son tir à 16 min 31 s de la 2e mi-temps, la 62e minute).
- **Les noms dans une table, pas dans une règle.** Retirer « FC » donnerait « Sydney » pour Sydney FC ; une table de 13
  lignes vérifiée à la main est plus sûre.

### L'idée à retenir

**Un test qui compare le système à lui-même ne trouve pas une erreur de définition.** Il faut au moins une vérification
contre le monde réel.

## Étape 5 : les pages coach, la comparaison et deux nouveaux matchs

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `dbt/macros/football_window.sql`, `int_football_windows`, `clock.window_index` | les fenêtres de 5 et 15 minutes repartent à chaque coup d'envoi : 0-5' ... 40-45', 45+ (le temps additionnel), 45-50' ... 85-90', 90+. Une seule règle, en SQL et en Python, vérifiées égales par un test ; Spark la reprendra à l'étape 6 |
| `app/streamlit/coach.py` | les phrases des pages coach, chacune avec les chiffres Gold qui l'ont produite |
| `sections/team_analysis.py` | forme avec et sans ballon, pressing par 15 minutes, construction et côté d'attaque, contrôle de l'espace, tirs et réseau de passes |
| `sections/physical_fatigue.py` | la distance par minute de chaque joueur dans chaque fenêtre, et qui a baissé en fin de match |
| `sections/event_explorer.py` | tous les événements filtrés (équipe, type, joueur, phase, mi-temps, minutes), en flèches ou en carte de chaleur, un résumé, un face-à-face et le momentum |
| `sections/compare_matches.py` | une équipe dans les matchs choisis, avec le lieu et l'adversaire écrits |
| m003, m004 | Perth Glory 1-3 Brisbane Roar et Sydney FC 4-1 Adelaide United, passés par toute la chaîne |

### Pourquoi c'est construit ainsi

- **Des fenêtres « football », pas « horloge ».** Avec `ts // 300`, la 2e mi-temps commençait au milieu d'une
  fenêtre. Les totaux n'ont pas bougé (passes, buts, secondes) : seules les frontières ont changé.
- **Le contrôle qualité a fait son travail.** Le nouveau match m003 avait 4 secondes à 43-52 km/h, des sauts depuis une
  position estimée. Les contrôles ont bloqué Gold ; tu as choisi de mettre ces vitesses à null dans Silver, et le
  contrôle du job vérifie le compte.
- **Une phrase montre ses chiffres.** « Spell le plus intense : 90+ avec 2,60 » ne disait pas que la fenêtre était
  courte ; la phrase donne maintenant les comptes (actions et passes) à côté du ratio.

### L'idée à retenir

**Ajouter des données réelles est le meilleur test.** Deux matchs de plus ont trouvé une vitesse impossible et un
écart de 3 s au début d'une mi-temps, que les deux premiers matchs ne montraient pas.

### Corrections après la revue de l'étape 5

- **`speed_rejected`** : Silver garde la vitesse à null au-dessus de 40 km/h, mais marque la ligne ; Soda vérifie qu'une
  ligne marquée a bien une vitesse nulle, et la page Data quality montre le nombre par match (4 pour m003).
- **Pressing grisé** : une fenêtre où l'adversaire a fait moins de 10 passes est grisée et ne peut plus être « le
  moment le plus intense ». Seuil écrit dans `product.md`.
- **Comparaison avant/après** : la Gold du code de `main` et celle de cette branche, construites sur le même Silver,
  sont identiques ligne à ligne pour les 12 tables qui ne devaient pas changer ; les 4 tables à fenêtres gardent les
  mêmes totaux par match.

L'idée à retenir : **marquer plutôt qu'effacer en silence**. Une valeur corrigée doit laisser une trace qu'on peut
compter et montrer.

## Spark Structured Streaming : les statistiques sur 5 minutes (FOO-08, étape 6)

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `ingestion/producer_foot.py` | chaque message d'un replay porte l'en-tête Kafka `replay_id`, par exemple `m001-20261116T101503Z` (le match et l'heure de départ) ; Bronze le garde dans `kafka_replay_id`, Silver le retire |
| `spark/streaming/live_stats.py` | le job Spark : il lit `foot-tracking`, `foot-ball` et `foot-events`, compte par replay et par fenêtre de football, et écrit dans le topic `foot-live-stats` ; lancé par `make streaming` sur le cluster Spark |
| `spark/streaming/rows.py` | les formules (celles de Gold) et la règle « fenêtre terminée », en Python pur, testées sans Spark |
| `sections/live_match.py` | sous le terrain, le panneau « Every 5 minutes » : les 4 dernières fenêtres, « complete » ou « in progress » |

### Pourquoi c'est construit ainsi

- **`replay_id` plutôt que deviner avec l'heure.** Avant, la page devinait un nouveau replay à partir des dates des
  messages. Un identifiant posé une fois par le producteur est sûr : deux replays de m001 l'un après l'autre donnent deux
  séries de fenêtres séparées, et toutes deux égales à Gold (vérifié). Le mettre dans un en-tête Kafka, et non dans le
  JSON, ne change pas les tables du contrat.
- **Des valeurs complètes, pas des incréments.** Chaque message de `foot-live-stats` contient la valeur entière d'une
  fenêtre (« 412 m depuis le début de la fenêtre »), jamais « +12 m ». Si un message est envoyé deux fois, la seconde
  copie écrase la première au lieu de s'ajouter. Le topic est « compacté » : Kafka garde au moins le dernier message de
  chaque clé, comme une table.
- **Le checkpoint.** Spark écrit dans MinIO (`s3a://checkpoints/streaming-5min`) les offsets Kafka déjà lus et l'état des
  agrégations. Après un arrêt, il repart exactement de là. Vérifié : le job arrêté à la minute 40 d'un replay x10 puis
  relancé donne les mêmes chiffres que Gold, sans rien compter deux fois.
- **La marge de 10 secondes (grace).** Les trois topics n'arrivent pas au même rythme : un événement de la minute 4:59
  peut arriver après la position de 5:01. Une fenêtre n'est donc marquée « complete » que quand le tracking a dépassé sa
  fin de 10 secondes de match (ou la dernière seconde du match). Avant, elle reste « in progress » et ses chiffres
  peuvent encore bouger.
- **Fenêtres de football, pas fenêtres Spark.** Les fenêtres de temps de Spark (`window()`) coupent l'horloge toutes les
  5 minutes ; nos fenêtres repartent à chaque coup d'envoi (45+, 45-50'). Le job appelle donc `clock.window_index`, la
  même fonction que l'app et que la macro dbt.

### Les idées à retenir

1. **Un flux qui peut rejouer doit être idempotent.** Envoyer la valeur complète avec une clé stable rend une répétition
   sans danger.
2. **« Fini » est une décision.** Dans un flux, une fenêtre n'est jamais sûre d'être terminée ; on choisit une règle
   (fin + 10 s) et on l'affiche.

### Ce qu'on n'a pas choisi

- **Les fenêtres de temps de Spark avec un watermark** : elles suivent l'horloge réelle, pas la mi-temps du football.
- **Le mode `complete` de Spark** (renvoyer toutes les fenêtres à chaque micro-batch) : plus simple, mais tout l'historique
  repart toutes les 5 secondes. Le mode `update` n'envoie que les fenêtres qui ont changé.
- **Écrire dans Gold en direct** : Gold reste construit par dbt après le match ; le live ne fait qu'afficher.

### Limites connues

- Le job ne lit que les nouveaux messages : il doit tourner avant le début du replay (écrit dans le script de démo).
- Il ne garde que 10 minutes de messages pour enlever les doublons ; un doublon arrivé plus tard compterait deux fois.
- Les distances sont arrondies au dixième ; quand la somme tombe exactement sur ,x5, Spark et DuckDB n'arrondissent pas
  du même côté (0,1 m d'écart sur 9 des 450 lignes joueur, sommes non arrondies identiques).
- Un replay lancé au milieu d'une fenêtre (la démo part de 04:56) marque la fenêtre 0-5' « complete » avec seulement
  4 secondes : « complete » veut dire « plus rien n'arrivera », pas « fenêtre pleine ». Possession et pressing y sont
  grisés (« - »).

### Corrections après la revue de l'étape 6

- **`PYSPARK_PYTHON`** est posé par `tests/spark/conftest.py` sur l'interpréteur qui lance les tests : Spark ne peut pas
  mélanger deux versions de Python (3.11 pour le pilote, 3.12 pour les workers). `make test` et la CI passent donc sans
  variable à poser à la main.
- **Un test Soda** ajoute `kafka_replay_id` aux cinq tables Silver et vérifie que les cinq contrôles de schéma échouent.
  On a aussi vérifié que le test lui-même échoue si on retire la colonne d'une des listes (un test qui ne peut pas
  échouer ne prouve rien).
- **m003 à x60** dans le job de streaming : 502 lignes, toutes égales à Gold. C'est le match aux 4 vitesses au-dessus de
  40 km/h : la règle de Silver est bien reprise dans le flux.
- **Pressing en deux colonnes** sur la page Live : « - - - » quand les deux équipes étaient grisées était illisible.


## Dagster : la chaîne d'un match lancée par le coup de sifflet final (étape 8)

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `dagster/football_platform/assets.py` | les étapes d'un match : `bronze` (tout est dans MinIO), `silver` (le job Spark), `soda_silver` (contrôle bloquant), les modèles dbt (Gold), `soda_gold` (bloquant, un résultat par table), `match_report` |
| `dagster/football_platform/sensors.py` | le capteur `replay_end` (fin d'un replay -> run du match), le planning de 3 h, et le journal des runs pour l'app |
| `dagster/football_platform/replays.py`, `soda.py` | les règles en Python pur : quand un replay est fini, ce que veut dire un résultat Soda ; testées sans Dagster qui tourne |
| `dagster/Dockerfile`, `dagster.yaml` | une image pour le serveur web, le démon et les runs (Java 17 + Spark, dbt, Soda) ; la file des runs et le pool `duckdb` |
| service `bronze-writer` | l'écriture Kafka -> MinIO tourne seule dès `make up`, plus besoin d'un terminal |
| `sections/pipeline_lineage.py`, `sources_limits.py` | les deux pages « Behind the data » |

### Pourquoi c'est construit ainsi

- **Chaque étape lance la commande du projet** (`check_bronze`, le job Silver, `dbt build`, `run_checks.py`) : un run
  Dagster fait exactement ce que fait `make`. Dagster ajoute l'ordre, les reprises, le blocage et l'historique.
- **Un contrôle « bloquant »** : si Soda échoue sur Silver, Gold n'est pas construit. Vérifié : avec des données
  abîmées exprès (`inject_damage`), 6 contrôles Silver échouent, Gold, `soda_gold` et le rapport ne sont pas exécutés, et
  le fichier Gold garde la même date et la même taille.
- **Le capteur lit Kafka** : un replay est fini quand son tracking atteint la dernière seconde du match (`p2_end_ts` de
  son propre message `foot-matches`, reconnu par `replay_id`). La clé du run est le `replay_id` : un replay ne lance
  jamais deux runs.
- **Bronze « complet »** : le writer ne valide ses offsets Kafka qu'après l'envoi vers MinIO. Quand son retard est nul,
  tout ce que Kafka contient est dans Bronze ; l'étape `bronze` attend ce moment.
- **Un seul Gold à la fois** : tous les matchs sont dans un seul fichier DuckDB, qui n'accepte qu'un écrivain. Les
  étapes qui l'ouvrent partagent le pool `duckdb` (limite 1) : si deux matchs finissent ensemble, le second attend.
- **Spark depuis un conteneur** : le « driver » Spark tourne dans le conteneur `dagster-daemon` ; les workers le
  joignent par ce nom (`spark.driver.host`). Vérifié dans les logs du worker : `spark://CoarseGrainedScheduler@dagster-daemon`.
- **Rejouer un run ne change rien** : relancer m001 a réécrit le fichier Gold, et les 16 tables sont identiques ligne à
  ligne (15 294 lignes, même empreinte).

### Les idées à retenir

1. **L'orchestrateur ne calcule pas, il enchaîne.** Les calculs restent dans Spark, dbt et Soda ; Dagster décide quand
   et dans quel ordre, et s'arrête au premier contrôle qui échoue.
2. **Idempotent = on peut relancer sans peur.** Chaque étape remplace son résultat au lieu d'ajouter : c'est ce qui rend
   les reprises automatiques (retries) sans danger.

### Ce qu'on n'a pas choisi

- **Lancer les conteneurs existants par le socket Docker** : plus léger, mais le conteneur Dagster aurait eu le contrôle
  de toute la machine.
- **Gold non partitionné, déclenché après Silver** : plus propre dans le graphe, mais un contrôle Silver raté y bloque
  Gold moins visiblement.
- **Postgres pour l'historique de Dagster** : utile à plusieurs machines ; SQLite suffit ici.

### Un bug trouvé en route

Le contrôle Silver « vitesses rejetées = vitesses > 40 km/h dans Bronze » comptait les lignes de Bronze **avant**
dédoublonnage. m003, rejoué trois fois, donnait 4 contre 12 et Silver refusait le match. Le compte se fait maintenant une
fois par clé (joueur, seconde). Le premier lancement automatique l'a montré : c'est l'intérêt d'un pipeline qui rejoue.

### Limites connues

- Après un changement de modèle dbt, relancer `make dagster` (le graphe est lu dans `manifest.json`).
- Un replay déjà fini avant le premier démarrage du capteur n'est pas repris.
- Le démon a besoin de mémoire : deux Silver en même temps, environ 3 Go sur les 4 Go permis.

## Replay : rejouer un match stocké (étape 7, R1 et S1)

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `dbt/models/marts/gold_replay_frames.sql` | nouvelle table Gold : une ligne par seconde suivie et par objet (22 joueurs et le ballon), dans le repère de Silver, avec le possesseur du ballon et la part d'espace de HOME (S1) |
| `app/streamlit/replayer.py` | Python pur : le match pour le navigateur (positions en centimètres entiers), et le panneau « jusqu'à maintenant » (score, possession, fenêtres terminées, stats d'un joueur) |
| `app/web3d/pitch.js` | le terrain joue le match **dans le navigateur** : lecture/pause, 0,25x à 8x, curseur avec les buts, mouvement fluide, traces, noms, « détectés seulement », Voronoi |
| `app/web3d/d3-delaunay.min.js` | la bibliothèque des cellules de Voronoi, gardée en fichier (licence ISC, dans `NOTICE`) |
| `sections/replay.py` | la page : le terrain, le panneau, le graphique de contrôle de l'espace avec un trait « maintenant » |
| `live.py`, `playerstats.flip_xy` | la page Live dessine aussi dans le repère de Silver : HOME attaque à droite sur tous les terrains du site |

### Pourquoi c'est construit ainsi

- **Le match part une seule fois.** 1,7 à 2,1 Mo de JSON par match (0,55 Mo compressé). Si Python le renvoyait à
  chaque mise à jour du panneau, ce serait lent. Il l'envoie une fois ; ensuite il envoie seulement sa clé, et le
  navigateur garde sa copie. Après un changement de page, le navigateur n'a plus la copie : il la redemande.
- **10 Hz ou 1 Hz ? La réponse se voit.** Nous gardons 1 position par seconde. « Smooth movement » trace la ligne
  droite entre deux secondes consécutives, au rythme de l'écran (60 images par seconde) ; on ne trace jamais à travers
  un trou de caméra. En coupant l'option, on voit les sauts bruts de 1 Hz. L'interpolation est dessinée, jamais
  stockée : les chiffres viennent toujours des vraies secondes.
- **Le panneau ne connaît pas le futur.** Il ne montre que les fenêtres de 5 minutes déjà terminées : une fenêtre en
  cours afficherait des valeurs Gold qui incluent des secondes pas encore jouées.
- **Centimètres, pas décimètres.** Le premier essai en décimètres perdait la 2e décimale de Silver (le test l'a vu :
  -1,25 m devenait -1,2 m). En centimètres entiers, la position dessinée est exactement celle de Silver.
- **Un seul repère pour tout le site.** Live montrait l'image de la caméra (les équipes changent de côté à la
  mi-temps), les autres pages le repère de Silver. Maintenant Live retourne la 2e mi-temps comme Silver : la même
  seconde est au même endroit sur Live et sur Replay (vérifié : 132 positions, écart 0).

### Les idées à retenir

1. **Calculer là où c'est le moins cher.** Animer 60 fois par seconde se fait dans le navigateur ; les statistiques
   restent en Python, avec les formules déjà testées contre Gold.
2. **Une interpolation est un dessin, pas une donnée.** Elle rend le mouvement lisible, mais aucun chiffre n'en vient.

### Ce qu'on n'a pas choisi

- **Garder le 10 Hz de SkillCorner** : 10 fois plus de données à envoyer, pour un mouvement que l'interpolation rend
  déjà fluide à l'écran ; et les statistiques de Gold sont calculées à 1 Hz.
- **Un graphique Plotly animé** : chaque image et chaque cellule de Voronoi vivraient dans la figure, trop lourd.
- **Laisser Live dans le repère de la caméra** : plus proche de la télévision, mais un même joueur aurait changé de
  côté entre Live et Replay.

### Limites connues

- Le panneau suit la lecture toutes les 2 secondes (et tout de suite à la pause, au saut ou au clic) : à 8x, il a
  environ 16 secondes de match de retard pendant la lecture.
- Une fenêtre de 5 minutes en cours n'apparaît qu'une fois terminée.
- Le premier affichage d'un match prend environ 1 seconde (lecture et préparation des 100 000 lignes, ensuite en cache).

## Corrections et finitions du Replay (2026-11-17)

### Ce qui a changé

| Fichier | Rôle |
|---|---|
| `gold_player_card.sql`, `playerstats.py` | vitesse max (F5) : la meilleure vitesse **tenue deux secondes de suite**, avec les trois positions vues par la caméra |
| `gold_events.sql`, `goalmoment.py` | `goal_ts` : la seconde où le ballon est dans le but ; le score de Live et de Replay change à ce moment |
| `gold_replay_frames.sql` | ajoute la hauteur du ballon `z` et le poste du joueur (pour repérer le gardien) |
| `pitch.js` | « BUT ! » (filet qui clignote, bandeau, pause de 3 s), marques des tirs, ballon plus visible avec ombre selon sa hauteur, gardien en carré, noms des équipes près des flèches, légende, aide sur chaque bouton, dernier événement, clavier (espace, flèches) |
| `viz.possession_bar` | la barre de possession avec le nom des équipes, la même sur Live et Replay |

### Pourquoi c'est construit ainsi

- **Une vitesse doit durer.** À 1 Hz, une vitesse relie deux positions à une seconde d'écart : une seule position
  fausse donne une seconde trop rapide (39,5 km/h pour T. Okamoto). Une vitesse tenue deux secondes demande trois
  bonnes positions de suite. Résultat : maximum 33,1 km/h sur les 4 matchs, plus personne au-dessus de 36 km/h. Le
  prix : les vrais rapides perdent environ 1 km/h (A. Goodwin 32,8 → 31,9).
- **Le but, c'est le ballon qui entre.** L'événement « but » est daté au début de l'action. On cherche dans les 10
  secondes suivantes la première seconde où le ballon a passé la ligne entre les poteaux ; si on ne le voit jamais
  (ballon extrapolé, caméra qui coupe pour le ralenti), la seconde où il est le plus près du but. 8 buts sur 15 sont
  trouvés par la première règle, 7 par la seconde ; ils arrivent 0 à 7 s après le début de l'action.
- **La même règle à deux endroits, vérifiée.** Gold (SQL) et Live (Python) appliquent la règle chacun de leur côté ; un
  test vérifie qu'ils donnent la même seconde, et sur les 15 vrais buts aussi.
- **Un clic ne doit pas se perdre.** À 8x, le navigateur envoie le temps à Python plusieurs fois par seconde ; un
  « déclencheur » (trigger) pouvait se perdre entre deux exécutions. Le clic est maintenant une valeur d'état numérotée
  `{joueur, n}` : Python l'applique une fois, même s'il la voit plusieurs fois.

### Les idées à retenir

1. **Une donnée bizarre cache souvent une règle trop naïve.** 39,5 km/h n'était pas une faute de calcul, mais une
   règle qui faisait confiance à une seule seconde.
2. **Dater un événement, c'est choisir quel instant compte.** Début de l'action, tir, ballon dans le but : trois
   secondes différentes ; le score doit suivre le ballon.

### Ce qu'on n'a pas choisi

- **Ajouter la fin de l'action de SkillCorner (`frame_end`) au contrat** : il aurait fallu changer toutes les couches
  et rejouer les 4 matchs, pour un instant (le tir) qui reste avant l'entrée du ballon. Tu as choisi le ballon le plus
  proche du but.
- **Recalculer `max_speed_kmh` aussi** : c'est la « vitesse max » brute du cahier des charges (FOO-04), avec son jumeau
  en streaming ; elle reste, mais l'app ne l'affiche plus comme une vitesse max.

### Limites connues

- Pour 7 buts, la seconde est une estimation (ballon le plus près du but), pas une observation.
- Sur Live, quand le ballon n'est jamais vu dans le but, le score change jusqu'à 10 s après le début de l'action
  (il faut attendre la fin de la fenêtre).
- À 8x, il faut viser vite : la zone de clic grandit avec la vitesse (+16 px à 8x).

## La page « Data quality » en six dimensions (2026-11-17)

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `soda/dimensions.yml` | chacun des 210 contrôles Soda reçoit une dimension (complétude, unicité, validité, cohérence, exactitude) et un nom en anglais simple ; un test échoue si un contrôle n'en a pas |
| `spark/silver` (`quality_report`) | à chaque match, Silver écrit `data/quality/silver_<match>.json` : lignes préparées, lues dans Bronze, gardées, positions corrigées, vitesses rejetées |
| `docs/external_checks.yml` | ce que disent les sources officielles (clubs, AAP, Fox Sports, ESPN, FBref, avec les liens) ; la page compare avec Gold à chaque ouverture |
| `scripts/quality_evidence.py` (`make evidence`) | refait les comparaisons Live = Gold, Streaming = Gold, mesure le délai du live, explique les runs Dagster en échec, et écrit le tout avec la date et le commit |
| `app/streamlit/quality.py`, `sections/data_quality.py` | la page : verdict, six cartes, grille match x dimension, couverture caméra, runs, « Caught by our checks », tous les contrôles |

### Pourquoi c'est construit ainsi

- **Juger notre pipeline, pas la caméra.** La complétude dit si nous avons gardé tout ce que nous avons reçu
  (100 % : 423 540 lignes sur 423 540, et Gold les contient toutes). Que la caméra n'ait vu que 76 % du match est une
  limite de la source : on l'affiche, on ne la note pas.
- **Une seule source pour chaque fait.** Les minutes officielles des buts sont dans un fichier YAML lu par deux pages ;
  nos minutes sont recalculées depuis Gold à chaque fois. Si nos données changent, l'exactitude change aussi.
- **Une preuve doit pouvoir être refaite.** `make evidence` refait les comparaisons au lieu de recopier un résultat :
  le fichier dit quand et sur quel commit. Et il a trouvé un vrai bug : le live comptait les vitesses au-dessus de
  40 km/h que Silver retire (m003, deux joueurs). Corrigé dans `playerstats.py`.
- **« Exact » veut dire « comme au moins une source ».** Les sources ne sont pas d'accord entre elles (Goodwin 62' pour
  Adelaide, 63' pour Brisbane ; Klein 50' pour Brisbane, 51' pour Fox Sports et ESPN). 15 buts sur 15 sont exacts.

### Les idées à retenir

1. **Les six dimensions répondent à six questions simples.** Rien ne manque ? Rien en double ? Des valeurs possibles ?
   Les tables d'accord entre elles ? D'accord avec le monde réel ? Assez récent ?
2. **Une vérification qu'on ne peut pas refaire n'est qu'une affirmation.** D'où la date, le commit et le script.

### Ce qu'on n'a pas choisi

- **Des attributs Soda (`attributes:`) pour la dimension** : Soda Core les valide contre Soda Cloud ; un fichier à
  nous, testé, est plus simple.
- **Noter la couverture caméra** : ce serait punir la source, pas notre travail.

### Limites connues

- La possession de m002 est à 1,1 point de FBref (62,9 % contre 64 %) : orange. Avant, le tableau arrondissait à 63 % et
  disait « à 1 point ».
- L'unicité, la cohérence et la validité viennent de contrôles qui couvrent tous les matchs à la fois : un échec met
  tous les matchs en rouge.
- Le délai du live mesure Kafka jusqu'à l'application (0,32 s, 95 %) ; l'affichage ajoute jusqu'à 1 s (la page se
  redessine chaque seconde). Le délai jusqu'à l'écran n'est pas mesuré.

## Un site lisible au projecteur et par tout le monde (2026-11-16)

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `.streamlit/config.toml`, `theme.py` | thème clair par défaut, thème sombre au choix ; toutes les couleurs du site au même endroit, avec les formules de contraste |
| `tests/app/test_theme.py` | mesure les contrastes (règle WCAG) : texte au moins 4,5:1, couleurs d'équipe et graphiques au moins 3:1 |
| `assets/matchlens-logo.svg` | le logo, un seul fichier utilisé partout (barre latérale et accueil) : le remplacer suffit |
| `glossary.py` | six mots expliqués au survol (xThreat, field tilt, space control, pressing, outfield block, tracked) ; un test vérifie que chacun est utilisé |
| `charts.py` | `finish` met le texte des graphiques à 14 px ; `balance` dessine possession et territoire comme une ligne autour de 50 % ; `ranking` remplace l'ancien graphique matplotlib sombre |
| `lineage.py` | le schéma simple du pipeline (chemin d'après-match et chemin live), et le sens de chaque colonne Gold lu dans le contrat de données |
| `app/web3d/pitch.js` | points blancs autour des joueurs ; passes réussies en blanc plein, ratées en or pointillé ; panneau du Replay qui suit le thème |
| `docs/img/readability/` | une capture de chaque page en clair, six en sombre, et le terrain vu par un daltonien |

### Pourquoi c'est construit ainsi

- **Un projecteur écrase les couleurs sombres.** Fond clair, texte foncé, texte des graphiques à 14 px au lieu de 11.
  Les contrastes sont mesurés par un test, pas estimés à l'œil : texte 15,5:1 en clair, 16,1:1 en sombre.
- **Une seule paire de couleurs pour les équipes.** Domicile toujours bleu `#0072B2`, extérieur toujours vermillon
  `#D55E00`, dans tous les matchs. Ces deux couleurs de la palette Okabe-Ito restent différentes pour un daltonien
  rouge-vert : la capture `pitch_deuteranopia.png` le montre (bleu contre jaune-olive). Avant, les couleurs de maillot
  changeaient d'un match à l'autre et pouvaient se ressembler. Le nom de l'équipe est toujours écrit à côté de la couleur,
  car une couleur seule ne suffit jamais.
- **Le terrain reste vert dans les deux thèmes.** Un terrain clair rendrait les points blancs invisibles ; le contour
  blanc des points se lit à 13,5:1 sur la pelouse.
- **Le CSS hérite de la couleur du texte.** Streamlit annonce le thème choisi avec un temps de retard ; des couleurs
  fixes seraient fausses pendant ce temps. Avec `color: inherit` et des gris translucides, la même règle marche partout.
- **Trop de flèches, plus de lecture.** Au-delà de 100 événements, l'explorateur montre la carte de chaleur et propose
  de filtrer ; la vue « Directions » donne une flèche moyenne par zone.
- **Comparer d'un coup d'œil, puis en détail.** Le radar donne le profil ; ensuite chaque mesure a ses barres, sa valeur
  écrite et une ligne « higher = ... ». Chaque axe du radar va du minimum au maximum de toutes les équipes de tous les
  matchs stockés, pour que la forme ne dépende pas des matchs choisis.

### Les idées à retenir

1. **Contraste = rapport de luminance**, de 1:1 (même couleur) à 21:1 (noir sur blanc). 4,5:1 pour du texte, 3:1 pour
   un trait ou une surface de graphique.
2. **Ne jamais coder une information par la couleur seule** : nom à côté de la couleur, pointillés pour les passes
   ratées, croix pour les exécutions du pipeline en échec.

### Ce qu'on n'a pas choisi

- **Garder les couleurs de maillot** : fidèles au club, mais deux maillots proches (ou rouge contre vert) deviennent
  illisibles pour les daltoniens. Le petit carré couleur maillot à côté du nom était optionnel ; il n'a pas été ajouté.
- **Un terrain clair en thème clair** : il fallait alors d'autres couleurs de points, et le daltonisme redevenait un
  problème.
- **Un radar seul pour comparer** : joli, mais on y lit mal une valeur exacte ; il est donc suivi des barres.

### Limites connues

- Le thème sombre suit le réglage du système ou le menu de Streamlit ; il n'a été vérifié que dans Chrome.
- La simulation de daltonisme est un calcul (matrice de Machado, 2009), pas un test avec de vraies personnes.
- Les figures matplotlib de `viz.py` (carte de chaleur, tirs, réseau de passes) ne sont plus utilisées par aucune page ;
  elles sont encore là, avec leurs tests.

## La surveillance : Prometheus, Alertmanager, Grafana (2026-11-17)

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` (profil `monitoring`) | 8 services : Prometheus, Alertmanager, Grafana et 5 « exporters » ; `make monitoring` les lance, `make monitoring-stop` les arrête |
| `monitoring/prometheus/` | quoi lire toutes les 15 s (`prometheus.yml`), les 14 alertes (`rules/alerts.yml`), les objectifs de service (`rules/recording.yml`) |
| `monitoring/alertmanager/` | à qui envoyer quoi, et le modèle de l'e-mail (couleurs, boutons vers Grafana, Dagster et la page Data quality) |
| `monitoring/grafana/` | la source de données et les 4 tableaux de bord, écrits par `build_dashboards.py` |
| `monitoring/exporter/pipeline_exporter.py` | notre exporter : les runs Dagster (GraphQL), les tests dbt, les contrôles Soda par dimension, la progression de Spark, la fraîcheur de Gold par match |
| `spark/streaming/progress.py` | Spark écrit après chaque lot où il en est (lignes par seconde, retard sur Kafka) |
| `app/streamlit/live_feed.py` | le consommateur Kafka de la page Live publie son retard et le délai du direct |

### Les mots à connaître

- **Prometheus** est une base de données de nombres dans le temps (des « séries temporelles »). Il ne reçoit rien : toutes
  les 15 secondes, il va lire une page `/metrics` sur chaque service (on dit qu'il « scrape »). Il garde 7 jours, puis
  efface.
- **Un exporter** est un petit programme qui traduit l'état d'un système en page `/metrics`. node-exporter pour la
  machine, cAdvisor pour les conteneurs, kafka-exporter pour Kafka, blackbox pour savoir si un site répond. Le nôtre
  traduit Dagster, dbt et Soda.
- **Une règle d'alerte** est une requête PromQL avec un seuil et une durée : « la mémoire dépasse 90 % de la limite
  depuis 2 minutes ». Quand elle est vraie, Prometheus prévient Alertmanager.
- **Alertmanager** décide quoi envoyer : il regroupe (6 contrôles Soda en échec = un seul e-mail), répète toutes les
  4 heures si le problème dure, envoie un e-mail « RESOLVED » quand il est réglé, et se tait sur les conséquences quand
  la cause est connue (Kafka arrêté : pas d'alerte de retard en plus).
- **Grafana** dessine les séries de Prometheus. Ses tableaux de bord sont des fichiers JSON chargés au démarrage, pas
  des clics : ils sont dans git comme le reste.
- **Un SLO** (objectif de niveau de service) est une promesse chiffrée, mesurée sur une période : « 95 % des messages du
  direct arrivent en moins de 2 s, sur 7 jours ». Le tableau « Service levels » en montre cinq, en vert si la promesse
  est tenue, en rouge sinon.

### Pourquoi c'est construit ainsi

- **Tout est un fichier.** Une alerte, un tableau de bord ou un seuil se change dans le code, se relit dans une
  pull request et revient après un `docker compose down`. Grafana refuse même les modifications à la souris.
- **Deux lecteurs de Kafka ne laissent pas de trace dans Kafka.** Spark garde sa position dans son checkpoint et la page
  Live ne valide rien : un exporter Kafka ne peut pas voir leur retard. Chacun le publie donc lui-même, et les trois
  retards apparaissent sous un seul nom, `football:consumer_lag`.
- **Une seule règle de fraîcheur.** L'exporter appelle la fonction de la page Data quality (`quality.freshness`) au lieu
  de la recopier : la page et l'alerte ne peuvent pas se contredire.
- **Un e-mail doit dire quoi faire.** Chaque alerte a un titre, ce qui s'est passé, où (match, service, dimension), quoi
  vérifier, et des boutons qui ouvrent le bon tableau de bord ou le run Dagster.
- **Les secrets restent dans `.env`.** Alertmanager ne lit pas les variables d'environnement : un petit script remplit
  sa configuration au démarrage et met le mot de passe dans un fichier à l'intérieur du conteneur.

### Ce qui a été mesuré (2026-11-17)

- **Run endommagé** (`inject_damage`) sur m001 : échec à 10:46:53 UTC, alerte reçue par Alertmanager à 10:47:24, deux
  e-mails envoyés à 10:47:35 (42 s ; l'objectif était 2 minutes) : « Dagster run failed » et « Soda check failed (6) »,
  chaque contrôle avec sa dimension. 0 échec d'envoi.
- **E-mail « RESOLVED »** : après le replay complet de m001, le run normal a réussi à 11:03:32, les alertes se sont
  éteintes à 11:03:56, les e-mails « RESOLVED » sont partis à 11:05:20 (Alertmanager attend 2 minutes entre deux
  e-mails d'un même groupe).
- **bronze-writer arrêté** : alerte à +85 s, e-mail « Container down » à +113 s après l'arrêt.
- **Pendant un replay de m001 à 10x** : 173 messages Kafka par seconde, délai du direct p95 0,72 s, retard 0 pour Spark.
  Les lots Spark durent environ 9 s pour un déclencheur de 5 s : Spark suit (lignes traitées = lignes reçues), mais
  sans marge.
- **Mémoire de la surveillance** : 655 Mio pendant le replay (avant les corrections ci-dessous), 538 Mio au repos
  après, sur 4 792 Mio pour les 18 conteneurs. Grafana 227, cAdvisor 111, Prometheus 82, notre exporter 50,
  Alertmanager 24, les trois autres exporters 43.

### Ce que les preuves ont trouvé (et qui est corrigé)

- **De faux e-mails « RESOLVED ».** Un run encore en file d'attente n'a pas d'heure de début ; la fonction de
  fraîcheur a planté, toute la page `/metrics` de l'exporter est tombée, et Prometheus a cru que toutes les alertes
  du pipeline étaient finies : deux faux « RESOLVED » à 10:58:35, puis de nouveau « PROBLEM ». Correction : un run pas
  encore commencé est ignoré (comme dans `runs.json`), chaque source est lue à part, et une source illisible déclenche
  sa propre alerte (`ExporterSourceFailing`) au lieu d'effacer les autres. Deux tests reproduisent le bug.
- **Un conteneur arrêté vu 6 minutes plus tard.** cAdvisor date lui-même ses mesures ; Prometheus garde alors une
  série disparue pendant 5 minutes. `honor_timestamps: false` : 85 s au lieu de 6 minutes.
- **Grafana près de sa limite mémoire.** Grafana 13 lance un processus par source de données livrée (CloudWatch, Loki,
  Tempo... 17 à 31 Mio chacun) ; seules celles de Prometheus servent : les autres sont désactivées, et la limite est
  fixée d'après la mesure (340 Mio au repos, limite 512 Mio).

### Les idées à retenir

1. **Mesurer, alerter, montrer sont trois métiers** : Prometheus mesure, Alertmanager prévient, Grafana montre. On peut
   perdre Grafana sans perdre une seule alerte.
2. **Une alerte utile est rare et actionnable** : un seuil, une durée (pas d'alerte pour un pic d'une seconde), et une
   phrase qui dit quoi faire.

### Ce qu'on n'a pas choisi

- **Les alertes de Grafana** au lieu d'Alertmanager : tout serait dans Grafana, mais les alertes dépendraient de
  l'outil d'affichage ; Alertmanager sait aussi regrouper et faire taire les conséquences.
- **Un Pushgateway** (les jobs poussent leurs chiffres) : utile pour des jobs courts, mais Dagster garde déjà
  l'historique ; il suffit de le lire.
- **L'exporter JMX de Kafka** : plus de détails sur le broker, mais un agent Java à ajouter dans le conteneur Kafka ;
  kafka-exporter a suffi (il fonctionne avec Kafka 4.3).
- **Un jeton pour les métriques MinIO** : c'est le bon choix en production (voir `monitoring/README.md`) ; ici le port
  n'est ouvert qu'à la machine elle-même.

### Limites connues

- Personne ne surveille le surveillant : si Prometheus ou Alertmanager s'arrête, aucune alerte ne part.
- 7 jours d'historique, puis plus rien ; juste après le premier démarrage, les SLO « sur 7 jours » couvrent bien moins.
- Les liens des e-mails pointent vers `localhost` : ils ne s'ouvrent que sur la machine qui fait tourner la plateforme.
- Un redémarrage volontaire (`docker compose restart`) compte comme un redémarrage dans l'alerte ContainerRestarting.

## Mesurer les performances : `make benchmark` (2026-11-17)

### Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `scripts/benchmark.py` (`make benchmark`) | joue les scénarios (vitesses x1, x10, x60 ; charge de 1 à 4 matchs ; redémarrages) et enregistre les mesures brutes dans `data/benchmark/<date>.json` |
| `scripts/benchmark_report.py` (`make benchmark-report`) | fonctions pures : percentiles, temps de vidage, limite de charge, verdicts des SLO, goulots d'étranglement ; écrit `docs/performance.md` et 4 graphiques |
| `monitoring/exporter/pipeline_exporter.py` | le scénario en cours devient une annotation dans Grafana ; les runs lancés exprès pour un test (tag `purpose`) sont comptés à part |

### Les mots à connaître

- **Le débit** (throughput) : combien de messages par seconde traversent un composant. On le compare à la **cible** :
  les lignes que le match contient par seconde de jeu, fois la vitesse du replay.
- **La latence** : le temps entre deux moments d'un même message, ici l'envoi par le producteur et l'état mis à jour
  dans la page Live. Kafka garde l'heure d'envoi de chaque message, ce qui permet de la mesurer exactement.
- **Les percentiles** : p50 est la valeur du milieu, p95 la valeur sous laquelle se trouvent 95 % des mesures, p99
  99 %. La moyenne cache les cas lents ; p95 et p99 les montrent. Un objectif (SLO) s'écrit donc sur p95.
- **Le retard** (lag) d'un lecteur : les messages écrits dans Kafka qu'il n'a pas encore lus. S'il oscille, le lecteur
  suit ; s'il ne fait que monter, il décroche.
- **Le temps de vidage** (drain) : après l'arrêt des producteurs, combien de secondes il faut à un lecteur pour tout
  lire. Au-delà de 30 s, on considère qu'il a atteint sa limite.
- **Le test de charge** cherche la **capacité** : on monte la charge par paliers (1, 2, 3, 4 matchs en même temps) et on
  note le premier palier où un lecteur décroche.
- **Le temps de rétablissement** : après le redémarrage d'un service en plein replay, combien de temps avant que son
  retard revienne à la normale.

### Pourquoi c'est construit ainsi

- **Mesures et rapport séparés.** Le benchmark dure environ 50 minutes ; le rapport se régénère en quelques secondes
  depuis le fichier de résultats, qui est versionné. Personne n'écrit les chiffres à la main.
- **La latence mesurée avec le code de la page.** Une sonde lit Kafka comme la page Live (`live.route`, même taille de
  lot) et mesure chaque message ; l'histogramme de l'application sert de contre-vérification.
- **Un garde-fou.** Toutes les 1 s, le script lit la mémoire, le CPU et le disque de la machine ; il arrête les
  producteurs si la machine est en danger (moins de 1,5 Gio libres, CPU > 95 % pendant 30 s, disque < 10 %).
- **Le capteur Dagster mis en pause pendant la charge**, dans un `try/finally` : sinon dix runs du pipeline
  s'empileraient et fausseraient les paliers suivants. À la fin, Gold est reconstruit une fois et la fraîcheur vérifiée.
- **Les runs de test à part.** Un run lancé exprès (démo de données abîmées, reconstruction du benchmark) porte le tag
  `purpose` ; l'objectif « 95 % de runs réussis » ne compte que les runs normaux, et le taux brut est affiché à côté.

### Ce qui a été mesuré (2026-11-17, détail dans `docs/performance.md`)

- **Débit** : le producteur tient la cible à chaque vitesse (x60 : environ 1 000 messages/s pour un match, 4 100 pour
  quatre matchs en même temps, 96 % de la cible).
- **Latence du direct** : p95 0,49 s à x1, 0,51 s à x10, 0,53 s à x60. Objectif (< 2 s) tenu.
- **Fenêtre de 5 minutes complète** : 13 à 15 s après la fin de la fenêtre (p50), dont 10 s d'attente voulue.
- **Coup de sifflet final → Gold** : 14,7 min pour m001, objectif (10 min) manqué : `silver` a duré 787 s.
- **Charge** : jusqu'à 4 matchs en même temps à x60, aucun lecteur ne décroche ; Spark est le plus lent (22,7 s pour
  rattraper son retard, 115 346 messages au plus fort), loin devant bronze-writer (8,6 s) et la page Live (0,6 s).
- **Rétablissement** : bronze-writer redémarré revient à la normale en 47 s, le pilote Spark en 20 s.

### Ce que le benchmark a trouvé (rien n'est corrigé dans cette branche)

- **Les lots de Spark durent 11,2 s (p50) pour un déclencheur de 5 s** : Spark suit, mais en retard sur son propre
  rythme, et c'est le premier lecteur à souffrir quand la charge monte.
- **Silver relit toutes les copies gardées dans Bronze.** Chaque replay ajoute une copie complète d'un match ; m001 en
  avait 27 (2 millions de lignes lues pour en garder 97 416) et Silver a mis 13 minutes au lieu de 3,6 le matin. Le
  benchmark lui-même rejoue m001 six fois : chaque mesure rend la suivante plus lente.
- **Le consommateur de l'application est plus lent que la sonde qui exécute le même code** (p95 2,9 s contre 0,49 s
  à x1) : depuis la branche monitoring, il mesure son retard dans sa boucle de lecture et bloque la lecture pendant ce
  temps. Une régression à corriger dans une branche à part.
- **bronze-writer ignore le signal d'arrêt** : Docker attend 10 s puis le tue ; chaque redémarrage coûte 10 s de plus.
- **Le capteur Dagster reprend là où il s'était arrêté** : le mettre en pause ne suffit pas, il faut avancer son
  curseur, sinon chaque replay joué pendant la pause lance son run à la reprise (dix runs la première fois).

### Les idées à retenir

1. **On mesure avec des percentiles, pas des moyennes** : p95 dit ce que vit l'utilisateur dans 95 % des cas.
2. **Un test de charge cherche le premier composant qui décroche** : ici Spark, avant Kafka et la page Live.
3. **Mesurer change ce qu'on mesure** : un benchmark qui écrit dans le système (copies dans Bronze) doit le dire.

### Ce qu'on n'a pas choisi

- **Un outil de charge générique** (k6, Locust) : il mesure des requêtes HTTP, pas un flux Kafka ni un pipeline ; le
  vrai producteur et le code de la page mesurent ce que vivent nos utilisateurs.
- **Corriger pendant qu'on mesure** : une mesure sert de référence ; les corrections viendront dans leurs branches et
  `make benchmark` dira si elles aident.

## Corriger ce que le benchmark a trouvé : `fix/performance` (2026-11-17)

### Ce qui a été changé

| Fichier | Changement |
|---|---|
| `ingestion/bronze_writer.py` | un dossier par replay dans Bronze (`replay_id=<replay>`) ; arrêt propre sur SIGTERM : il écrit ce qu'il a en mémoire, valide ses offsets et s'arrête |
| `spark/silver/bronze_to_silver.py` | Silver ne lit que le dernier replay complet d'un match (celui que Dagster lui donne, sinon le plus récent complet) et garde son `replay_id` |
| `soda/checks/silver.yml`, `docs/contrat_donnees.md` | nouvelle garantie : chaque match vient d'un seul replay ; le contrat décrit le nouveau chemin de Bronze |
| `dbt/models/staging/*.sql` | `replay_id` est retiré avant Gold : Gold ne change pas |
| `scripts/bronze_prune.py` (`make bronze-prune KEEP=3`) | garde les 3 derniers replays complets par match, montre ce qu'il supprimerait, et ne supprime qu'avec `DELETE=yes` |
| `spark/streaming/live_stats.py`, `docker-compose.yml` | 2 cœurs pour le streaming (4 pour le worker), 2 partitions de shuffle |
| `app/streamlit/live_feed.py` | le retard de la page Live est mesuré par un autre thread, avec son propre consommateur |

### Pourquoi c'est construit ainsi

- **Un dossier par replay plutôt qu'un filtre.** Avec un filtre sur `kafka_replay_id`, Spark devrait quand même lister
  et ouvrir chaque fichier de chaque replay ; avec un dossier, il ne regarde même pas les autres. Résultat : Silver
  lit environ 97 000 lignes au lieu de 2 millions pour m001, en 73 s au lieu de 787 s.
- **Échouer bruyamment plutôt que deviner.** Un match qui n'a pas de replay dans le nouveau format n'est pas
  reconstruit : Silver dit de le rejouer. Relire l'ancien format aurait caché le problème.
- **Mesurer avant de changer.** Le premier suspect pour Spark (200 partitions de shuffle) était faux : il y en avait
  déjà 4. Le découpage de chaque lot a montré que le checkpoint sur MinIO ne coûte que 0,25 s ; le vrai coût était le
  travail lui-même, fait par trois requêtes sur un seul cœur. Deux cœurs ont divisé la durée d'un lot par 2,5.
- **Un réglage à la fois, sur le même replay.** Deux cœurs : 12,5 s → 5,0 s. Deux partitions : 25 % de mieux, mesuré
  deux fois pour être sûr. RocksDB : plus lent (7,0 s), donc pas gardé. Le checkpoint reste sur MinIO : sur un vrai
  cluster, il doit de toute façon être sur un stockage partagé, que tous les nœuds lisent.
- **Silver garde son cœur.** Avec 2 cœurs pour le streaming, Silver attendait avec 0 cœur (vu dans l'interface de
  Spark) : le worker passe donc de 2 à 4 cœurs.

### Avant / après (`make benchmark`, détail dans `docs/performance.md`)

| Mesure | Avant | Après |
|---|---|---|
| Silver pour le match à x60 | 787 s | 78 s |
| Coup de sifflet final → Gold | 14,7 min (objectif manqué) | 2,5 min (tenu) |
| Lot Spark, p50 / p95 | 11,2 / 17,0 s | 3,8 / 4,9 s |
| Spark, rattrapage à 4 matchs | 22,7 s | 10,0 s |
| Page Live (application), p95 à x1 | 2 925 ms | 518 ms (la sonde : 489 ms) |
| Redémarrage de bronze-writer | 11 s | 2 s |
| Runs réussis (normaux, 7 jours / depuis la dernière correction) | 88,0 % / – | 90,9 % / 96,2 % |

Les résultats de Spark n'ont pas changé : `make evidence` trouve toujours les 10 021 valeurs des 2 017 fenêtres
complètes égales à Gold. `make bronze-prune KEEP=3 DELETE=yes` a libéré 205,9 Mio de Bronze (251,9 → 46,0 Mio).

### Les idées à retenir

1. **Partitionner, c'est permettre de ne pas lire** : le chemin d'un fichier peut porter une information (ici le
   replay) qui évite de l'ouvrir.
2. **Un arrêt propre** : un programme qui reçoit SIGTERM doit finir son travail en cours et s'arrêter ; sinon Docker le
   tue après 10 s, et ce qu'il avait en mémoire est relu (ou perdu, s'il avait déjà validé).

### Ce qu'on n'a pas choisi

- **Supprimer les anciens replays automatiquement** : Bronze est l'historique brut ; on le taille à la main, après
  avoir vu ce qui serait supprimé.
- **Changer la logique des fenêtres** (la fonction Python qui place chaque ligne dans sa fenêtre, l'état qui ne se vide
  jamais) : ce serait plus rapide, mais les résultats pourraient changer ; c'est pour une autre branche.

### Limites connues

- L'étape Bronze de Dagster attend que le retard **total** de bronze-writer soit nul : si des replays s'enchaînent, elle
  attend en vain et échoue après 180 s (vu sur m001). Il faudrait attendre seulement les messages de ce replay.
- L'état de l'agrégation Spark ne se vide jamais (pas de watermark sur l'agrégation) : 384 000 lignes après une
  journée de replays. Il grossit avec chaque replay.
