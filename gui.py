import sys
import os
import shutil
import datetime
import time
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QLineEdit, QTextEdit, QComboBox, QFileDialog, QMessageBox,
    QProgressBar, QTabWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from file_utils import copy_folder

class BackupThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    journal = pyqtSignal(str)

    def __init__(self, sources, destination):
        super().__init__()
        self.sources = sources
        self.destination = destination
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        start_time = time.time()

        def count_files(src):
            total = 0
            for root, dirs, files in os.walk(src):
                for f in files:
                    s = os.path.join(root, f)
                    rel_path = os.path.relpath(s, src)
                    d = os.path.join(self.destination, os.path.basename(os.path.normpath(src)), rel_path)
                    # Correction : vérifier l'existence avant d'appeler getmtime
                    if not os.path.exists(d):
                        total += 1
                    else:
                        try:
                            if os.path.getmtime(s) > os.path.getmtime(d):
                                total += 1
                        except Exception:
                            total += 1
            return total

        total_files = sum(count_files(src) for src in self.sources) or 1
        copied_files = 0
        self.journal.emit("Début de la sauvegarde.")

        def copy_folder_progress(src, dst, log_func=None):
            nonlocal copied_files
            base_name = os.path.basename(os.path.normpath(src))
            dst_subfolder = os.path.join(dst, base_name)
            src_long = src
            dst_long = dst_subfolder
            if os.name == 'nt':
                from file_utils import long_path
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
                for item in os.listdir(src_long):
                    if self._abort:
                        if log_func:
                            log_func("Copie annulée par l'utilisateur.")
                        return
                    s = os.path.join(src_long, item)
                    d = os.path.join(dst_long, item)
                    try:
                        if os.path.islink(s):
                            if os.path.lexists(d):
                                os.remove(d)
                            linkto = os.readlink(s)
                            os.symlink(linkto, d)
                        elif os.path.isdir(s):
                            copy_folder_progress(s, dst_long, log_func)
                        else:
                            # Ne copie que si le fichier n'existe pas ou a été modifié
                            if not os.path.exists(d) or os.path.getmtime(s) > os.path.getmtime(d):
                                shutil.copy2(s, d, follow_symlinks=False)
                                copied_files += 1
                                percent = int((copied_files / total_files) * 100)
                                self.progress.emit(percent)
                    except OSError as e:
                        try:
                            if os.name == 'nt':
                                from file_utils import long_path
                                # Ne copie que si le fichier n'existe pas ou a été modifié
                                if not os.path.exists(d) or os.path.getmtime(s) > os.path.getmtime(d):
                                    shutil.copy2(long_path(s), long_path(d), follow_symlinks=False)
                                    copied_files += 1
                                    percent = int((copied_files / total_files) * 100)
                                    self.progress.emit(percent)
                            else:
                                raise
                        except Exception as e2:
                            if log_func:
                                log_func(f"Erreur lors de la copie de {s} : {e2}")
            except Exception as e:
                if log_func:
                    log_func(f"Erreur critique lors de la copie de {src} : {e}")

        for src in self.sources:
            if self._abort:
                self.journal.emit("Copie annulée par l'utilisateur.")
                break
            try:
                self.journal.emit(f"Préparation à copier : {src}")
                self.log.emit(f"Copie de {src} vers {self.destination}...")
                self.journal.emit(f"Copie de {src} vers {self.destination} démarrée.")
                copy_folder_progress(src, self.destination, log_func=self.journal.emit)
                if not self._abort:
                    self.journal.emit(f"Copie de {src} terminée avec succès.")
            except Exception as e:
                self.journal.emit(f"Erreur lors de la copie de {src} : {str(e)}")
        self.progress.emit(100)
        elapsed = time.time() - start_time
        if self._abort:
            self.journal.emit("Fin de la sauvegarde (annulée par l'utilisateur).")
        else:
            self.journal.emit(f"Fin de la sauvegarde. Durée totale : {elapsed:.2f} secondes.")
            self.log.emit("Sauvegarde terminée.")

class BackupAssistant(QWidget):
    def __init__(self):
        super().__init__()
        # Initialisation des états de planification
        self.next_backup_time = None
        self.scheduled_backup_active = False
        self.scheduled_seconds_left = None

        # Timers
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_next_backup_label)
        self.timer.start(1000)

        self.scheduled_timer = QTimer(self)
        self.scheduled_timer.timeout.connect(self.scheduled_backup_tick)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()
        self.tabs = QTabWidget()
        self.tab_main = QWidget()
        self.tab_log = QWidget()
        self.tab_about = QWidget()
        self.tabs.addTab(self.tab_main, "Assistant")
        self.tabs.addTab(self.tab_log, "Journal")
        self.tabs.addTab(self.tab_about, "À propos")
        main_layout.addWidget(self.tabs)

        # --- Onglet principal ---
        tab_main_layout = QVBoxLayout()
        title = QLabel("<b><span style='font-size:16pt'>Assistant de sauvegarde de dossiers</span></b>")
        tab_main_layout.addWidget(title)

        # Source folders
        src_layout = QHBoxLayout()
        src_label = QLabel("Dossiers source à sauvegarder :")
        src_layout.addWidget(src_label)
        tab_main_layout.addLayout(src_layout)

        src_list_layout = QHBoxLayout()
        self.src_list = QListWidget()
        src_list_layout.addWidget(self.src_list)

        btns_layout = QVBoxLayout()
        self.btn_add_src = QPushButton("Ajouter dossier\nsource")
        self.btn_add_src.clicked.connect(self.add_source)
        btns_layout.addWidget(self.btn_add_src)

        self.btn_remove_src = QPushButton("Supprimer sélection")
        self.btn_remove_src.setStyleSheet("background-color: #f8d7da;")
        self.btn_remove_src.clicked.connect(self.remove_source)
        btns_layout.addWidget(self.btn_remove_src)

        self.btn_total_size = QPushButton("Taille totale")
        self.btn_total_size.setStyleSheet("background-color: #d4edda;")
        self.btn_total_size.clicked.connect(self.show_total_size)
        btns_layout.addWidget(self.btn_total_size)
        btns_layout.addStretch()
        src_list_layout.addLayout(btns_layout)
        tab_main_layout.addLayout(src_list_layout)

        # Destination folder
        dst_layout = QHBoxLayout()
        dst_label = QLabel("Dossier de destination :")
        dst_layout.addWidget(dst_label)
        self.dst_edit = QLineEdit()
        dst_layout.addWidget(self.dst_edit)
        self.btn_choose_dst = QPushButton("Choisir destination")
        self.btn_choose_dst.clicked.connect(self.choose_destination)
        dst_layout.addWidget(self.btn_choose_dst)
        tab_main_layout.addLayout(dst_layout)

        # Frequency
        freq_layout = QHBoxLayout()
        freq_label = QLabel("Fréquence d'exécution :")
        freq_layout.addWidget(freq_label)
        self.freq_combo = QComboBox()
        self.freq_combo.addItems([
            "Une seule fois",
            "Toutes les 10 minutes",
            "Toutes les 12 heures",
            "Tous les jours",
            "Toutes les semaines"
        ])
        self.freq_combo.currentIndexChanged.connect(self.on_freq_changed)
        freq_layout.addWidget(self.freq_combo)
        freq_layout.addStretch()
        tab_main_layout.addLayout(freq_layout)

        # Info fréquence
        self.freq_info = QLabel(
            "<i>Astuce :</i> "
            "Si vous choisissez une fréquence régulière, la sauvegarde sera automatiquement relancée selon la périodicité choisie.<br>"
            "Exemple : <b>Tous les jours</b> = sauvegarde quotidienne automatique.<br>"
            "L'application doit rester ouverte pour exécuter les sauvegardes planifiées."
        )
        self.freq_info.setWordWrap(True)
        self.freq_info.setStyleSheet("color: #555; font-size: 10pt;")
        tab_main_layout.addWidget(self.freq_info)

        # Affichage du temps restant
        self.next_backup_label = QLabel("Prochaine sauvegarde dans : --:--:--")
        self.next_backup_label.setStyleSheet("font-size: 11pt; color: #007bff;")
        tab_main_layout.addWidget(self.next_backup_label)

        # Log et progression
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        tab_main_layout.addWidget(self.log_text, stretch=1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        tab_main_layout.addWidget(self.progress_bar)

        # Boutons principaux
        btn_layout = QHBoxLayout()
        self.btn_close = QPushButton("Fermer")
        self.btn_close.setStyleSheet("background-color: #f8d7da;")
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_close)
        btn_layout.addStretch()
        self.btn_start = QPushButton("Lancer la sauvegarde")
        self.btn_start.setStyleSheet("background-color: #d4edda;")
        self.btn_start.clicked.connect(lambda: self.start_backup(scheduled=False))
        btn_layout.addWidget(self.btn_start)
        tab_main_layout.addLayout(btn_layout)

        # Bouton sauvegarde auto
        self.btn_start_auto = QPushButton("Lancer la sauvegarde automatique")
        self.btn_start_auto.setStyleSheet("background-color: #cce5ff;")
        self.btn_start_auto.clicked.connect(self.start_auto_backup)
        tab_main_layout.addWidget(self.btn_start_auto)

        # Bouton annulation planification
        self.btn_cancel_schedule = QPushButton("Annuler la sauvegarde planifiée")
        self.btn_cancel_schedule.setStyleSheet("background-color: #ffeeba;")
        self.btn_cancel_schedule.clicked.connect(self.cancel_scheduled_backup)
        self.btn_cancel_schedule.setVisible(False)
        tab_main_layout.addWidget(self.btn_cancel_schedule)

        # Bouton pour annuler la copie en cours
        self.btn_abort_copy = QPushButton("Annuler la copie des fichiers")
        self.btn_abort_copy.setStyleSheet("background-color: #f8d7da;")
        self.btn_abort_copy.clicked.connect(self.abort_copy)
        self.btn_abort_copy.setVisible(False)
        tab_main_layout.addWidget(self.btn_abort_copy)

        self.tab_main.setLayout(tab_main_layout)

        # --- Onglet Journal ---
        log_layout = QVBoxLayout()
        journal_info = QLabel(
            "<b>Journal des opérations</b><br>"
            "<span style='color:#555;'>"
            "Cet onglet affiche l’historique détaillé de toutes les sauvegardes réalisées, "
            "y compris les dossiers copiés, la durée, les erreurs éventuelles et les actions manuelles ou automatiques.<br>"
            "Vous pouvez utiliser ces informations pour vérifier le bon déroulement des sauvegardes."
            "</span>"
        )
        journal_info.setWordWrap(True)
        log_layout.addWidget(journal_info)
        self.journal_text = QTextEdit()
        self.journal_text.setReadOnly(True)
        log_layout.addWidget(self.journal_text)
        self.tab_log.setLayout(log_layout)

        # --- Onglet À propos ---
        about_layout = QVBoxLayout()
        about_label = QLabel(
            "<b>Fonctionnement de l'application</b><br><br>"
            "<ul>"
            "<li><b>Sauvegarde simple :</b> Sélectionnez un ou plusieurs dossiers source et un dossier de destination, puis lancez la sauvegarde.</li>"
            "<li><b>Planification :</b> Choisissez une fréquence pour automatiser les sauvegardes (quotidienne, hebdomadaire, ou manuelle).</li>"
            "<li><b>Journalisation :</b> Consultez l’onglet Journal pour suivre l’historique détaillé des opérations, erreurs et succès.</li>"
            "<li><b>Progression :</b> Une barre de progression indique l’avancement de la sauvegarde en cours.</li>"
            "<li><b>Intégrité :</b> L’application vérifie et consigne chaque étape pour garantir la fiabilité des copies.</li>"
            "</ul>"
            "<br>"
            "L’application est conçue pour être simple d’utilisation, robuste et adaptée à la gestion de gros volumes de données.<br>"
            "Pour toute question ou suggestion, contactez votre administrateur."
        )
        about_label.setWordWrap(True)
        about_layout.addWidget(about_label)
        about_layout.addStretch()
        self.tab_about.setLayout(about_layout)

        self.setLayout(main_layout)
        self.update_next_backup_label()

    def on_freq_changed(self):
        # Réinitialise l'affichage sans lancer la planification
        self.next_backup_time = None
        self.scheduled_backup_active = False
        self.btn_cancel_schedule.setVisible(False)
        self.scheduled_timer.stop()
        self.scheduled_seconds_left = None
        self.update_next_backup_label()

    def start_auto_backup(self):
        freq = self.freq_combo.currentText()
        if freq == "Une seule fois":
            QMessageBox.information(self, "Info", "Veuillez choisir une fréquence (quotidienne ou hebdomadaire) pour activer la sauvegarde automatique.")
            return
        self.setup_scheduled_backup()
        self.write_journal("Sauvegarde automatique programmée par l'utilisateur.")
        self.log_text.append("Sauvegarde automatique programmée.")

    def setup_scheduled_backup(self):
        freq = self.freq_combo.currentText()
        now = datetime.datetime.now()
        interval = 0
        if freq == "Toutes les 10 minutes":
            interval = 10 * 60
        elif freq == "Toutes les 12 heures":
            interval = 12 * 3600
        elif freq == "Tous les jours":
            interval = 24 * 3600
        elif freq == "Toutes les semaines":
            interval = 7 * 24 * 3600
        if interval > 0:
            self.scheduled_seconds_left = interval
            self.next_backup_time = now + datetime.timedelta(seconds=interval)
            self.scheduled_backup_active = True
            self.btn_cancel_schedule.setVisible(True)
            self.scheduled_timer.start(1000)
            self.update_next_backup_label()

    def scheduled_backup_tick(self):
        if not self.scheduled_backup_active or self.scheduled_seconds_left is None:
            self.scheduled_timer.stop()
            return
        self.scheduled_seconds_left -= 1
        if self.scheduled_seconds_left <= 0:
            self.scheduled_timer.stop()
            # Lance la sauvegarde automatiquement à la fin du compte à rebours
            self.start_backup(scheduled=True)
            # Le redémarrage du compte à rebours est géré dans on_backup_finished
        self.update_next_backup_label()

    def schedule_next_backup(self):
        freq = self.freq_combo.currentText()
        interval = 0
        if freq == "Toutes les 10 minutes":
            interval = 10 * 60
        elif freq == "Toutes les 12 heures":
            interval = 12 * 3600
        elif freq == "Tous les jours":
            interval = 24 * 3600
        elif freq == "Toutes les semaines":
            interval = 7 * 24 * 3600
        if interval > 0:
            self.scheduled_seconds_left = interval
            self.next_backup_time = datetime.datetime.now() + datetime.timedelta(seconds=interval)
            self.scheduled_timer.start(1000)
            self.update_next_backup_label()
        else:
            self.scheduled_backup_active = False
            self.btn_cancel_schedule.setVisible(False)

    def cancel_scheduled_backup(self):
        self.scheduled_backup_active = False
        self.scheduled_timer.stop()
        self.next_backup_time = None
        self.scheduled_seconds_left = None
        self.btn_cancel_schedule.setVisible(False)
        self.next_backup_label.setText("Planification annulée.")
        self.write_journal("Planification de sauvegarde automatique annulée par l'utilisateur.")

    def update_next_backup_label(self):
        if self.scheduled_backup_active and self.scheduled_seconds_left is not None:
            total = self.scheduled_seconds_left
            if total > 0:
                h, rem = divmod(int(total), 3600)
                m, s = divmod(rem, 60)
                self.next_backup_label.setText(f"Prochaine sauvegarde dans : <span style='color:#007bff'>{h:02d}:{m:02d}:{s:02d}</span>")
            else:
                self.next_backup_label.setText("Prochaine sauvegarde imminente !")
        else:
            self.next_backup_label.setText("Prochaine sauvegarde dans : --:--:--")

    def start_backup(self, scheduled=False):
        sources = [self.src_list.item(i).text() for i in range(self.src_list.count())]
        destination = self.dst_edit.text()
        if not sources or not destination:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner au moins un dossier source et une destination.")
            return
        self.progress_bar.setValue(0)
        if scheduled:
            self.log_text.append("Sauvegarde planifiée lancée automatiquement...")
            self.write_journal("Sauvegarde planifiée lancée automatiquement.")
        else:
            self.log_text.append("Sauvegarde lancée...")
            self.write_journal("Sauvegarde lancée manuellement.")
        self.btn_abort_copy.setVisible(True)
        self.thread = BackupThread(sources, destination)
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.log.connect(self.log_and_journal)
        self.thread.journal.connect(self.write_journal)
        self.thread.finished.connect(self.on_backup_finished)
        self.thread.start()

    def on_backup_finished(self):
        self.btn_abort_copy.setVisible(False)
        # Si la sauvegarde était planifiée, recommence le compte à rebours
        if self.scheduled_backup_active:
            self.schedule_next_backup()

    def log_and_journal(self, msg):
        self.log_text.append(msg)
        self.write_journal(msg)

    def write_journal(self, msg):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.journal_text.append(f"[{now}] {msg}")

    def add_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier source")
        if folder:
            self.src_list.addItem(folder)

    def remove_source(self):
        for item in self.src_list.selectedItems():
            self.src_list.takeItem(self.src_list.row(item))

    def show_total_size(self):
        import os
        def get_size(path):
            total = 0
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.isfile(fp):
                        total += os.path.getsize(fp)
            return total

        total_size = 0
        for i in range(self.src_list.count()):
            total_size += get_size(self.src_list.item(i).text())
        size_mb = total_size / (1024 * 1024)
        QMessageBox.information(self, "Taille totale", f"Taille totale : {size_mb:.2f} Mo")

    def choose_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination")
        if folder:
            self.dst_edit.setText(folder)

    def abort_copy(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.abort()
            self.log_text.append("Annulation de la copie demandée...")
            self.write_journal("Annulation de la copie des fichiers demandée par l'utilisateur.")


def launch_gui():
    app = QApplication(sys.argv)
    window = BackupAssistant()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    launch_gui()
    window = BackupAssistant()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    launch_gui()
