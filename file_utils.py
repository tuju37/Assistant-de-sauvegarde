import shutil
import os
import sys
import stat

def long_path(path):
    # Ajoute le préfixe \\?\ si nécessaire (Windows uniquement)
    if os.name == 'nt':
        path = os.path.abspath(path)
        if not path.startswith('\\\\?\\'):
            if path.startswith('\\\\'):
                path = '\\\\?\\UNC\\' + path[2:]
            else:
                path = '\\\\?\\' + path
    return path

def copy_folder(src, dst, log_func=None):
    """
    Copie récursivement tout le contenu de src dans un sous-dossier de dst.
    Gère les chemins longs, liens symboliques, fichiers cachés, systèmes, fichiers sans extension, fichiers verrouillés, etc.
    Journalise les erreurs si log_func est fourni.
    """
    base_name = os.path.basename(os.path.normpath(src))
    dst_subfolder = os.path.join(dst, base_name)
    src_long = long_path(src)
    dst_long = long_path(dst_subfolder)
    try:
        if not os.path.exists(dst_long):
            os.makedirs(dst_long, exist_ok=True)
            try:
                shutil.copystat(src_long, dst_long, follow_symlinks=False)
            except Exception as e:
                if log_func:
                    log_func(f"Impossible de copier les attributs de {src} : {e}")
        with os.scandir(src_long) as it:
            for entry in it:
                s = entry.path
                d = os.path.join(dst_long, entry.name)
                try:
                    if entry.is_symlink():
                        # Copie le lien symbolique tel quel
                        if os.path.lexists(d):
                            os.remove(d)
                        linkto = os.readlink(s)
                        os.symlink(linkto, d)
                    elif entry.is_dir(follow_symlinks=False):
                        copy_folder(s, dst_long, log_func)
                    elif entry.is_file(follow_symlinks=False):
                        # Tente de rendre le fichier accessible si verrouillé ou protégé
                        try:
                            os.chmod(s, stat.S_IWRITE)
                        except Exception:
                            pass
                        try:
                            shutil.copy2(s, d, follow_symlinks=False)
                        except Exception as e:
                            # Réessaie avec les chemins longs si erreur
                            try:
                                shutil.copy2(long_path(s), long_path(d), follow_symlinks=False)
                            except Exception as e2:
                                if log_func:
                                    log_func(f"Erreur lors de la copie de {s} : {e2}")
                    else:
                        # Cas très rare : autre type (fifo, device, etc.)
                        try:
                            shutil.copy(s, d, follow_symlinks=False)
                        except Exception as e:
                            if log_func:
                                log_func(f"Type de fichier non géré ou erreur : {s} : {e}")
                except Exception as e:
                    if log_func:
                        log_func(f"Erreur lors du traitement de {s} : {e}")
    except Exception as e:
        if log_func:
            log_func(f"Erreur critique lors de la copie de {src} : {e}")
