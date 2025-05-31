# PyQt-based 96-Well Plate Viewer

import sys
import os
import re
import numpy as np
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QGridLayout, QPushButton, QVBoxLayout, QComboBox, QFileDialog, QScrollArea, QHBoxLayout, QStackedLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QCheckBox, QButtonGroup, QProgressBar)
from PyQt5.QtGui import QPixmap, QImage, QWheelEvent, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QEvent, QObject
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtCore import QMutex, QTimer
from PIL import Image


# Utility functions for caching images as NumPy arrays
def cache_grayscale_image_as_numpy(image_path):
    """Cache a grayscale image as a NumPy array."""
    try:
        img = Image.open(image_path).convert("L")
        return np.array(img)  # Convert to NumPy array
    except Exception as e:
        print(f"Error caching grayscale image: {e}")
        return None

def cache_gfp_overlay_as_numpy(image_path):
    """Cache a GFP overlay as a NumPy array."""
    try:
        img = Image.open(image_path).convert("L")
        img_array = np.array(img)  # Convert to NumPy array

        # Create an RGBA array
        height, width = img_array.shape
        rgba_array = np.zeros((height, width, 4), dtype=np.uint8)

        # Set the green channel and alpha channel
        rgba_array[:, :, 1] = img_array  # Green channel
        rgba_array[:, :, 3] = 128        # Alpha channel (semi-transparent)

        return rgba_array
    except Exception as e:
        print(f"Error caching GFP overlay: {e}")
        return None

def numpy_to_qpixmap(np_array):
    """Convert a NumPy array to a QPixmap."""
    try:
        if isinstance(np_array, np.ndarray):  # Ensure input is a NumPy array
            if np_array.ndim == 2:  # Grayscale image
                height, width = np_array.shape
                qimg = QImage(np_array.data, width, height, QImage.Format_Grayscale8)
            elif np_array.ndim == 3:  # RGBA image
                height, width, _ = np_array.shape
                qimg = QImage(np_array.data, width, height, QImage.Format_RGBA8888)
            else:
                raise ValueError("Unsupported NumPy array shape for conversion.")
            return QPixmap.fromImage(qimg)
        else:
            raise TypeError("Input to numpy_to_qpixmap must be a NumPy array.")
    except Exception as e:
        print(f"Error converting NumPy array to QPixmap: {e}")
        return None
    
class PlateLoadingThread(QThread):
    images_loaded = pyqtSignal(dict)

    def __init__(self, image_data, current_plate):
        super().__init__()
        self.loading_threads = []
        self.image_data = image_data
        self.current_plate = current_plate

    def run(self):
        wells_by_plate = [d for d in self.image_data if d["plate"] == self.current_plate]
        loaded_images = {}
        for d in wells_by_plate:
            well = d["well"]
            path = d["path"]
            img_array = cache_grayscale_image_as_numpy(path)
            if img_array is not None:
                loaded_images[well] = img_array
        self.images_loaded.emit(loaded_images)

class CachingThread(QThread):
    finished = pyqtSignal(dict)  # Signal to send cached data to the main thread

    def __init__(self, well, image_data, current_plate):
        super().__init__()
        self.well = well
        self.image_data = image_data
        self.current_plate = current_plate

    def run(self):
        plate_images = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == self.well]
        cached_data = {}

        for image in plate_images:
            # Cache grayscale image as NumPy array
            if image["path"] not in cached_data:
                img_array = cache_grayscale_image_as_numpy(image["path"])
                if img_array is not None:
                    cached_data[image["path"]] = img_array

            # Cache GFP overlay as NumPy array
            if image["is_gfp"]:
                cache_key = f"{image['path']}_overlay"
                if cache_key not in cached_data:
                    overlay_array = cache_gfp_overlay_as_numpy(image["path"])
                    if overlay_array is not None:
                        cached_data[cache_key] = overlay_array

        # Emit the cached data
        self.finished.emit(cached_data)

class ThreadedLoader(QObject):
    image_data_ready = pyqtSignal(list)

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def load_images(self, folder):
        """Load image metadata from the specified folder (no image loading yet)."""
        if not folder:
            return

        pattern = re.compile(r"_(?P<plate>plate\d+)_.*?(?P<well>[A-H](?:1[0-2]|[1-9]))[^\n]*?(?P<timepoint>\d{2}d\d{2}h\d{2}m)")
        self.image_data = []
        files = sorted(os.listdir(folder))
        for fname in files:
            if not fname.lower().endswith(".tif"):
                continue
            match = pattern.search(fname)
            if not match:
                continue
            meta = match.groupdict()
            plate = meta["plate"].upper()
            well = meta["well"]
            timepoint = meta["timepoint"]
            is_gfp = "GFP" in fname.upper()
            self.image_data.append({
                "plate": plate,
                "well": well,
                "timepoint": timepoint,
                "path": os.path.join(folder, fname),
                "filename": fname,
                "is_gfp": is_gfp
            })

        self.plates = sorted(set(d["plate"] for d in self.image_data))
        self.plate_selector.clear()
        self.plate_selector.addItems(self.plates)
        self.update_plate()

class LoadingThread(QThread):
    image_data_ready = pyqtSignal(list)

    def __init__(self, folder):
        super().__init__()
        self.loader = ThreadedLoader(folder)
        self.loader.image_data_ready.connect(self.emit_result)

    def run(self):
        self.loader.load_images()

    def emit_result(self, image_data):
        self.image_data_ready.emit(image_data)

class ZoomableGraphicsView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.black)
        self.installEventFilter(self)

    def wheelEvent(self, event: QWheelEvent):
        zoom_in_factor = 1.25
        zoom_out_factor = 0.8
        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)

    def get_transform(self):
        return self.transform()

    def set_transform(self, transform):
        self.setTransform(transform)

class PlateViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("96-Well Plate Viewer")

        # Initialize attributes
        self.image_data = []
        self.plates = []
        self.caching_threads = []
        self.loading_threads = []
        self.current_plate = None
        self.current_timepoint = None
        self.current_well = None
        self.current_filename = ""
        self.timepoint_btns = {}
        self.zoom_state = None
        self.thumbnail_cache = {}
        self.well_cache = {}  # Cache for current and next well images
        self.cache_limit = 10
        self.checked_wells = {}

        self.cache_mutex = QMutex()

        # Plate selector
        self.plate_selector = QComboBox()
        self.plate_selector.currentIndexChanged.connect(self.update_plate)

        # Stacked layout for grid and detail views
        self.stacked_layout = QStackedLayout()

        # Grid view
        self.grid_widget = QWidget()
        self.grid_widget.setStyleSheet("background-color: black")
        self.grid_layout = QGridLayout()
        self.grid_layout.setHorizontalSpacing(2)
        self.grid_layout.setVerticalSpacing(0)
        self.grid_widget.setLayout(self.grid_layout)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.grid_widget)
        self.scroll_area.setWidgetResizable(True)
        self.stacked_layout.addWidget(self.scroll_area)
        self.scroll_area.setAlignment(Qt.AlignCenter)

        # Hide the grid until wells are loaded
        #self.scroll_area.hide()

        # Detail view
        self.detail_widget = QWidget()
        self.detail_layout = QVBoxLayout()
        self.detail_widget.setLayout(self.detail_layout)

        self.detail_label = QLabel("")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_layout.addWidget(self.detail_label)

        self.detail_timepoint_buttons = QHBoxLayout()
        self.detail_layout.addLayout(self.detail_timepoint_buttons)

        self.graphics_view = ZoomableGraphicsView()
        self.scene = QGraphicsScene()
        self.graphics_view.setScene(self.scene)
        self.detail_layout.addWidget(self.graphics_view)

        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("\u2190 Previous [S]")
        self.next_btn = QPushButton("Next [F] \u2192")
        self.back_btn = QPushButton("Back to Plate View")
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(self.back_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(self.next_btn)
        self.detail_layout.addLayout(nav_layout)

        self.prev_btn.clicked.connect(self.handle_prev)
        self.next_btn.clicked.connect(self.handle_next)
        self.back_btn.clicked.connect(self.handle_back)

        self.stacked_layout.addWidget(self.detail_widget)

        # Right panel
        self.right_panel = QVBoxLayout()

        # Right panel widget
        self.right_panel_widget = QWidget()
        self.right_panel_widget.setLayout(self.right_panel)
        self.right_panel_widget.hide()  # Initially hidden

        # GFP Toggle
        self.gfp_toggle = QCheckBox("GFP show/hide [W]")
        self.gfp_toggle.setStyleSheet("color: green")
        self.gfp_toggle.setChecked(True)
        self.gfp_toggle.toggled.connect(self.update_gfp_toggle)
        self.right_panel.addWidget(self.gfp_toggle)

        # Checkboxes
        self.singlet_checkbox = QCheckBox("singlet [1]")
        self.doublet_checkbox = QCheckBox("doublet [2]")
        self.inconclusive_checkbox = QCheckBox("inconclusive [3]")

        self.singlet_checkbox.setStyleSheet("color: blue")
        self.doublet_checkbox.setStyleSheet("color: red")
        self.inconclusive_checkbox.setStyleSheet("color: orange")

        self.checkbox_group = QButtonGroup()
        self.checkbox_group.setExclusive(False)
        for cb in [self.singlet_checkbox, self.doublet_checkbox, self.inconclusive_checkbox]:
            self.checkbox_group.addButton(cb)
            self.right_panel.addWidget(cb)

        self.singlet_checkbox.toggled.connect(lambda state: self.toggle_checkmark("singlet", state))
        self.doublet_checkbox.toggled.connect(lambda state: self.toggle_checkmark("doublet", state))
        self.inconclusive_checkbox.toggled.connect(lambda state: self.toggle_checkmark("inconclusive", state))

        # Top bar for plate selector
        self.top_bar = QHBoxLayout()
        self.top_bar.addWidget(QLabel("Plate:"))
        self.top_bar.addWidget(self.plate_selector)
        self.top_bar.addStretch()  # Add stretch to push the dropdown to the left

        # Left panel (stacked layout for grid and detail views)
        self.left_panel_layout = QVBoxLayout()
        self.left_panel_layout.addLayout(self.top_bar)  # Add the top bar
        self.left_panel_layout.addLayout(self.stacked_layout)  # Add the stacked layout (grid and detail views)

        # Main layout
        self.main_layout = QHBoxLayout()  # Main layout for left and right panels
        self.main_layout.addLayout(self.left_panel_layout)  # Add the left panel
        self.main_layout.addWidget(self.right_panel_widget)  # Add the right panel to the right-hand side

        # Set the main layout
        self.setLayout(self.main_layout)

        self.installEventFilter(self)

        # Add these lines to show the grid immediately
        self.update_grid()  # Create the well buttons
        self.scroll_area.show()  # Make sure the grid is visible

        # Prompt for folder and start loading thread
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            self.load_images(folder)
            self.show()
        #    self.loading_thread = LoadingThread(folder)
        #    self.loading_thread.image_data_ready.connect(self.on_image_data_ready)
        #    self.loading_thread.start()

    def load_images(self, folder):
        """Load image metadata from the specified folder (no image loading yet)."""
        if not folder:
            return

        pattern = re.compile(r"_(?P<plate>plate\d+)_.*?(?P<well>[A-H](?:1[0-2]|[1-9]))[^\n]*?(?P<timepoint>\d{2}d\d{2}h\d{2}m)")
        self.image_data = []
        files = sorted(os.listdir(folder))
        for fname in files:
            if not fname.lower().endswith(".tif"):
                continue
            match = pattern.search(fname)
            if not match:
                continue
            meta = match.groupdict()
            plate = meta["plate"].upper()
            well = meta["well"]
            timepoint = meta["timepoint"]
            is_gfp = "GFP" in fname.upper()
            self.image_data.append({
                "plate": plate,
                "well": well,
                "timepoint": timepoint,
                "path": os.path.join(folder, fname),
                "filename": fname,
                "is_gfp": is_gfp
            })

        self.plates = sorted(set(d["plate"] for d in self.image_data))
        self.plate_selector.clear()
        self.plate_selector.addItems(self.plates)
        self.update_plate()

    def on_image_data_ready(self, image_data):
        self.image_data = image_data
        #print(f"Loaded image data: {self.image_data}")
        self.plates = sorted(set(d["plate"] for d in self.image_data))
        self.plate_selector.addItems(self.plates)
        self.update_plate()
        #self.start_plate_loading_thread()  # <-- Only call here!
        self.show()

    def on_loading_finished(self):
        """Show the main window after loading is complete."""
        self.update_plate()  # Update the plate selector and grid
        self.show()  # Show the main window

    def toggle_checkmark(self, label, state):
        key = (self.current_plate, self.current_well)
        if state:
            self.checked_wells[key] = label
        else:
            # Remove the label for the current well if it matches the toggled-off label
            if key in self.checked_wells and self.checked_wells[key] == label:
                del self.checked_wells[key]

        # Refresh the UI to reflect the changes
        self.refresh_checkboxes()
        self.update_grid()

    def eventFilter(self, source, event):
        if event.type() == QEvent.KeyPress and self.stacked_layout.currentWidget() == self.detail_widget:
            if event.key() == Qt.Key_A:
                self.zoom_state = self.graphics_view.get_transform()
                self.prev_timepoint()
            elif event.key() == Qt.Key_D:
                self.zoom_state = self.graphics_view.get_transform()
                self.next_timepoint()
            elif event.key() == Qt.Key_W:  # Toggle GFP on/off
                self.gfp_toggle.setChecked(not self.gfp_toggle.isChecked())
            if event.key() == Qt.Key_1:  # Toggle singlet
                self.singlet_checkbox.setChecked(not self.singlet_checkbox.isChecked())
                print(f"Singlet toggled: {self.singlet_checkbox.isChecked()}")
            elif event.key() == Qt.Key_2:  # Toggle doublet
                self.doublet_checkbox.setChecked(not self.doublet_checkbox.isChecked())
                print(f"Doublet toggled: {self.doublet_checkbox.isChecked()}")
            elif event.key() == Qt.Key_3:  # Toggle inconclusive
                self.inconclusive_checkbox.setChecked(not self.inconclusive_checkbox.isChecked())
                print(f"Inconclusive toggled: {self.inconclusive_checkbox.isChecked()}")
            elif event.key() == Qt.Key_F:  # Go to the next well
                self.handle_next()
            elif event.key() == Qt.Key_S:  # Go to the previous well
                self.handle_prev()
        return super().eventFilter(source, event)

    def refresh_checkboxes(self):
        key = (self.current_plate, self.current_well)
        current_label = self.checked_wells.get(key, None)

        self.singlet_checkbox.blockSignals(True)
        self.doublet_checkbox.blockSignals(True)
        self.inconclusive_checkbox.blockSignals(True)

        self.singlet_checkbox.setChecked(current_label == "singlet")
        self.doublet_checkbox.setChecked(current_label == "doublet")
        self.inconclusive_checkbox.setChecked(current_label == "inconclusive")

        self.singlet_checkbox.blockSignals(False)
        self.doublet_checkbox.blockSignals(False)
        self.inconclusive_checkbox.blockSignals(False)

    def open_detail_view(self, well):
        self.zoom_state = None
        self.current_well = well
        self.scene.clear()

        # Cache all timepoints for the current well
        self.cache_well_images(well)

        # Filter images for the current plate and well
        plate_images = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == well]
        self.current_timepoint = sorted(set(d["timepoint"] for d in plate_images))[0]
        self.display_detail_image()

        # Get the grayscale image filename
        grayscale_image = next((d for d in plate_images if not d["is_gfp"] and d["timepoint"] == self.current_timepoint), None)
        filename = grayscale_image["filename"] if grayscale_image else "No grayscale image available"

        # Set the detail label to show the well name and filename
        self.detail_label.setText(f"{well} - {filename}")

        # Clear existing timepoint buttons
        for i in reversed(range(self.detail_timepoint_buttons.count())):
            self.detail_timepoint_buttons.itemAt(i).widget().setParent(None)

        # Create timepoint buttons (deduplicated)
        self.timepoint_btns = {}
        unique_timepoints = sorted(set(d["timepoint"] for d in plate_images))
        for timepoint in unique_timepoints:
            btn = QPushButton(timepoint)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, tp=timepoint: self.update_timepoint(tp))
            self.detail_timepoint_buttons.addWidget(btn)
            self.timepoint_btns[timepoint] = btn

        self.highlight_active_timepoint()
        self.stacked_layout.setCurrentWidget(self.detail_widget)
        self.right_panel_widget.show()  # Show the right panel

        # Preload the next wells after entering the current well
        QTimer.singleShot(100, lambda: self.preload_next_wells(num_wells=5))

    def cache_well_images(self, well):
        """Cache all timepoints for the given well using a background thread."""
        if well in self.well_cache:
            return  # Already cached

        self.well_cache[well] = {}  # Mark the well as being cached

        # Use the thread manager that tracks threads
        self.start_caching_thread(well)

    def update_thumbnail_cache(self, cached_data):
        self.thumbnail_cache.update(cached_data)

    def preload_next_wells(self, num_wells=5):
        """Preload images for the next `num_wells` wells."""
        if not self.current_well:
            return

        row = "ABCDEFGH"
        all_wells = [f"{r}{c}" for r in row for c in range(1, 13)]
        idx = all_wells.index(self.current_well)

        for offset in range(1, num_wells + 1):
            if idx + offset < len(all_wells):
                next_well = all_wells[idx + offset]
                if next_well not in self.well_cache:
                    print(f"Preloading well: {next_well}")
                    self.start_caching_thread(next_well)
                else:
                    print(f"Well {next_well} is already cached.")

    def start_caching_thread(self, well):
        """Start a background thread to cache images for the given well."""
        thread = CachingThread(well, self.image_data, self.current_plate)
        thread.finished.connect(self.cleanup_caching_thread)
        thread.finished.connect(self.update_thumbnail_cache)
        thread.start()
        self.caching_threads.append(thread)

    def cleanup_caching_thread(self, *args):
        # Remove finished threads from the list
        self.caching_threads = [t for t in self.caching_threads if t.isRunning()]

    def highlight_active_timepoint(self):
        """Highlight the active timepoint button."""
        for tp, btn in self.timepoint_btns.items():
            btn.setChecked(tp == self.current_timepoint)

    def update_plate(self):
        self.current_plate = self.plate_selector.currentText()
        self.update_grid()
        #self.start_plate_loading_thread()  # <-- Only call here!
    
    def on_caching_finished(self):
        """Handle the completion of the caching thread."""
        print("Caching for the well is complete.")
        self.update_grid()

    def update_grid(self):
        # Clear the existing grid layout
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Add clickable well name buttons in a grid (no image loading at all)
        for i, row in enumerate("ABCDEFGH"):
            for j in range(1, 13):
                well = f"{row}{j}"
                btn = QPushButton(well)
                btn.setFixedSize(60, 60)
                btn.setStyleSheet(
                    "color: white; background-color: #222; font-weight: bold; font-size: 14px; border: 1px solid #444;"
                )
                btn.clicked.connect(lambda _, w=well: self.open_detail_view(w))
                self.grid_layout.addWidget(btn, i, j)

    def update_timepoint(self, tp, is_gfp=False):
        self.zoom_state = self.graphics_view.get_transform()
        self.current_timepoint = tp
        self.display_detail_image(is_gfp=is_gfp)
        self.highlight_active_timepoint()

    def display_detail_image(self, is_gfp=False):
        # Preserve the current zoom state
        current_zoom_state = self.graphics_view.get_transform()

        self.scene.clear()
        # Filter images for the current plate, well, and timepoint
        matches = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == self.current_well and d["timepoint"] == self.current_timepoint]
        if not matches:
            print(f"No images found for plate {self.current_plate}, well {self.current_well}, timepoint {self.current_timepoint}")
            return

        # Identify grayscale and GFP images
        grayscale_image = next((d for d in matches if not d["is_gfp"]), None)
        gfp_image = next((d for d in matches if d["is_gfp"]), None)

        # Always display the grayscale image
        if grayscale_image:
            np_array = self.thumbnail_cache.get(grayscale_image["path"])
            if isinstance(np_array, np.ndarray):
                pixmap = numpy_to_qpixmap(np_array)
                if pixmap:
                    item = QGraphicsPixmapItem(pixmap)
                    self.scene.addItem(item)

        # Overlay the GFP image if the toggle is checked
        if self.gfp_toggle.isChecked() and gfp_image:
            cache_key = f"{gfp_image['path']}_overlay"
            np_array = self.thumbnail_cache.get(cache_key)
            if isinstance(np_array, np.ndarray):
                pixmap = numpy_to_qpixmap(np_array)
                if pixmap:
                    item = QGraphicsPixmapItem(pixmap)
                    self.scene.addItem(item)

        # Restore the zoom state
        if current_zoom_state:
            self.graphics_view.set_transform(current_zoom_state)
        else:
            self.graphics_view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def handle_prev(self):
        self.zoom_state = None
        self.go_to_prev_well()
        self.refresh_checkboxes()

    def handle_next(self):
        self.zoom_state = None
        self.go_to_next_well()
        self.refresh_checkboxes()

    def handle_back(self):
        self.zoom_state = None
        self.stacked_layout.setCurrentWidget(self.scroll_area)
        self.right_panel_widget.hide()
        self.refresh_checkboxes()

    def go_to_prev_well(self):
        if not self.current_well:
            return
        row = "ABCDEFGH"
        all_wells = [f"{r}{c}" for r in row for c in range(1, 13)]
        idx = all_wells.index(self.current_well)
        if idx > 0:
            self.open_detail_view(all_wells[idx - 1])

    def go_to_next_well(self):
        if not self.current_well:
            return
        row = "ABCDEFGH"
        all_wells = [f"{r}{c}" for r in row for c in range(1, 13)]
        idx = all_wells.index(self.current_well)
        if idx < len(all_wells) - 1:
            self.open_detail_view(all_wells[idx + 1])

    def prev_timepoint(self):
        plate_images = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == self.current_well]
        sorted_timepoints = sorted(set(d["timepoint"] for d in plate_images))
        idx = sorted_timepoints.index(self.current_timepoint)
        if idx > 0:
            self.update_timepoint(sorted_timepoints[idx - 1])

    def next_timepoint(self):
        plate_images = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == self.current_well]
        sorted_timepoints = sorted(set(d["timepoint"] for d in plate_images))
        idx = sorted_timepoints.index(self.current_timepoint)
        if idx < len(sorted_timepoints) - 1:
            self.update_timepoint(sorted_timepoints[idx + 1])

    def update_gfp_toggle(self):
        """Refresh the display when the GFP toggle is changed."""
        self.display_detail_image()

    def start_plate_loading_thread(self):
        """Start a background thread to load the initial plate."""
        thread = PlateLoadingThread(self.image_data, self.current_plate)
        thread.images_loaded.connect(self.update_grid_with_images)
        thread.finished.connect(self.show_grid_after_loading)
        thread.finished.connect(lambda: self.cleanup_loading_thread(thread))
        thread.start()
        self.loading_threads.append(thread)

    def cleanup_loading_thread(self, thread):
        # Remove finished threads from the list
        self.loading_threads = [t for t in self.loading_threads if t.isRunning()]

    def show_grid_after_loading(self):
        """Show the grid after all wells have been loaded."""
        self.scroll_area.show()  # Make the grid visible
    
    
    def update_grid_with_images(self, loaded_images):
        """Update the grid with all loaded images."""
        for i in range(self.grid_layout.count()):
            container_widget = self.grid_layout.itemAt(i).widget()
            stacked_layout = container_widget.layout()
            image_label = stacked_layout.itemAt(0).widget()  # The image label is the first widget
            well_label = stacked_layout.itemAt(2).widget()   # The well label is the third widget
            well = well_label.text()
            if well in loaded_images:
                np_array = loaded_images[well]
                pixmap = numpy_to_qpixmap(np_array)
                if pixmap:
                    image_label.setPixmap(pixmap)
                    self.thumbnail_cache[well] = np_array

    def on_plate_loading_finished(self):
        """Handle the completion of the plate loading."""
        print("Plate loading complete.")

    def update_well_image(self, well, pixmap):
        """Update the grid with the loaded image for a specific well."""
        for i in range(self.grid_layout.count()):
            container_widget = self.grid_layout.itemAt(i).widget()
            stacked_layout = container_widget.layout()
            well_label = stacked_layout.itemAt(1).widget()  # The well label is the second widget
            if well_label.text() == well:
                image_label = stacked_layout.itemAt(0).widget()  # The image label is the first widget
                image_label.setPixmap(pixmap)
                break
    

    def add_to_thumbnail_cache(self, path, pixmap):
        """Add a pixmap to the thumbnail cache with a size limit."""
        if len(self.thumbnail_cache) >= self.cache_limit:
            # Remove the oldest cached item
            self.thumbnail_cache.pop(next(iter(self.thumbnail_cache)))
        self.thumbnail_cache[path] = pixmap

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = PlateViewer()
    viewer.resize(1000, 800)
    sys.exit(app.exec_())
