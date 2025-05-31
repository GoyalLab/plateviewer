# PyQt-based 96-Well Plate Viewer

import sys
import os
import re
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QGridLayout, QPushButton, QVBoxLayout, QComboBox, QFileDialog, QScrollArea,
    QHBoxLayout, QStackedLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QCheckBox, QButtonGroup
)
from PyQt5.QtGui import QPixmap, QImage, QWheelEvent
from PyQt5.QtCore import Qt, QEvent
from PIL import Image

def cache_grayscale_image_as_numpy(image_path):
    try:
        img = Image.open(image_path).convert("L")
        return np.array(img)
    except Exception as e:
        print(f"Error caching grayscale image: {e}")
        return None

def cache_gfp_overlay_as_numpy(image_path):
    try:
        img = Image.open(image_path).convert("L")
        img_array = np.array(img)
        height, width = img_array.shape
        rgba_array = np.zeros((height, width, 4), dtype=np.uint8)
        rgba_array[:, :, 1] = img_array
        rgba_array[:, :, 3] = 128
        return rgba_array
    except Exception as e:
        print(f"Error caching GFP overlay: {e}")
        return None

def numpy_to_qpixmap(np_array):
    try:
        if isinstance(np_array, np.ndarray):
            if np_array.ndim == 2:
                height, width = np_array.shape
                qimg = QImage(np_array.data, width, height, QImage.Format_Grayscale8)
            elif np_array.ndim == 3:
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

        self.image_data = []
        self.plates = []
        self.current_plate = None
        self.current_timepoint = None
        self.current_well = None
        self.current_filename = ""
        self.timepoint_btns = {}
        self.zoom_state = None
        self.thumbnail_cache = {}
        self.checked_wells = {}

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
        self.right_panel_widget = QWidget()
        self.right_panel_widget.setLayout(self.right_panel)
        self.right_panel_widget.hide()

        self.gfp_toggle = QCheckBox("GFP show/hide [W]")
        self.gfp_toggle.setStyleSheet("color: green")
        self.gfp_toggle.setChecked(True)
        self.gfp_toggle.toggled.connect(self.update_gfp_toggle)
        self.right_panel.addWidget(self.gfp_toggle)

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
        self.top_bar.addStretch()

        # Left panel (stacked layout for grid and detail views)
        self.left_panel_layout = QVBoxLayout()
        self.left_panel_layout.addLayout(self.top_bar)
        self.left_panel_layout.addLayout(self.stacked_layout)

        # Main layout
        self.main_layout = QHBoxLayout()
        self.main_layout.addLayout(self.left_panel_layout)
        self.main_layout.addWidget(self.right_panel_widget)

        self.setLayout(self.main_layout)
        self.installEventFilter(self)

        # Prompt for folder and load images immediately
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            self.load_images(folder)
            self.show()

    def load_images(self, folder):
        if not folder:
            return
        pattern = re.compile(r"_(?P<plate>plate\d+)_.*?(?P<well>[A-H](?:1[0-2]|[1-9]))[^\n]*?(?P<timepoint>\d{2}d\d{2}h\d{2}m)")
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
        self.plate_selector.addItems(self.plates)
        self.update_plate()

    def update_plate(self):
        self.current_plate = self.plate_selector.currentText()
        self.update_grid()

    def update_grid(self):
        for i in reversed(range(self.grid_layout.count())):
            self.grid_layout.itemAt(i).widget().setParent(None)
        wells_by_plate = [d for d in self.image_data if d["plate"] == self.current_plate]
        well_latest = {}
        for d in wells_by_plate:
            if d["well"] not in well_latest or d["timepoint"] < well_latest[d["well"]]["timepoint"]:
                well_latest[d["well"]] = d
        for i, row in enumerate("ABCDEFGH"):
            for j in range(1, 13):
                well = f"{row}{j}"
                container_widget = QWidget()
                layout = QVBoxLayout(container_widget)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                image_label = QLabel()
                image_label.setStyleSheet("background-color: black;")
                image_label.setFixedSize(60, 60)
                image_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(image_label)
                if well in well_latest:
                    img_path = well_latest[well]["path"]
                    img_array = cache_grayscale_image_as_numpy(img_path)
                    if img_array is not None:
                        pixmap = numpy_to_qpixmap(img_array)
                        if pixmap:
                            image_label.setPixmap(pixmap)
                image_button = QPushButton()
                image_button.setStyleSheet("background: transparent;")
                image_button.setFixedSize(60, 60)
                image_button.clicked.connect(lambda _, w=well: self.open_detail_view(w))
                image_button.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                image_button.raise_()
                layout.addWidget(image_button)
                well_label = QLabel(well)
                well_label.setStyleSheet(
                    "color: white; background-color: rgba(0, 0, 0, 128); font-weight: bold; padding: 2px;"
                )
                well_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(well_label)
                self.grid_layout.addWidget(container_widget, i, j)

    def toggle_checkmark(self, label, state):
        key = (self.current_plate, self.current_well)
        if state:
            self.checked_wells[key] = label
        else:
            if key in self.checked_wells and self.checked_wells[key] == label:
                del self.checked_wells[key]
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
            elif event.key() == Qt.Key_W:
                self.gfp_toggle.setChecked(not self.gfp_toggle.isChecked())
            if event.key() == Qt.Key_1:
                self.singlet_checkbox.setChecked(not self.singlet_checkbox.isChecked())
            elif event.key() == Qt.Key_2:
                self.doublet_checkbox.setChecked(not self.doublet_checkbox.isChecked())
            elif event.key() == Qt.Key_3:
                self.inconclusive_checkbox.setChecked(not self.inconclusive_checkbox.isChecked())
            elif event.key() == Qt.Key_F:
                self.handle_next()
            elif event.key() == Qt.Key_S:
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
        plate_images = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == well]
        self.current_timepoint = sorted(set(d["timepoint"] for d in plate_images))[0]
        self.display_detail_image()
        grayscale_image = next((d for d in plate_images if not d["is_gfp"] and d["timepoint"] == self.current_timepoint), None)
        filename = grayscale_image["filename"] if grayscale_image else "No grayscale image available"
        self.detail_label.setText(f"{well} - {filename}")
        for i in reversed(range(self.detail_timepoint_buttons.count())):
            self.detail_timepoint_buttons.itemAt(i).widget().setParent(None)
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
        self.right_panel_widget.show()

    def highlight_active_timepoint(self):
        for tp, btn in self.timepoint_btns.items():
            btn.setChecked(tp == self.current_timepoint)

    def update_timepoint(self, tp, is_gfp=False):
        self.zoom_state = self.graphics_view.get_transform()
        self.current_timepoint = tp
        self.display_detail_image(is_gfp=is_gfp)
        self.highlight_active_timepoint()

    def display_detail_image(self, is_gfp=False):
        current_zoom_state = self.graphics_view.get_transform()
        self.scene.clear()
        matches = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == self.current_well and d["timepoint"] == self.current_timepoint]
        if not matches:
            print(f"No images found for plate {self.current_plate}, well {self.current_well}, timepoint {self.current_timepoint}")
            return
        grayscale_image = next((d for d in matches if not d["is_gfp"]), None)
        gfp_image = next((d for d in matches if d["is_gfp"]), None)
        if grayscale_image:
            np_array = cache_grayscale_image_as_numpy(grayscale_image["path"])
            if isinstance(np_array, np.ndarray):
                pixmap = numpy_to_qpixmap(np_array)
                if pixmap:
                    item = QGraphicsPixmapItem(pixmap)
                    self.scene.addItem(item)
        if self.gfp_toggle.isChecked() and gfp_image:
            np_array = cache_gfp_overlay_as_numpy(gfp_image["path"])
            if isinstance(np_array, np.ndarray):
                pixmap = numpy_to_qpixmap(np_array)
                if pixmap:
                    item = QGraphicsPixmapItem(pixmap)
                    self.scene.addItem(item)
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
        self.display_detail_image()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = PlateViewer()
    viewer.resize(1000, 800)
    sys.exit(app.exec_())