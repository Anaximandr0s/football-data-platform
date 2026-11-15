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
