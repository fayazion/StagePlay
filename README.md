# STAGEPLAY V2 — prototype Windows portable pour la régie événementielle

**Statut : version de test. Ne pas utiliser comme unique source en prestation sans répétition matérielle.**

V2 construit sur StagePlay Lite V1 (dont la sortie plein écran a été validée par l'utilisateur). Le lecteur vidéo est toujours basé sur LibVLC ; les images et les pages PDF sont rendues nativement par Qt / PyMuPDF. Le programme ne nécessite aucune connexion Internet pour fonctionner.

## Nouveautés V2

- Playlist **vidéos + images + PDF multipages** : MP4/MOV/MKV/AVI/WMV/etc., PNG/JPEG/BMP/TIFF/WebP et PDF.
- Deux écrans : **écran opérateur** et **sortie plein écran indépendante** sur écran sélectionné.
- Boutons `GO`, `PAUSE`, `STOP`, `BLACK`, `LOGO`, `FREEZE` et sélection de cues (sans GO automatique à la sélection).
- **BLACK et LOGO sont des masques** : ils n'appellent **ni stop ni seek**. La vidéo continue en arrière-plan, sauf si elle était déjà en pause ou atteint sa fin. Pour un BLACK qui fige la lecture : appuyer sur PAUSE puis BLACK.
- **LOGO** charge une image PNG/JPG et la maintient sur PROGRAM. Une seconde pression restaure la sortie.
- **Points IN/OUT** (secondes et centièmes) par vidéo. `SET IN/OUT = position` sur le clip à l'antenne. Précision limitée par la lecture/seek et le polling (pas frame-accurate).
- **LOOP OFF / ONE / ALL** : ONE répète la cue courante ; ALL enchaîne et reprend toute la playlist ; OFF ne déclenche automatiquement la prochaine cue que si `Auto-next` est activé. **OFF et Auto-next OFF par défaut**.
- Pour les **images et PDF**, durée en secondes optionnelle (`0 = HOLD`, infini), navigation manuelle des pages PDF (`Page précédente/suivante`), PDF affiché en vectoriel pré-rendu page par page.
- **Cadrage par cue** : FIT / FILL / STRETCH / ORIGINAL, zoom 0,25× à 4×, pan X/Y, crop gauche/droite/haut/bas. Pour la vidéo, on taille et décale la fenêtre native de rendu dans un conteneur qui clippe ; cela évite de dépendre uniquement des options VLC de crop qui ne fonctionnaient pas en V1. **À valider sur une machine Windows**.
- **Canvas logique personnalisé** (ex. 2304×1152, 2:1) : ajuste la zone de composition dans la résolution **actuelle de Windows**, sans modifier le signal physique HDMI/EDID.
- Shows JSON sauvegardés avec **chemins relatifs** si possible, réglages par cue, boucle, dimensions de canvas et logo. Lecture des playlists JSON de la V1 ; les anciens réglages de ratio/crop VLC ont été remplacés par les nouveaux modes de cadrage.

## Limites connues

- **PPT/PPTX non pris en charge dans cette version** : convertir préalablement la présentation en PDF. Les animations/vidéos intégrées du PowerPoint ne sont pas conservées en PDF.
- Pas de vidéo en Preview pour l'instant (la PREVIEW texte/image/PDF reste légère et n'active aucun deuxième décodeur vidéo).
- Une seule sortie PROGRAM, pas de double sortie indépendante pour l'instant.
- Pas de synchonisation Genlock, pas de garantie de frame-accurate, pas de zérobascule entre vidéos.
- `FREEZE` utilise une pause du média vidéo. Ce n'est pas encore un vrai snapshot de la frame actuelle.
- Sur une fin vidéo naturelle, VLC peut effacer la dernière frame. À un point OUT manuel, l'application essaie de faire une pause approximative.
- L'overlay BLACK/LOGO masque l'image, mais **ne coupe pas automatiquement le son**. Couper au mélangeur ou mettre le média en pause/mute selon le besoin.
- Lorsque le canvas logique a un autre ratio que le signal Windows, il y a des marges noires sur la sortie. Pour changer la résolution *physique*, utiliser Windows et/ou le processeur vidéo.
- Certains vidéos (HDR, codecs exotiques, formats anamorphiques ou accélération matérielle) peuvent produire des comportements de mise à l'échelle différents ; tester sur la configuration de prestation.
- Le projet n'a pas pu être lancé graphiquement dans l'environnement Linux de préparation, faute de PySide6 et de VLC. Les modules Python sont vérifiés par compilation de syntaxe et tests unitaires, **pas par test de lecture HDMI**.

## Construire l'EXE avec GitHub Actions (sans rien installer sur le PC)

1. Ouvrir ton dépôt GitHub **StagePlay**.
2. Mettre à jour à la racine les fichiers `stageplay.py`, `stageplay_core.py`, `stageplay_output.py`, `requirements.txt`, `README.md` et le dossier `tests`.
3. Sur GitHub, ouvrir `.github/workflows/windows-build.yml`, cliquer sur le crayon et **remplacer son contenu** avec celui du fichier `.github/workflows/windows-build.yml` fourni ici. Puis `Commit changes`.
4. Onglet **Actions** → **Fabriquer StagePlay V2 pour Windows** → **Run workflow** (si l'exécution ne s'est pas déjà lancée après le commit).
5. À la coche verte : ouvrir le workflow → **Summary** → **Artifacts** → `StagePlayV2-Windows-portable`.
6. Décompresser l'archive. Lancer `StagePlayV2.exe` **en conservant tout le dossier** (ne pas copier seulement l'EXE).

Le dépôt peut être privé ; le compte GitHub gratuit dispose généralement de minutes d'exécution Actions, sous réserve des quotas et conditions de GitHub.

## Compilation locale Windows (alternative)

Installer Python 3.12 64 bits et VLC 3.x 64 bits. Lancer `build_windows.bat` depuis le dossier du projet. Le logiciel sort dans `dist/StagePlayV2/StagePlayV2.exe` (dossier à copier en entier).

## Raccourcis

| Touche | Fonction |
|---|---|
| F5 | GO cue sélectionnée |
| Espace | Pause/reprise |
| F6 | BLACK / restauration |
| F7 | STOP |
| F8 | Sélectionner cue suivante (pas GO) |
| F9 | LOGO / restauration |
| PageUp / PageDown | Page PDF précédente / suivante |
| Ctrl+O | Import médias |
| Ctrl+S | Sauver show |

## Vérifications avant prestation

- Configuration Windows sur `Étendre ces affichages` ; désactiver notifications et veille.
- Ouvrir SORTIE A sur **le bon écran**, vérifier résolution / fréquence, synchronisation audio.
- Tester sur **MP4, MOV**, image et PDF, avec `medias_test/` fourni.
- Tester FIT, FILL, STRETCH, Zoom et les crops sur l'écran réel et via le mélangeur.
- Tester les points IN/OUT et BLACK/LOGO pendant la lecture, notamment le retour de masque.
- Ne pas utiliser comme source unique critique tant que les essais n'ont pas été validés.

**Licence du moteur VLC :** en cas de redistribution du dossier avec DLL/plugins VLC, consulter et respecter les licences VideoLAN/libVLC et fournir les notices nécessaires.
