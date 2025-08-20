import os
import sys
import pathlib
import tempfile
import logging
import threading
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PyQt6.QtCore import (
    Qt, 
    QSize, 
    QThread, 
    pyqtSignal, 
    QTimer, 
    QEvent
)
from PyQt6.QtGui import (
    QIcon, 
    QPixmap, 
    QAction, 
    QDragEnterEvent, 
    QDropEvent, 
    QKeySequence
)
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
    QCheckBox,
    QSpinBox,
    QGroupBox,
)

# External libraries
from pypdf import PdfReader, PdfWriter
from pdf2image import convert_from_path
from PIL import Image, ImageDraw, ImageFont

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                   handlers=[
                       logging.FileHandler("pdfmerger.log"),
                       logging.StreamHandler()
                   ])
logger = logging.getLogger('PDFMerger')

# Define path for resources
def get_resource_path():
    base_path = pathlib.Path(__file__).resolve().parent
    assets_dir = base_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir

# Get the Poppler path
def get_poppler_path():
    """Find poppler binaries path with multiple fallback options."""
    base_path = pathlib.Path(__file__).resolve().parent
    
    # If running as executable, check for bundled poppler
    if hasattr(sys, '_MEIPASS'):
        bundled_poppler = pathlib.Path(sys._MEIPASS) / "poppler" / "bin"
        if bundled_poppler.exists():
            logger.info(f"Using bundled poppler at: {bundled_poppler}")
            return str(bundled_poppler)
    
    # Check for local poppler installations in order of preference
    local_poppler_paths = [
        base_path / "poppler-25.07.0" / "Library" / "bin",
        base_path / "poppler-24.08.0" / "Library" / "bin", 
        base_path / "poppler-23.11.0" / "Library" / "bin",
        base_path / "poppler" / "Library" / "bin",
        base_path / "poppler" / "bin",
    ]
    
    for poppler_path in local_poppler_paths:
        if poppler_path.exists() and (poppler_path / "pdftoppm.exe").exists():
            logger.info(f"Found local poppler at: {poppler_path}")
            return str(poppler_path)
    
    # Try environment variable
    env_path = os.environ.get("POPPLER_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
        
    # On Windows, try common installation locations
    if sys.platform.startswith('win'):
        common_paths = [
            r"C:\Release-25.07.0-0\Library\bin",
            r"C:\Program Files\poppler-25.07.0\Library\bin",
            r"C:\Program Files\poppler-24.08.0\Library\bin",
            r"C:\Program Files\poppler-23.11.0\Library\bin",
            r"C:\Program Files\poppler\Library\bin",
            r"C:\Program Files\poppler\bin",
            r"C:\poppler\bin",
            os.path.expanduser("~\\poppler\\bin")
        ]
        for path in common_paths:
            if os.path.exists(path) and os.path.exists(os.path.join(path, "pdftoppm.exe")):
                logger.info(f"Found system poppler at: {path}")
                return path
    
    logger.warning("Poppler not found in any standard locations")
    return None

ASSETS_DIR = get_resource_path()
ICON_PATH = ASSETS_DIR / "app_icon.png"
POPPLER_PATH = get_poppler_path()

def validate_poppler():
    """Validate that poppler is available and working."""
    if not POPPLER_PATH:
        return False, "Poppler not found in any standard locations"
    
    # Check if pdftoppm.exe exists
    pdftoppm_path = pathlib.Path(POPPLER_PATH) / "pdftoppm.exe"
    if not pdftoppm_path.exists():
        return False, f"pdftoppm.exe not found in {POPPLER_PATH}"
    
    try:
        # Try to run pdftoppm to verify it works
        import subprocess
        
        # Use CREATE_NO_WINDOW flag on Windows to prevent console window
        creation_flags = 0
        if sys.platform.startswith('win'):
            creation_flags = 0x08000000  # CREATE_NO_WINDOW
            
        result = subprocess.run(
            [str(pdftoppm_path), "-h"], 
            capture_output=True, 
            text=True, 
            timeout=3,  # Reduced timeout
            creationflags=creation_flags if sys.platform.startswith('win') else 0
        )
        
        if result.returncode != 0 and "help" not in result.stderr.lower():
            return False, f"pdftoppm failed to run: {result.stderr}"
        return True, "Poppler is working correctly"
    except subprocess.TimeoutExpired:
        return False, "Poppler validation timed out"
    except Exception as e:
        return False, f"Error validating poppler: {str(e)}"

# Validate poppler on startup
POPPLER_AVAILABLE, POPPLER_STATUS = validate_poppler()
if POPPLER_AVAILABLE:
    logger.info(f"Poppler validation: {POPPLER_STATUS}")
else:
    logger.warning(f"Poppler validation failed: {POPPLER_STATUS}")

# Global configuration - REDUCED for better performance
MAX_WORKERS = min(2, (os.cpu_count() or 1))  # Reduce for stability - use fewer workers
ACTIVE_WORKERS_LIMIT = 1  # Strictly limit to 1 concurrent processing
THUMBNAIL_CACHE_SIZE = 30  # Smaller cache size to reduce memory usage
THUMBNAIL_DPI = 72  # Lower DPI for faster thumbnail generation

@dataclass
class PDFEntry:
    path: pathlib.Path
    pages: int = 0
    thumb: Optional[QIcon] = None
    file_size: int = 0

class WorkerManager:
    """Thread-safe worker management for PDF processing."""
    
    def __init__(self):
        self.thumbnail_workers = {}  # path -> worker
        self.page_workers = {}  # path -> worker
        self.thumbnail_cache = {}  # path -> QIcon (LRU cache)
        self._lock = threading.Lock()
        self._thumbnail_semaphore = threading.Semaphore(ACTIVE_WORKERS_LIMIT)
        self._page_semaphore = threading.Semaphore(ACTIVE_WORKERS_LIMIT)
        self._active_thumbnails = 0
        self._active_page_counts = 0
        self._batch_queue = []  # Queue of paths waiting to be processed
        self._batch_processing = False
        
    def is_processing_thumbnail(self, path: pathlib.Path) -> bool:
        """Check if thumbnail is being processed for this path."""
        with self._lock:
            return path in self.thumbnail_workers
            
    def is_processing_pages(self, path: pathlib.Path) -> bool:
        """Check if page count is being processed for this path."""
        with self._lock:
            return path in self.page_workers
    
    def has_capacity(self) -> bool:
        """Check if we have capacity to process more files."""
        with self._lock:
            return (self._active_thumbnails + self._active_page_counts) < ACTIVE_WORKERS_LIMIT
            
    def get_cached_thumbnail(self, path: pathlib.Path) -> Optional[QIcon]:
        """Get cached thumbnail if available."""
        with self._lock:
            return self.thumbnail_cache.get(path)
            
    def cache_thumbnail(self, path: pathlib.Path, icon: QIcon) -> None:
        """Cache thumbnail with LRU eviction."""
        with self._lock:
            # Simple LRU: remove oldest if at capacity
            if len(self.thumbnail_cache) >= THUMBNAIL_CACHE_SIZE:
                oldest_key = next(iter(self.thumbnail_cache))
                del self.thumbnail_cache[oldest_key]
            self.thumbnail_cache[path] = icon
            
    def start_thumbnail_worker(self, path: pathlib.Path, worker: 'SimpleThumbnailWorker') -> bool:
        """Start thumbnail worker if not already processing and we have capacity."""
        acquired = self._thumbnail_semaphore.acquire(blocking=False)
        if not acquired:
            logger.debug(f"No capacity for thumbnail worker, will try later: {path}")
            return False
            
        with self._lock:
            if path in self.thumbnail_workers:
                self._thumbnail_semaphore.release()  # Release the permit
                return False
                
            self.thumbnail_workers[path] = worker
            self._active_thumbnails += 1
            logger.debug(f"Started thumbnail worker for {path}, active: {self._active_thumbnails}")
            return True
            
    def start_page_worker(self, path: pathlib.Path, worker: 'SimplePageCountWorker') -> bool:
        """Start page count worker if not already processing and we have capacity."""
        acquired = self._page_semaphore.acquire(blocking=False)
        if not acquired:
            logger.debug(f"No capacity for page worker, will try later: {path}")
            return False
            
        with self._lock:
            if path in self.page_workers:
                self._page_semaphore.release()  # Release the permit
                return False
                
            self.page_workers[path] = worker
            self._active_page_counts += 1
            logger.debug(f"Started page worker for {path}, active: {self._active_page_counts}")
            return True
            
    def finish_thumbnail_worker(self, path: pathlib.Path) -> None:
        """Remove finished thumbnail worker and release semaphore permit."""
        with self._lock:
            if path in self.thumbnail_workers:
                self.thumbnail_workers.pop(path)
                self._active_thumbnails -= 1
                logger.debug(f"Finished thumbnail worker for {path}, active: {self._active_thumbnails}")
                
        # Release outside the lock to avoid deadlock
        self._thumbnail_semaphore.release()
            
    def finish_page_worker(self, path: pathlib.Path) -> None:
        """Remove finished page worker and release semaphore permit."""
        with self._lock:
            if path in self.page_workers:
                self.page_workers.pop(path)
                self._active_page_counts -= 1
                logger.debug(f"Finished page worker for {path}, active: {self._active_page_counts}")
                
        # Release outside the lock to avoid deadlock
        self._page_semaphore.release()
            
    def cleanup_all(self) -> None:
        """Clean up all workers and cache."""
        with self._lock:
            # Wait for all workers to finish
            for worker in list(self.thumbnail_workers.values()):
                if worker.isRunning():
                    try:
                        worker.wait(500)  # Wait up to 0.5 second
                    except:
                        pass
                    
            for worker in list(self.page_workers.values()):
                if worker.isRunning():
                    try:
                        worker.wait(500)
                    except:
                        pass
                    
            # Reset semaphores
            for _ in range(self._active_thumbnails):
                try:
                    self._thumbnail_semaphore.release()
                except:
                    pass
                    
            for _ in range(self._active_page_counts):
                try:
                    self._page_semaphore.release()
                except:
                    pass
                    
            self._active_thumbnails = 0
            self._active_page_counts = 0
            self.thumbnail_workers.clear()
            self.page_workers.clear()
            self.thumbnail_cache.clear()
            self._batch_queue.clear()

# Global worker manager
WORKER_MANAGER = WorkerManager()

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

# Optimized background workers
class SimpleThumbnailWorker(QThread):
    result = pyqtSignal(object, object)  # (pathlib.Path, QIcon)
    error = pyqtSignal(object, str)
    finished_processing = pyqtSignal(object)  # (pathlib.Path)

    def __init__(self, path: pathlib.Path, thumb_size: Tuple[int, int] = (140, 180)):
        super().__init__()
        self.path = path
        self.thumb_size = thumb_size
        self.finished.connect(lambda: self.finished_processing.emit(self.path))

    def run(self) -> None:
        try:
            # Check cache first
            cached_icon = WORKER_MANAGER.get_cached_thumbnail(self.path)
            if cached_icon:
                self.result.emit(self.path, cached_icon)
                return
                
            # Fast path for small thumbnails - use first page with low DPI
            qpix = render_page_qpix(self.path, page_index=0, 
                                   max_w=self.thumb_size[0], 
                                   max_h=self.thumb_size[1],
                                   dpi=THUMBNAIL_DPI)  # Use lower DPI
                                   
            if not qpix.isNull():
                icon = QIcon(qpix)
                WORKER_MANAGER.cache_thumbnail(self.path, icon)
                self.result.emit(self.path, icon)
            else:
                self.error.emit(self.path, "Failed to generate thumbnail")
        except Exception as e:
            logger.error(f"Thumbnail generation failed for {self.path}: {str(e)}")
            self.error.emit(self.path, str(e))

class SimplePageCountWorker(QThread):
    counted = pyqtSignal(object, int, int)  # (pathlib.Path, pages, file_size)
    finished_processing = pyqtSignal(object)  # (pathlib.Path)

    def __init__(self, path: pathlib.Path):
        super().__init__()
        self.path = path
        self.finished.connect(lambda: self.finished_processing.emit(self.path))

    def run(self) -> None:
        try:
            # Get file stats first (faster)
            stat = self.path.stat()
            file_size = stat.st_size
            
            # Count pages using pypdf with error handling and timeout protection
            try:
                # Use a faster page counting method that doesn't fully load the document
                reader = PdfReader(str(self.path))
                page_count = len(reader.pages)
                
                self.counted.emit(self.path, page_count, file_size)
            except Exception as e:
                logger.error(f"PDF page counting error: {str(e)}")
                self.counted.emit(self.path, 0, file_size)  # Still emit the file size
                
        except Exception as e:
            logger.error(f"Page counting failed for {self.path}: {str(e)}")
            # Emit default values on error
            self.counted.emit(self.path, 0, 0)

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
                try:
                    reader = PdfReader(str(p))
                    for page in reader.pages:
                        writer.add_page(page)
                    self.progress.emit(int(i / max(1, total) * 100))
                    logger.info(f"Added PDF {i}/{total}: {p}")
                except Exception as e:
                    logger.error(f"Error adding PDF {p}: {str(e)}")
                    self.failed.emit(f"Error processing {p.name}: {str(e)}")
                    return
                
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
            self._dragEnterEvent(event)
            return True
        if obj is self.viewport() and event.type() == QEvent.Type.Drop:
            self._dropEvent(event)
            return True
        return super().eventFilter(obj, event)

    def _dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(str(u.toLocalFile()).lower().endswith(".pdf") for u in urls):
                event.acceptProposedAction()

    def _dropEvent(self, event: QDropEvent):
        paths = [pathlib.Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile() and str(u.toLocalFile()).lower().endswith(".pdf")]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

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
        self.current_path = None  # Track current path to avoid reloading

    def clear_pages(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.current_path = None

    def show_message(self, text):
        self.clear_pages()
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("color: #9aa0a6; font-size: 14px; padding: 20px;")
        self.layout.addWidget(label)

    def load_pdf(self, path, max_width=600):
        # Skip reloading if already showing this PDF
        if self.current_path == path:
            return
            
        self.clear_pages()
        self.current_path = path
        
        if not POPPLER_AVAILABLE:
            self.show_message(f"PDF Preview Not Available\n\n{POPPLER_STATUS}\n\nFile: {path.name}")
            return
            
        self.show_message("Loading PDF...")
        
        # Use a timer to allow the UI to update before loading
        QTimer.singleShot(100, lambda: self._load_pdf_delayed(path, max_width))
    
    def _load_pdf_delayed(self, path, max_width):
        try:
            # Check page count first
            reader = PdfReader(str(path))
            total_pages = len(reader.pages)
            
            # Limit preview pages for performance
            max_preview_pages = min(2, total_pages)  # Reduced to 2 pages max
            
            # Load first few pages for preview with optimized DPI
            images = convert_from_path(
                str(path), 
                first_page=1, 
                last_page=max_preview_pages, 
                dpi=100,  # Reduced DPI for better performance
                poppler_path=POPPLER_PATH,
                thread_count=1,  # Use just 1 thread to avoid creating multiple processes
                use_pdftocairo=True  # Try to use pdftocairo which is faster
            )
            
            # Clear old message
            self.clear_pages()
            self.current_path = path
            
            if images:
                for i, img in enumerate(images):
                    # Optimize image before converting to QPixmap
                    # Resize if too large
                    if img.width > max_width:
                        ratio = max_width / img.width
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                    
                    # Convert PIL image to QPixmap more efficiently
                    from io import BytesIO
                    buf = BytesIO()
                    # Use JPEG for better compression on preview
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.save(buf, format="JPEG", quality=80, optimize=True)
                    
                    qpix = QPixmap()
                    qpix.loadFromData(buf.getvalue(), "JPEG")
                    buf.close()  # Explicitly close buffer
                    
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
                    container_layout.setContentsMargins(5, 5, 5, 5)
                    container_layout.addWidget(page_label)
                    container_layout.addWidget(page_number)
                    
                    self.layout.addWidget(container)
                
                # Add info about total pages if more than preview
                if total_pages > max_preview_pages:
                    info_label = QLabel(f"Showing {max_preview_pages} of {total_pages} pages")
                    info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    info_label.setStyleSheet("color: #9aa0a6; font-style: italic; padding: 10px;")
                    self.layout.addWidget(info_label)
            else:
                self.show_message("No pages could be loaded from this PDF")
                
        except Exception as e:
            logger.error(f"Error loading PDF preview: {str(e)}")
            error_msg = str(e)
            if "poppler" in error_msg.lower():
                self.show_message(f"PDF Preview Error\n\nPoppler is required for PDF preview but is not available.\n\nError: {error_msg}")
            else:
                self.show_message(f"Error loading PDF: {error_msg}")

# Main Window
class SimpleMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Merger App - Simple")
        self.setMinimumSize(1100, 700)
        
        ensure_icon()
        self.app_icon = QIcon(str(ICON_PATH))
        self.setWindowIcon(self.app_icon)
        
        self._pending_files: List[pathlib.Path] = []
        self._batch_timer = QTimer()
        self._batch_timer.timeout.connect(self._process_pending_files)
        self._batch_timer.setSingleShot(True)
        self._active_workers = set()  # Track active workers for cleanup
        self._merge_thread = None

        self._init_ui()
        self._setup_shortcuts()
        self._apply_styles()
        self._update_count()
        
        # Check poppler status and warn user if needed
        if not POPPLER_AVAILABLE:
            QTimer.singleShot(1000, self._show_poppler_warning)
            self.statusBar().showMessage("Warning: PDF thumbnails and preview not available", 8000)
        else:
            # Show welcome message
            self.statusBar().showMessage("Ready - Drag & drop PDF files or use Add PDFs button", 5000)

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

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts for common actions."""
        # Add files shortcut
        add_shortcut = QAction("Add Files", self)
        add_shortcut.setShortcut(QKeySequence("Ctrl+O"))
        add_shortcut.triggered.connect(self.on_add)
        self.addAction(add_shortcut)
        
        # Remove selected shortcut
        remove_shortcut = QAction("Remove Selected", self)
        remove_shortcut.setShortcut(QKeySequence("Delete"))
        remove_shortcut.triggered.connect(self.on_remove)
        self.addAction(remove_shortcut)
        
        # Clear all shortcut
        clear_shortcut = QAction("Clear All", self)
        clear_shortcut.setShortcut(QKeySequence("Ctrl+Shift+N"))
        clear_shortcut.triggered.connect(self.on_reset)
        self.addAction(clear_shortcut)
        
        # Merge shortcut
        merge_shortcut = QAction("Merge", self)
        merge_shortcut.setShortcut(QKeySequence("Ctrl+M"))
        merge_shortcut.triggered.connect(self.on_merge)
        self.addAction(merge_shortcut)
        
        # Select all shortcut
        select_all_shortcut = QAction("Select All", self)
        select_all_shortcut.setShortcut(QKeySequence("Ctrl+A"))
        select_all_shortcut.triggered.connect(self.listw.selectAll)
        self.addAction(select_all_shortcut)
        
        # Update button tooltips with shortcuts
        self.btn_add.setToolTip("Add PDF files (Ctrl+O)")
        self.btn_remove.setToolTip("Remove selected files (Delete)")
        self.btn_reset.setToolTip("Clear all files (Ctrl+Shift+N)")
        self.btn_merge.setToolTip("Merge PDFs (Ctrl+M)")
        self.btn_add_folder.setToolTip("Add all PDFs from a folder")

    def _show_poppler_warning(self):
        """Show warning dialog when poppler is not available."""
        msg = QMessageBox(self)
        msg.setWindowTitle("PDF Preview Not Available")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText("PDF thumbnails and preview are not available")
        msg.setInformativeText(
            f"Poppler utilities are required for PDF thumbnails and preview.\n\n"
            f"Status: {POPPLER_STATUS}\n\n"
            f"PDF merging will still work, but you won't see thumbnails or previews.\n\n"
            f"To fix this issue:\n"
            f"• Ensure poppler binaries are in the application folder\n"
            f"• Or install poppler and add it to your system PATH"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

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
        """Add PDF files to the list with proper throttling."""
        if not paths:
            return
            
        # Limit the number of paths to process at once to avoid overloading
        MAX_PATHS_AT_ONCE = 10  # Reduced from 20
        if len(paths) > MAX_PATHS_AT_ONCE:
            logger.info(f"Too many files ({len(paths)}), limiting initial batch to {MAX_PATHS_AT_ONCE}")
            # Process in batches
            remaining = paths[MAX_PATHS_AT_ONCE:]
            paths = paths[:MAX_PATHS_AT_ONCE]
            # Schedule the rest for later processing
            QTimer.singleShot(2000, lambda: self.add_paths(remaining))  # Increased delay to 2000ms
            
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
            # Use a generic icon first while the thumbnail is loading
            item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            item.setSizeHint(self.listw.gridSize())
            self.listw.addItem(item)
            new_paths.append(p)
        
        if new_paths:
            self._pending_files.extend(new_paths)
            self._batch_timer.stop()
            self._batch_timer.start(500)  # Increased from 200ms to 500ms
            
            logger.info(f"Added {len(new_paths)} files to pending batch")
            self.statusBar().showMessage(f"Added {len(new_paths)} file(s) - Processing...", 4000)

    def _process_pending_files(self):
        """Process pending files with better batch handling and throttling."""
        if not self._pending_files:
            return
            
        # Check if we have capacity
        capacity = WORKER_MANAGER.has_capacity()
        if not capacity:
            logger.debug("No capacity for processing more files, retrying in 1000ms")
            # Re-schedule the timer to try again later
            self._batch_timer.stop()
            self._batch_timer.start(1000)  # Increased to 1000ms
            return
            
        # Get just one file to process at a time
        files_to_process = self._pending_files[:1]
        
        # Remove file we're going to process from the pending list
        self._pending_files = self._pending_files[1:]
        
        logger.info(f"Processing single file (remaining: {len(self._pending_files)})")
        
        # Process each file individually with throttling
        for path in files_to_process:
            self._process_single_file(path)
            
        # If we have more pending files, schedule another run
        if self._pending_files:
            self._batch_timer.stop()
            self._batch_timer.start(800)  # Increased from 200ms to 800ms

    def _process_single_file(self, path: pathlib.Path):
        # Start thumbnail generation if not already processing
        if not WORKER_MANAGER.is_processing_thumbnail(path):
            # Check cache first
            cached_icon = WORKER_MANAGER.get_cached_thumbnail(path)
            if cached_icon:
                self._on_thumb_ready(path, cached_icon)
            else:
                thumb_worker = SimpleThumbnailWorker(path, (self.listw.iconSize().width(), self.listw.iconSize().height()))
                thumb_worker.result.connect(self._on_thumb_ready)
                thumb_worker.error.connect(self._on_thumb_error)
                thumb_worker.finished_processing.connect(WORKER_MANAGER.finish_thumbnail_worker)
                thumb_worker.finished_processing.connect(lambda p: self._active_workers.discard(thumb_worker))
                
                if WORKER_MANAGER.start_thumbnail_worker(path, thumb_worker):
                    self._active_workers.add(thumb_worker)
                    thumb_worker.start()
        
        # Start page counting if not already processing
        if not WORKER_MANAGER.is_processing_pages(path):
            page_worker = SimplePageCountWorker(path)
            page_worker.counted.connect(self._on_pages_ready)
            page_worker.finished_processing.connect(WORKER_MANAGER.finish_page_worker)
            page_worker.finished_processing.connect(lambda p: self._active_workers.discard(page_worker))
            
            if WORKER_MANAGER.start_page_worker(path, page_worker):
                self._active_workers.add(page_worker)
                page_worker.start()

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
            
        # Check if any files are still being processed
        active_processing = len([f for f in self._pending_files]) > 0
        if active_processing:
            reply = QMessageBox.question(
                self, 
                "Processing in Progress", 
                "Some files are still being processed. Do you want to wait and try again?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.statusBar().showMessage("Please wait for file processing to complete...", 3000)
                return
                
        out_dir = QFileDialog.getExistingDirectory(self, "Choose output directory", str(pathlib.Path.home()))
        if not out_dir:
            return
            
        # Check if output file already exists
        out_path = pathlib.Path(out_dir) / "merged.pdf"
        if out_path.exists():
            reply = QMessageBox.question(
                self, 
                "File Exists", 
                f"File '{out_path.name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
                
        paths = [self.listw.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.listw.count())]
        
        # Validate all files exist
        missing_files = [p for p in paths if not p.exists()]
        if missing_files:
            QMessageBox.warning(
                self, 
                "Missing Files", 
                f"Some files no longer exist:\n{chr(10).join(str(f) for f in missing_files[:3])}"
                + (f"\n... and {len(missing_files) - 3} more" if len(missing_files) > 3 else "")
            )
            return
            
        self.progress.setValue(0)
        self.statusBar().showMessage(f"Starting merge of {len(paths)} PDF files...")
        
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
        
        # Check output file size
        try:
            output_file = pathlib.Path(out_path)
            file_size = output_file.stat().st_size
            size_mb = file_size / (1024 * 1024)
            if size_mb > 1024:
                size_str = f"{size_mb/1024:.1f} GB"
            else:
                size_str = f"{size_mb:.1f} MB"
                
            self.statusBar().showMessage(f"Successfully merged to {output_file.name} ({size_str})", 10000)
            
            # Show success dialog with options
            msg = QMessageBox(self)
            msg.setWindowTitle("Merge Complete")
            msg.setText(f"Successfully merged {self.listw.count()} PDF files!")
            msg.setInformativeText(f"Output: {output_file.name}\nSize: {size_str}\nLocation: {output_file.parent}")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            
            # Add button to open folder
            open_folder_btn = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
            
            result = msg.exec()
            if msg.clickedButton() == open_folder_btn:
                # Open folder containing the merged file
                import subprocess
                # Use CREATE_NO_WINDOW flag on Windows to prevent console window
                creation_flags = 0
                if sys.platform.startswith('win'):
                    creation_flags = 0x08000000  # CREATE_NO_WINDOW
                    subprocess.run(['explorer', '/select,', str(output_file)], 
                                   creationflags=creation_flags)
                elif sys.platform.startswith('darwin'):
                    subprocess.run(['open', '-R', str(output_file)])
                else:
                    subprocess.run(['xdg-open', str(output_file.parent)])
                    
        except Exception as e:
            logger.error(f"Error checking output file: {e}")
            self.statusBar().showMessage(f"Merge completed: {out_path}", 8000)
            QMessageBox.information(self, "Merge Complete", f"Merged PDF saved to:\n{out_path}")

    def _on_merge_failed(self, err: str):
        self._toggle_controls(True)
        self.progress.setValue(0)
        self.statusBar().showMessage("Merge failed - check logs for details", 8000)
        
        # Better error message
        if "permission" in err.lower():
            error_msg = "Permission denied. The output file might be open in another application or you don't have write permissions."
        elif "memory" in err.lower() or "ram" in err.lower():
            error_msg = "Not enough memory to process these PDF files. Try merging fewer files at once."
        elif "corrupt" in err.lower() or "invalid" in err.lower():
            error_msg = "One or more PDF files appear to be corrupted or invalid."
        else:
            error_msg = f"Merge operation failed:\n{err}"
            
        QMessageBox.critical(self, "Merge Failed", error_msg)

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
        
        # Use a delay before loading the preview to prevent UI freeze
        QTimer.singleShot(200, lambda: self.preview_scroll.load_pdf(path))
        
        file_size = item.data(Qt.ItemDataRole.UserRole + 2) or 0
        size_mb = file_size / (1024 * 1024) if file_size > 0 else 0
        size_str = f" • {size_mb:.1f} MB" if file_size > 0 else ""
        self.meta_label.setText(f"{path.name} — {pages} page(s){size_str}\n{path}")

    def closeEvent(self, event):
        logger.info("Application closing, cleaning up resources...")
        
        # Stop batch timer
        self._batch_timer.stop()
        
        # Clean up active workers
        logger.info(f"Waiting for {len(self._active_workers)} active workers to finish...")
        for worker in list(self._active_workers):
            if worker.isRunning():
                try:
                    worker.terminate()  # Forcefully terminate workers to avoid hang
                except:
                    pass
        
        # Clean up worker manager
        try:
            WORKER_MANAGER.cleanup_all()
            logger.info("Worker manager cleanup completed")
        except Exception as e:
            logger.error(f"Error during worker manager cleanup: {e}")
        
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

def render_page_qpix(path: pathlib.Path, page_index: int = 0, max_w: Optional[int] = None, max_h: Optional[int] = None, dpi: int = 72) -> QPixmap:
    if not POPPLER_AVAILABLE:
        logger.error(f"Cannot render PDF page - {POPPLER_STATUS}")
        return QPixmap()
        
    try:
        # Create a temporary directory that will be cleaned up automatically
        with tempfile.TemporaryDirectory() as tmp_dir:
            import subprocess
            
            # Use pdftoppm directly for better performance and control
            if sys.platform.startswith('win'):
                pdftoppm_path = os.path.join(POPPLER_PATH, 'pdftoppm.exe')
                creation_flags = 0x08000000  # CREATE_NO_WINDOW
            else:
                pdftoppm_path = os.path.join(POPPLER_PATH, 'pdftoppm')
                creation_flags = 0
                
            output_prefix = os.path.join(tmp_dir, "thumb")
            
            # Run pdftoppm subprocess directly (faster than pdf2image for thumbnails)
            cmd = [
                pdftoppm_path,
                "-jpeg",       # Output as JPEG
                "-singlefile", # Only one output file
                "-r", str(dpi), # Lower DPI for thumbnails
                "-f", str(page_index + 1),  # First page
                "-l", str(page_index + 1),  # Last page
                str(path),
                output_prefix
            ]
            
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags if sys.platform.startswith('win') else 0
            )
            
            # Check if file was created
            output_file = f"{output_prefix}.jpg"
            if os.path.exists(output_file):
                qpix = QPixmap(output_file)
                
                # Scale if needed
                if max_w and qpix.width() > max_w:
                    qpix = qpix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
                
                return qpix
            else:
                # Fall back to pdf2image if direct approach fails
                logger.debug(f"pdftoppm direct approach failed, falling back to pdf2image")
                images = convert_from_path(
                    str(path),
                    first_page=page_index + 1,
                    last_page=page_index + 1,
                    dpi=dpi,
                    poppler_path=POPPLER_PATH,
                    thread_count=1,  # Use single thread to avoid multiple processes
                    use_pdftocairo=True,  # Try to use pdftocairo which is faster
                    output_folder=tmp_dir
                )
                
                if images:
                    # Convert PIL image to QPixmap
                    img = images[0]
                    from io import BytesIO
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=80, optimize=True)
                    qpix = QPixmap()
                    qpix.loadFromData(buf.getvalue())
                    buf.close()
                    
                    # Scale if needed
                    if max_w and qpix.width() > max_w:
                        qpix = qpix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
                        
                    return qpix
    
    except Exception as e:
        logger.error(f"PDF rendering failed for {path}: {str(e)}", exc_info=True)
        
    # Return empty pixmap on failure
    return QPixmap()

def cleanup_resources():
    logger.info("Performing final cleanup...")
    try:
        WORKER_MANAGER.cleanup_all()
        logger.info("Worker manager cleanup completed")
    except Exception as e:
        logger.error(f"Error during final cleanup: {e}")

def main():
    # When freezing with PyInstaller, prevent showing console window
    if sys.platform.startswith('win') and hasattr(sys, 'frozen'):
        import win32gui
        import win32con
        # Hide console window
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
    
    # Enable high DPI on Windows
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
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
