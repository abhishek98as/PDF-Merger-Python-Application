import os
import sys
import pathlib
import tempfile
import logging
import subprocess
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import QIcon, QPixmap, QAction, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QProgressBar,
    QStyle,
    QToolBar,
    QStatusBar,
    QMenu,
    QScrollArea,
)

# External libraries
from pypdf import PdfReader, PdfWriter
from pdf2image import convert_from_path
from PIL import Image, ImageDraw, ImageFont

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('PDFMerger')

# PyInstaller compatibility
def is_frozen():
    """Check if running in a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

def get_subprocess_creation_flags():
    """Get proper subprocess creation flags for Windows PyInstaller builds."""
    if sys.platform.startswith('win') and is_frozen():
        # Hide console windows when running as exe
        # CREATE_NO_WINDOW = 0x08000000
        return getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    return 0

# Define path for resources
def get_resource_path():
    if is_frozen():
        # When running as PyInstaller exe, use the temporary directory
        base_path = pathlib.Path(sys._MEIPASS)
    else:
        # When running as script, use script directory
        base_path = pathlib.Path(__file__).resolve().parent
    
    assets_dir = base_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir

# Get the Poppler path
def get_poppler_path():
    if is_frozen():
        # When running as PyInstaller exe, check bundled poppler first
        base_path = pathlib.Path(sys._MEIPASS)
        bundled_poppler = base_path / "poppler" / "bin"
        if bundled_poppler.exists():
            return str(bundled_poppler)
    else:
        # When running as script, check local poppler
        base_path = pathlib.Path(__file__).resolve().parent
        local_poppler = base_path / "poppler-23.11.0" / "Library" / "bin"
        if local_poppler.exists():
            return str(local_poppler)
    
    # Try environment variable
    env_path = os.environ.get("POPPLER_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
        
    # On Windows, try common installation locations
    if sys.platform.startswith('win'):
        common_paths = [
            r"C:\Program Files\poppler-23.11.0\Library\bin",
            r"C:\Program Files\poppler\bin",
            r"C:\poppler\bin",
            os.path.expanduser("~\\poppler\\bin")
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
                
    return None

ASSETS_DIR = get_resource_path()
ICON_PATH = ASSETS_DIR / "app_icon.png"
POPPLER_PATH = get_poppler_path()

# Global thread pool
MAX_WORKERS = min(16, (os.cpu_count() or 1) + 4)
THUMBNAIL_POOL = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="thumbnail")

# Simple thumbnail cache to avoid regenerating thumbnails
THUMBNAIL_CACHE = {}
CACHE_MAX_SIZE = 50

@dataclass
class PDFEntry:
    path: pathlib.Path
    pages: int = 0
    thumb: Optional[QIcon] = None
    file_size: int = 0

# Icon generation
def generate_icon(path: pathlib.Path, size: int = 256) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (size, size), (35, 39, 47, 255))
    draw = ImageDraw.Draw(img)

    # Rounded rect background with accent corner
    radius = size // 10
    draw.rounded_rectangle([(8, 8), (size - 8, size - 8)], radius=radius, fill=(28, 31, 38, 255))
    draw.rectangle([(size * 0.55, 8), (size - 8, size * 0.45)], fill=(52, 199, 89, 255))

    # Folded corner triangle
    draw.polygon(
        [
            (size - 8, 8),
            (size - size * 0.20, 8),
            (size - 8, size * 0.20),
        ],
        fill=(76, 217, 100, 255),
    )

    # PDF glyph
    try:
        font = ImageFont.truetype("arial.ttf", size // 4)
    except Exception:
        font = ImageFont.load_default()
    text = "PDF"
    tw, th = draw.textbbox((0, 0), text, font=font)[2:]
    draw.text(((size - tw) / 2, (size - th) / 2), text, font=font, fill=(255, 255, 255, 255))

    img.save(path)

# Background workers
class SimpleThumbnailWorker(QThread):
    result = pyqtSignal(object, object)  # (pathlib.Path, QIcon)
    error = pyqtSignal(object, str)

    def __init__(self, path: pathlib.Path, thumb_size: Tuple[int, int] = (140, 180)):
        super().__init__()
        self.path = path
        self.thumb_size = thumb_size

    def run(self) -> None:
        try:
            # Check cache first
            cache_key = f"{self.path}_{self.thumb_size[0]}x{self.thumb_size[1]}_{self.path.stat().st_mtime}"
            
            if cache_key in THUMBNAIL_CACHE:
                logger.debug(f"Using cached thumbnail for {self.path}")
                self.result.emit(self.path, THUMBNAIL_CACHE[cache_key])
                return
            
            # Add timeout for thumbnail generation
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("Thumbnail generation timed out")
            
            # Set timeout only on Unix systems
            if hasattr(signal, 'SIGALRM'):
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(10)  # 10 second timeout
            
            try:
                qpix = render_page_qpix(self.path, page_index=0, 
                                       max_w=self.thumb_size[0], 
                                       max_h=self.thumb_size[1])
                
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)  # Cancel timeout
                    
                if not qpix.isNull():
                    icon = QIcon(qpix)
                    
                    # Cache the result
                    if len(THUMBNAIL_CACHE) >= CACHE_MAX_SIZE:
                        # Remove oldest entry
                        oldest_key = next(iter(THUMBNAIL_CACHE))
                        del THUMBNAIL_CACHE[oldest_key]
                    
                    THUMBNAIL_CACHE[cache_key] = icon
                    self.result.emit(self.path, icon)
                else:
                    self.error.emit(self.path, "Failed to generate thumbnail")
                    
            except TimeoutError:
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)  # Cancel timeout
                logger.warning(f"Thumbnail generation timed out for {self.path}")
                self.error.emit(self.path, "Thumbnail generation timed out")
                
        except Exception as e:
            logger.error(f"Thumbnail generation failed for {self.path}: {str(e)}")
            self.error.emit(self.path, str(e))

class SimplePageCountWorker(QThread):
    counted = pyqtSignal(object, int, int)  # (pathlib.Path, pages, file_size)

    def __init__(self, path: pathlib.Path):
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            # Get file stats
            stat = self.path.stat()
            file_size = stat.st_size
            
            # Count pages using pypdf
            reader = PdfReader(str(self.path))
            page_count = len(reader.pages)
            
            self.counted.emit(self.path, page_count, file_size)
        except Exception as e:
            logger.error(f"Page counting failed for {self.path}: {str(e)}")

class MergeWorker(QThread):
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, paths: List[pathlib.Path], output_path: pathlib.Path):
        super().__init__()
        self.paths = paths
        self.output_path = output_path

    def run(self) -> None:
        try:
            writer = PdfWriter()
            total = len(self.paths)
            logger.info(f"Starting merge of {total} PDFs to {self.output_path}")
            
            for i, p in enumerate(self.paths, start=1):
                reader = PdfReader(str(p))
                for page in reader.pages:
                    writer.add_page(page)
                self.progress.emit(int(i / max(1, total) * 100))
                logger.info(f"Added PDF {i}/{total}: {p}")
                
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "wb") as f:
                writer.write(f)
            logger.info(f"Merge completed successfully to {self.output_path}")
            self.finished_ok.emit(str(self.output_path))
        except Exception as e:
            logger.error(f"Merge failed: {str(e)}", exc_info=True)
            self.failed.emit(str(e))

# UI Widgets
class SimpleGridListWidget(QListWidget):
    filesDropped = pyqtSignal(list)  # list[pathlib.Path]
    itemsChanged = pyqtSignal()

    def __init__(self, columns=3):
        super().__init__()
        self.columns = columns
        self.item_size = QSize(200, 280)
        
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(160, 200))
        self.setGridSize(self.item_size)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setSpacing(15)
        self.setWordWrap(True)
        
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setUniformItemSizes(True)
        
        self.viewport().installEventFilter(self)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)
        self.model().rowsInserted.connect(self.itemsChanged)
        self.model().rowsRemoved.connect(self.itemsChanged)

    def resizeEvent(self, event):
        available_width = self.viewport().width() - (self.columns + 1) * self.spacing()
        col_width = max(170, available_width // self.columns)
        
        icon_width = int(col_width * 0.85)
        icon_height = int(icon_width * 1.3)
        
        item_width = col_width
        item_height = icon_height + 70
        
        self.setIconSize(QSize(icon_width, icon_height))
        self.setGridSize(QSize(item_width, item_height))
        
        super().resizeEvent(event)

    def _open_menu(self, pos):
        menu = QMenu(self)
        remove = QAction("Remove selected", self)
        clear = QAction("Clear all", self)
        menu.addAction(remove)
        menu.addAction(clear)
        remove.triggered.connect(self._remove_selected)
        clear.triggered.connect(self.clear)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _remove_selected(self):
        for item in self.selectedItems():
            self.takeItem(self.row(item))

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.Type.DragEnter:
            return self._dragEnterEvent(event)
        if obj is self.viewport() and event.type() == QEvent.Type.Drop:
            return self._dropEvent(event)
        return super().eventFilter(obj, event)

    def _dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(str(u.toLocalFile()).lower().endswith(".pdf") for u in urls):
                event.acceptProposedAction()
                return True
        return False

    def _dropEvent(self, event: QDropEvent):
        paths = [pathlib.Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile() and str(u.toLocalFile()).lower().endswith(".pdf")]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return True
        return False

class SimpleScrollablePreview(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.layout.setSpacing(15)
        self.setWidget(self.container)

    def clear_pages(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_message(self, text):
        self.clear_pages()
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("color: #9aa0a6; font-size: 14px; padding: 20px;")
        self.layout.addWidget(label)

    def load_pdf(self, path, max_width=800):
        self.clear_pages()
        self.show_message("Loading PDF...")
        
        try:
            # Configure pdf2image to hide console windows on Windows
            import pdf2image.pdf2image as pdf2image_module
            
            # Monkey patch the subprocess call to use proper creation flags
            original_popen = subprocess.Popen
            def patched_popen(*args, **kwargs):
                if sys.platform.startswith('win') and is_frozen():
                    kwargs.setdefault('creationflags', get_subprocess_creation_flags())
                return original_popen(*args, **kwargs)
            
            # Temporarily replace Popen
            subprocess.Popen = patched_popen
            pdf2image_module.subprocess.Popen = patched_popen
            
            try:
                # Load first few pages for preview
                images = convert_from_path(
                    str(path), 
                    first_page=1, 
                    last_page=min(5, len(PdfReader(str(path)).pages)), 
                    dpi=150,
                    poppler_path=POPPLER_PATH
                )
            finally:
                # Restore original Popen
                subprocess.Popen = original_popen
                pdf2image_module.subprocess.Popen = original_popen
            
            if images:
                for i, img in enumerate(images):
                    # Convert PIL image to QPixmap
                    from io import BytesIO
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    qpix = QPixmap()
                    qpix.loadFromData(buf.getvalue(), "PNG")
                    
                    # Scale if needed
                    if max_width and qpix.width() > max_width:
                        qpix = qpix.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
                    
                    # Create page widget
                    page_label = QLabel()
                    page_label.setPixmap(qpix)
                    page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    page_label.setStyleSheet("""
                        background-color: #ffffff; 
                        border: 1px solid #2a2e3a; 
                        border-radius: 8px; 
                        padding: 8px;
                    """)
                    
                    # Page number
                    page_number = QLabel(f"Page {i + 1}")
                    page_number.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    page_number.setStyleSheet("color: #bdc1c6; font-weight: bold; padding: 4px;")
                    
                    # Container
                    container = QWidget()
                    container_layout = QVBoxLayout(container)
                    container_layout.addWidget(page_label)
                    container_layout.addWidget(page_number)
                    
                    self.layout.addWidget(container)
            else:
                self.show_message("No pages could be loaded from this PDF")
                
        except Exception as e:
            logger.error(f"Error loading PDF preview: {str(e)}")
            self.show_message(f"Error loading PDF: {str(e)}")

# Main Window
class SimpleMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Merger App - Simple")
        self.setMinimumSize(1100, 700)
        
        ensure_icon()
        self.app_icon = QIcon(str(ICON_PATH))
        self.setWindowIcon(self.app_icon)
        
        self._thumb_worker: Optional[SimpleThumbnailWorker] = None
        self._page_worker: Optional[SimplePageCountWorker] = None
        self._pending_files: List[pathlib.Path] = []
        self._batch_timer = QTimer()
        self._batch_timer.timeout.connect(self._process_pending_files)
        self._batch_timer.setSingleShot(True)

        self._init_ui()
        self._apply_styles()
        self._update_count()

    def _init_ui(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        central = QWidget()
        root = QVBoxLayout(central)
        
        self.count_label = QLabel("No files loaded")
        self.count_label.setObjectName("CountLabel")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.count_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # Left: controls + list of PDFs
        left = QWidget()
        lv = QVBoxLayout(left)

        add_row = QHBoxLayout()
        self.btn_add = QPushButton("Add PDFs")
        self.btn_add_folder = QPushButton("Add Folder")
        self.btn_add.clicked.connect(self.on_add)
        self.btn_add_folder.clicked.connect(self.on_add_folder)
        add_row.addWidget(self.btn_add)
        add_row.addWidget(self.btn_add_folder)
        lv.addLayout(add_row)

        self.listw = SimpleGridListWidget(columns=3)
        self.listw.filesDropped.connect(self.add_paths)
        self.listw.itemSelectionChanged.connect(self.on_selection_changed)
        self.listw.itemsChanged.connect(self._update_count)
        lv.addWidget(self.listw, 1)

        controls = QHBoxLayout()
        self.btn_merge = QPushButton("Merge")
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setObjectName("danger")
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("secondary")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        controls.addWidget(self.btn_merge)
        controls.addWidget(self.btn_remove)
        controls.addWidget(self.btn_reset)
        controls.addStretch(1)
        controls.addWidget(self.progress)
        lv.addLayout(controls)

        self.btn_merge.clicked.connect(self.on_merge)
        self.btn_remove.clicked.connect(self.on_remove)
        self.btn_reset.clicked.connect(self.on_reset)

        splitter.addWidget(left)

        # Right: preview panel
        right = QWidget()
        rv = QVBoxLayout(right)
        
        self.preview_scroll = SimpleScrollablePreview()
        self.preview_scroll.show_message("Select a PDF to preview")
        rv.addWidget(self.preview_scroll, 1)

        meta_row = QHBoxLayout()
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("MetaLabel")
        meta_row.addWidget(self.meta_label)
        rv.addLayout(meta_row)

        splitter.addWidget(right)
        splitter.setSizes([550, 550])

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QMainWindow { background: #111318; }
            QToolBar { background: #171922; border: none; padding: 6px; }
            QToolButton { color: #e8eaed; padding: 6px 10px; border-radius: 6px; }
            QToolButton:hover { background: #222533; }

            QListWidget { background: #0f1116; border: 1px solid #2a2e3a; border-radius: 8px; padding: 8px; color: #e8eaed; }
            QListWidget::item { 
                border: 1px solid transparent; 
                border-radius: 8px; 
                padding: 6px; 
                text-align: center;
                background-color: #171922;
            }
            QListWidget::item:hover { background: #1a1d27; }
            QListWidget::item:selected { background: #2a2e3a; border: 1px solid #3a3f4c; }

            QPushButton { background: #2b5cff; color: white; padding: 10px 16px; border: none; border-radius: 8px; font-weight: 600; }
            QPushButton:hover { background: #2148cc; }
            QPushButton#danger { background: #e53935; }
            QPushButton#danger:hover { background: #c62828; }
            QPushButton#secondary { background: #2a2e3a; color: #e8eaed; }
            QPushButton#secondary:hover { background: #343948; }

            QLabel#MetaLabel { color: #bdc1c6; padding: 6px 0; }
            QLabel#CountLabel { color: #e8eaed; font-weight: 600; padding: 10px; background-color: #171922; border-radius: 6px; margin-bottom: 8px; }

            QScrollArea { background: #0f1116; border: 1px solid #2a2e3a; border-radius: 8px; }
            
            QProgressBar { border: 1px solid #2a2e3a; border-radius: 6px; background: #0f1116; color: #e8eaed; }
            QProgressBar::chunk { background-color: #52c41a; border-radius: 6px; }
            
            QScrollBar:vertical { background: #0f1116; width: 12px; margin: 0px; }
            QScrollBar::handle:vertical { background: #2a2e3a; min-height: 20px; border-radius: 6px; }
            QScrollBar::handle:vertical:hover { background: #3a3f4c; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
            """
        )

    def _update_count(self):
        total_files = self.listw.count()
        total_pages = 0
        total_size = 0
        
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            pages = item.data(Qt.ItemDataRole.UserRole + 1) or 0
            file_size = item.data(Qt.ItemDataRole.UserRole + 2) or 0
            total_pages += pages
            total_size += file_size
        
        if total_files == 0:
            self.count_label.setText("No files loaded")
        else:
            size_mb = total_size / (1024 * 1024) if total_size > 0 else 0
            if size_mb > 1024:
                size_str = f"{size_mb/1024:.1f} GB"
            else:
                size_str = f"{size_mb:.1f} MB"
            self.count_label.setText(f"Files: {total_files} • Pages: {total_pages} • Size: {size_str}")

    def on_add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select PDF files", str(pathlib.Path.home()), "PDF Files (*.pdf)")
        self.add_paths([pathlib.Path(p) for p in paths])

    def add_paths(self, paths: List[pathlib.Path]):
        if not paths:
            return
            
        existing = {self.listw.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.listw.count())}
        
        new_paths = []
        for p in paths:
            if p in existing:
                continue
            if not p.exists() or p.suffix.lower() != ".pdf":
                continue
                
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(str(p))
            item.setText(f"{p.name}\nAnalyzing...")
            item.setSizeHint(self.listw.gridSize())
            self.listw.addItem(item)
            new_paths.append(p)
        
        if new_paths:
            self._pending_files.extend(new_paths)
            self._batch_timer.stop()
            self._batch_timer.start(500)
            
            logger.info(f"Added {len(new_paths)} files to pending batch")
            self.statusBar().showMessage(f"Added {len(new_paths)} file(s) - Processing...", 4000)

    def _process_pending_files(self):
        if not self._pending_files:
            return
            
        files_to_process = self._pending_files.copy()
        self._pending_files.clear()
        
        logger.info(f"Processing batch of {len(files_to_process)} files")
        
        # Process files one by one to avoid thread overload
        if files_to_process:
            # Start with the first file
            self._current_batch = files_to_process
            self._current_batch_index = 0
            self._process_next_in_batch()

    def _process_next_in_batch(self):
        """Process the next file in the current batch."""
        if not hasattr(self, '_current_batch') or self._current_batch_index >= len(self._current_batch):
            # Batch processing complete
            if hasattr(self, '_current_batch'):
                logger.info(f"Completed processing batch of {len(self._current_batch)} files")
                delattr(self, '_current_batch')
                delattr(self, '_current_batch_index')
            return
        
        path = self._current_batch[self._current_batch_index]
        self._current_batch_index += 1
        
        # Clean up any existing workers first
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.quit()
            self._thumb_worker.wait(1000)
        
        if self._page_worker and self._page_worker.isRunning():
            self._page_worker.quit()
            self._page_worker.wait(1000)
        
        # Start thumbnail generation with completion callback
        self._thumb_worker = SimpleThumbnailWorker(path, self.listw.iconSize())
        self._thumb_worker.result.connect(self._on_thumb_ready)
        self._thumb_worker.error.connect(self._on_thumb_error)
        self._thumb_worker.finished.connect(self._on_thumbnail_finished)
        self._thumb_worker.start()
        
        # Start page counting
        self._page_worker = SimplePageCountWorker(path)
        self._page_worker.counted.connect(self._on_pages_ready)
        self._page_worker.start()

    def _on_thumbnail_finished(self):
        """Called when thumbnail generation is finished, continue with next file."""
        # Small delay to prevent overwhelming the system
        QTimer.singleShot(100, self._process_next_in_batch)


    def on_add_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select a folder containing PDFs", str(pathlib.Path.home()))
        if not dir_path:
            return
        base = pathlib.Path(dir_path)
        pdfs: List[pathlib.Path] = []
        for root, _, files in os.walk(base):
            for name in sorted(files):
                if name.lower().endswith(".pdf"):
                    pdfs.append(pathlib.Path(root) / name)
        if not pdfs:
            QMessageBox.information(self, "No PDFs", "No PDF files found in the selected folder.")
            return
        self.add_paths(pdfs)

    def _on_thumb_ready(self, path: pathlib.Path, icon: QIcon):
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setIcon(icon)
                break

    def _on_thumb_error(self, path: pathlib.Path, err: str):
        item = None
        for i in range(self.listw.count()):
            it = self.listw.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                item = it
                break
        if item:
            item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        logger.error(f"Thumbnail error for {path}: {err}")
        self.statusBar().showMessage(f"Preview failed for {path.name}: {err}", 5000)

    def _on_pages_ready(self, path: pathlib.Path, pages: int, file_size: int):
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                base = path.name
                size_mb = file_size / (1024 * 1024)
                item.setText(f"{base}\n{pages} pages • {size_mb:.1f} MB")
                item.setData(Qt.ItemDataRole.UserRole + 1, pages)
                item.setData(Qt.ItemDataRole.UserRole + 2, file_size)
                break
        self._update_count()

    def on_merge(self):
        if self.listw.count() == 0:
            QMessageBox.information(self, "Nothing to merge", "Add some PDF files first.")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Choose output directory", str(pathlib.Path.home()))
        if not out_dir:
            return
        out_path = pathlib.Path(out_dir) / "merged.pdf"
        paths = [self.listw.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.listw.count())]
        self.progress.setValue(0)
        self._merge_thread = MergeWorker(paths, out_path)
        self._merge_thread.progress.connect(self.progress.setValue)
        self._merge_thread.finished_ok.connect(self._on_merge_done)
        self._merge_thread.failed.connect(self._on_merge_failed)
        self._toggle_controls(False)
        self._merge_thread.start()
        
    def on_remove(self):
        selected = self.listw.selectedItems()
        if not selected:
            QMessageBox.information(self, "No Selection", "Please select PDF file(s) to remove.")
            return
        
        count = len(selected)
        if count == 1:
            msg = f"Remove {selected[0].data(Qt.ItemDataRole.UserRole).name}?"
        else:
            msg = f"Remove {count} selected PDF files?"
            
        reply = QMessageBox.question(self, "Confirm Remove", msg, 
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                                    
        if reply == QMessageBox.StandardButton.Yes:
            self.listw._remove_selected()
            self.statusBar().showMessage(f"Removed {count} file(s)", 4000)

    def _on_merge_done(self, out_path: str):
        self._toggle_controls(True)
        self.progress.setValue(100)
        self.statusBar().showMessage(f"Merged to {out_path}", 8000)
        QMessageBox.information(self, "Done", f"Merged PDF saved to:\n{out_path}")

    def _on_merge_failed(self, err: str):
        self._toggle_controls(True)
        self.statusBar().showMessage("Merge failed", 6000)
        QMessageBox.critical(self, "Merge failed", err)

    def _toggle_controls(self, enabled: bool):
        self.listw.setEnabled(enabled)
        self.btn_merge.setEnabled(enabled)
        self.btn_remove.setEnabled(enabled)
        self.btn_reset.setEnabled(enabled)

    def on_reset(self):
        self.listw.clear()
        self.preview_scroll.show_message("Select a PDF to preview")
        self.meta_label.setText("")
        self.progress.setValue(0)
        self._update_count()

    def on_selection_changed(self):
        items = self.listw.selectedItems()
        if not items:
            self.preview_scroll.show_message("Select a PDF to preview")
            self.meta_label.setText("")
            return
        
        item = items[0]
        path: pathlib.Path = item.data(Qt.ItemDataRole.UserRole)
        pages = item.data(Qt.ItemDataRole.UserRole + 1) or 0
        
        self.preview_scroll.load_pdf(path)
        
        file_size = item.data(Qt.ItemDataRole.UserRole + 2) or 0
        size_mb = file_size / (1024 * 1024) if file_size > 0 else 0
        size_str = f" • {size_mb:.1f} MB" if file_size > 0 else ""
        self.meta_label.setText(f"{path.name} — {pages} page(s){size_str}\n{path}")

    def closeEvent(self, event):
        logger.info("Application closing, cleaning up resources...")
        
        # Stop batch processing
        if hasattr(self, '_current_batch'):
            delattr(self, '_current_batch')
            delattr(self, '_current_batch_index')
        
        self._batch_timer.stop()
        
        # Clean up workers
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.quit()
            self._thumb_worker.wait(3000)
            
        if self._page_worker and self._page_worker.isRunning():
            self._page_worker.quit()
            self._page_worker.wait(3000)
        
        try:
            THUMBNAIL_POOL.shutdown(wait=False)
            logger.info("Thread pool shutdown initiated")
        except Exception as e:
            logger.warning(f"Error during thread pool shutdown: {e}")
        
        event.accept()

# Helper functions
def ensure_icon():
    try:
        if not ICON_PATH.exists():
            logger.info(f"Generating app icon at {ICON_PATH}")
            generate_icon(ICON_PATH)
        else:
            logger.info(f"Icon already exists at {ICON_PATH}")
    except Exception as e:
        logger.error(f"Icon generation failed: {str(e)}", exc_info=True)

def render_page_qpix(path: pathlib.Path, page_index: int = 0, max_w: Optional[int] = None, max_h: Optional[int] = None) -> QPixmap:
    """Render a PDF page to QPixmap with PyInstaller compatibility."""
    try:
        # Configure pdf2image to hide console windows on Windows
        import pdf2image.pdf2image as pdf2image_module
        
        # Monkey patch the subprocess call to use proper creation flags
        original_popen = subprocess.Popen
        def patched_popen(*args, **kwargs):
            if sys.platform.startswith('win') and is_frozen():
                kwargs.setdefault('creationflags', get_subprocess_creation_flags())
            return original_popen(*args, **kwargs)
        
        # Temporarily replace Popen
        subprocess.Popen = patched_popen
        pdf2image_module.subprocess.Popen = patched_popen
        
        try:
            # Use lower DPI for thumbnails to improve speed
            dpi = 120 if max_w and max_w < 200 else 150
            
            images = convert_from_path(
                str(path), 
                first_page=page_index + 1, 
                last_page=page_index + 1, 
                dpi=dpi,
                poppler_path=POPPLER_PATH
            )
        finally:
            # Restore original Popen
            subprocess.Popen = original_popen
            pdf2image_module.subprocess.Popen = original_popen
        
        if images:
            from io import BytesIO
            img = images[0]
            if max_w or max_h:
                img.thumbnail((max_w or img.width, max_h or img.height), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            qpix = QPixmap()
            qpix.loadFromData(buf.getvalue(), "PNG")
            return qpix
        else:
            logger.error(f"pdf2image returned no images for {path}")
            
    except Exception as e:
        logger.error(f"PDF rendering failed: {str(e)}", exc_info=True)

    return QPixmap()

def cleanup_resources():
    logger.info("Performing final cleanup...")
    try:
        THUMBNAIL_POOL.shutdown(wait=True)
        logger.info("Thread pool shutdown completed")
    except Exception as e:
        logger.error(f"Error during final cleanup: {e}")

def main():
    # Enable high DPI on Windows
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Merger App - Simple")
    app.setApplicationVersion("2.0")
    
    import atexit
    atexit.register(cleanup_resources)
    
    ensure_icon()
    app_icon = QIcon(str(ICON_PATH))
    app.setWindowIcon(app_icon)

    w = SimpleMainWindow()
    w.show()
    
    logger.info("Simple PDF Merger application started successfully")

    try:
        sys.exit(app.exec())
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        cleanup_resources()
        sys.exit(1)

if __name__ == "__main__":
    main()
