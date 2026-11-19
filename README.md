# StagePlay Lite — première compilation automatique Windows

**Prototype de lecteur vidéo double écran (pas encore StagePlay Pro).**

## Compiler sans installer Python

1. Créer un dépôt GitHub **privé**, par exemple `stageplay`.
2. Importer **les fichiers et dossiers de ce projet**, en conservant `.github/workflows/windows-build.yml`.
3. Ouvrir l'onglet **Actions** du dépôt. Accepter si nécessaire l'activation des workflows.
4. Cliquer sur **Fabriquer StagePlay pour Windows**, puis **Run workflow**, ou laisser se lancer le workflow au premier push sur `main`.
5. Après une exécution réussie (coche verte), cliquer sur l'exécution, puis, en bas dans **Artifacts**, télécharger **StagePlayLite-Windows-portable**.
6. Décompresser le ZIP téléchargé et lancer `StagePlayLite.exe`. **Conserver tous les fichiers décompressés autour du .exe**.

Note : le téléchargement d'un artifact Actions nécessite en général d'être connecté à GitHub. Le nom du menu peut varier selon l'interface.

## Fonctionnalités réellement présentes dans ce prototype

- Playlist vidéo (MP4, MOV, MKV, AVI, WEBM, etc.), réorganisation, sauvegarde JSON.
- Sélection écran et lecture en plein écran.
- Commandes GO, pause, stop, next et BLACK (arrêt + écran noir).
- Ratio, crop central, zoom et volume par vidéo.
- Auto-next optionnel, désactivé par défaut.

## Pas encore développés

- **Images, PDF, PowerPoint** dans une playlist unique.
- Preview indépendante, préchargement sans changement de sortie, transitions, freeze réel.
- Contrôle Companion/Stream Deck, profils de canvas LED et crop X/Y indépendants.
- Cette application n'est pas validée pour diffusion critique en spectacle.

## En cas d'erreur de compilation

Dans l'exécution GitHub Actions, cliquer l'étape en échec pour lire le log. Le workflow installe VLC 64 bits automatiquement, puis PyInstaller. Les machines GitHub sont changeantes : un ajustement de dépendances peut être nécessaire.

## Licence / sécurité

Les binaires VLC et leurs plugins sont redistribués dans le dossier portable. Avant toute distribution au public, vérifier les conditions de licence des composants VLC et inclure les mentions requises. L'exécutable n'est pas signé numériquement ; Windows SmartScreen peut afficher un avertissement. Ne désactiver aucune protection sans avoir vérifié les fichiers.
