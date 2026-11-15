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
- Deux replays du même match lancés en même temps se mélangent.
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
