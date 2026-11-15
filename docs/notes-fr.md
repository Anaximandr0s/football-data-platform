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
