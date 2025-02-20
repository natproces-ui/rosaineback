# RosainebotBackend

Ce projet est une API REST développée avec FastAPI et MongoDB pour la gestion d’un système de suggestion de réponses aux emails.

## Structure du projet

- **database.py**  
  Ce fichier est utilisé pour **déclarer et définir les collections** MongoDB (ex. : users, email, email_messages, service, intents_classification, knowledge_base, responses, etc).

- **schemas.py**  
  Ce fichier contient les **modèles Pydantic** qui décrivent les attributs et la structure de chaque collection.

- **main.py**  
  Ce fichier implémente les **endpoints CRUD** pour chaque API. Il contient les routes permettant de créer, lire, mettre à jour et supprimer des documents dans chacune des collections.

## Fonctionnement global

1. **Connexion et définition des collections**  
   La connexion à MongoDB se fait dans `database.py` où toutes les collections sont déclarées.

2. **Définition des attributs**  
   Les attributs de chaque collection sont définis dans `schemas.py` à l’aide de modèles Pydantic, garantissant ainsi la validation des données entrantes.

3. **Implémentation des API**  
   Les opérations CRUD (Create, Read, Update, Delete) sont implémentées dans `main.py`. Chaque endpoint interagit avec les collections définies dans `database.py` en utilisant les modèles de `schemas.py`.
