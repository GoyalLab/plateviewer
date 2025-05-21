# PyQt-based 96-Well Plate Viewer

import sys
import os
import re
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QGridLayout, QPushButton, QVBoxLayout, QComboBox, QFileDialog, QScrollArea, QHBoxLayout, QStackedLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QCheckBox, QButtonGroup)
from PyQt5.QtGui import QPixmap, QImage, QWheelEvent, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QEvent
from PIL import Image

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

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.plate_selector = QComboBox()
        self.plate_selector.currentIndexChanged.connect(self.update_plate)
        self.layout.addWidget(self.plate_selector)

        self.stacked_layout = QStackedLayout()
        self.layout.addLayout(self.stacked_layout)

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

        self.detail_widget = QWidget()
        self.detail_layout = QVBoxLayout()
        self.detail_widget.setLayout(self.detail_layout)

        self.detail_label = QLabel("")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_layout.addWidget(self.detail_label)

        self.checkboxes_layout = QHBoxLayout()
        self.detail_layout.addLayout(self.checkboxes_layout)

        self.singlet_checkbox = QCheckBox("Singlet [1]")
        self.doublet_checkbox = QCheckBox("Doublet [2]")
        self.inconclusive_checkbox = QCheckBox("Inconclusive [3]")

        self.singlet_checkbox.setStyleSheet("color: green")
        self.doublet_checkbox.setStyleSheet("color: red")
        self.inconclusive_checkbox.setStyleSheet("color: orange")

        self.checkbox_group = QButtonGroup()
        self.checkbox_group.setExclusive(True)
        for cb in [self.singlet_checkbox, self.doublet_checkbox, self.inconclusive_checkbox]:
            self.checkbox_group.addButton(cb)
            self.checkboxes_layout.addWidget(cb, alignment=Qt.AlignRight)

        self.singlet_checkbox.toggled.connect(lambda state: self.toggle_checkmark("singlet", state))
        self.doublet_checkbox.toggled.connect(lambda state: self.toggle_checkmark("doublet", state))
        self.inconclusive_checkbox.toggled.connect(lambda state: self.toggle_checkmark("inconclusive", state))

        self.detail_timepoint_buttons = QHBoxLayout()
        self.detail_layout.addLayout(self.detail_timepoint_buttons)

        self.gfp_timepoint_buttons = QHBoxLayout()
        self.detail_layout.addLayout(self.gfp_timepoint_buttons)

        self.graphics_view = ZoomableGraphicsView()
        self.scene = QGraphicsScene()
        self.graphics_view.setScene(self.scene)
        self.detail_layout.addWidget(self.graphics_view)

        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("\u2190 Previous")
        self.next_btn = QPushButton("Next \u2192")
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

        self.installEventFilter(self)
        self.load_images()

    def toggle_checkmark(self, label, state):
        key = (self.current_plate, self.current_well)
        if state:
            self.checked_wells[key] = label
        elif key in self.checked_wells and self.checked_wells[key] == label:
            del self.checked_wells[key]

        print(f"Updated checked_wells: {self.checked_wells}")  # Debugging

        # Refresh the UI to reflect the changes
        self.refresh_checkboxes()
        self.update_grid()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and self.stacked_layout.currentWidget() == self.detail_widget:
            if event.key() == Qt.Key_1:
                self.singlet_checkbox.setChecked(True)
                self.toggle_checkmark("singlet", True)
            elif event.key() == Qt.Key_2:
                self.doublet_checkbox.setChecked(True)
                self.toggle_checkmark("doublet", True)
            elif event.key() == Qt.Key_3:
                self.inconclusive_checkbox.setChecked(True)
                self.toggle_checkmark("inconclusive", True)
            return True
        return super().eventFilter(obj, event)

    def refresh_checkboxes(self):
        key = (self.current_plate, self.current_well)
        current_label = self.checked_wells.get(key, None)  # Default to None if the well hasn't been touched
        print(f"Refreshing checkboxes for {key}: {current_label}")  # Debugging

        # Block signals to avoid triggering toggle_checkmark during UI updates
        self.singlet_checkbox.blockSignals(True)
        self.doublet_checkbox.blockSignals(True)
        self.inconclusive_checkbox.blockSignals(True)

        # Reset all checkboxes
        self.singlet_checkbox.setChecked(False)
        self.doublet_checkbox.setChecked(False)
        self.inconclusive_checkbox.setChecked(False)

        # Check the appropriate checkbox if a label exists
        if current_label == "singlet":
            self.singlet_checkbox.setChecked(True)
        elif current_label == "doublet":
            self.doublet_checkbox.setChecked(True)
        elif current_label == "inconclusive":
            self.inconclusive_checkbox.setChecked(True)

        # Unblock signals after UI updates
        self.singlet_checkbox.blockSignals(False)
        self.doublet_checkbox.blockSignals(False)
        self.inconclusive_checkbox.blockSignals(False)

    def load_images(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if not folder:
            return

        pattern = re.compile(r"(?i)(?P<plate>plate\w+)[_\- ]?(?P<well>[A-H](?:1[0-2]|[1-9]))[^\n]*?(?P<timepoint>\d{2}d\d{2}h\d{2}m)")

        files = sorted(os.listdir(folder))
        seen = set()
        for fname in files:
            if not fname.lower().endswith(".tif"):
                continue
            match = pattern.search(fname)
            if not match:
                continue
            meta = match.groupdict()
            plate = meta["plate"].upper().rstrip("_-")
            key = (plate, meta["well"], meta["timepoint"])
            if key in seen:
                continue
            seen.add(key)

            is_gfp = "GFP" in fname.upper()
            self.image_data.append({
                "plate": plate,
                "well": meta["well"],
                "timepoint": meta["timepoint"],
                "path": os.path.join(folder, fname),
                "filename": fname,
                "is_gfp": is_gfp
            })

        self.plates = sorted(set(d["plate"] for d in self.image_data))
        self.plate_selector.addItems(self.plates)
        self.update_plate()

    def open_detail_view(self, well):
        self.zoom_state = None
        self.current_well = well
        self.scene.clear()

        plate_images = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == well]
        self.current_timepoint = sorted(set(d["timepoint"] for d in plate_images))[0]
        self.display_detail_image()

        # Clear existing timepoint buttons
        for i in reversed(range(self.detail_timepoint_buttons.count())):
            self.detail_timepoint_buttons.itemAt(i).widget().setParent(None)
        for i in reversed(range(self.gfp_timepoint_buttons.count())):
            self.gfp_timepoint_buttons.itemAt(i).widget().setParent(None)

        # Create timepoint buttons
        self.timepoint_btns = {}
        self.gfp_timepoint_btns = {}
        for d in sorted(plate_images, key=lambda x: x["timepoint"]):
            btn = QPushButton(d["timepoint"])
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, tp=d["timepoint"]: self.update_timepoint(tp))
            self.detail_timepoint_buttons.addWidget(btn)
            self.timepoint_btns[d["timepoint"]] = btn

            if d["is_gfp"]:
                gfp_btn = QPushButton(d["timepoint"])
                gfp_btn.setCheckable(True)
                gfp_btn.setStyleSheet("color: green")
                gfp_btn.clicked.connect(lambda _, tp=d["timepoint"]: self.update_timepoint(tp, is_gfp=True))
                self.gfp_timepoint_buttons.addWidget(gfp_btn)
                self.gfp_timepoint_btns[d["timepoint"]] = gfp_btn

        self.highlight_active_timepoint()
        self.stacked_layout.setCurrentWidget(self.detail_widget)

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

        color_map = {
            "doublet": QColor("red"),
            "singlet": QColor("green"),
            "inconclusive": QColor("yellow")
        }

        for i, row in enumerate("ABCDEFGH"):
            for j in range(1, 13):
                well = f"{row}{j}"
                container = QVBoxLayout()
                title = QLabel(well)
                title.setStyleSheet("color: white")
                title.setAlignment(Qt.AlignCenter)
                container_widget = QWidget()
                container_widget.setLayout(container)
                container.addWidget(title)

                label = QLabel()
                label.setAlignment(Qt.AlignCenter)
                if well in well_latest:
                    try:
                        path = well_latest[well]["path"]
                        if path in self.thumbnail_cache:
                            pixmap = self.thumbnail_cache[path].copy()
                        else:
                            img = Image.open(path).convert("L").resize((80, 80))
                            data = img.tobytes("raw", "L")
                            qimg = QImage(data, img.width, img.height, QImage.Format_Grayscale8)
                            pixmap = QPixmap.fromImage(qimg)
                            self.thumbnail_cache[path] = pixmap

                        label_type = self.checked_wells.get((self.current_plate, well))
                        if label_type in color_map:
                            painter = QPainter(pixmap)
                            pen = QPen(color_map[label_type], 4)
                            painter.setPen(pen)
                            painter.drawRect(0, 0, pixmap.width()-1, pixmap.height()-1)
                            painter.end()

                        label.setPixmap(pixmap)
                        label.mousePressEvent = lambda e, w=well: self.open_detail_view(w)
                    except:
                        label.setText("Err")
                container.addWidget(label)
                self.grid_layout.addWidget(container_widget, i, j)

    def open_detail_view(self, well):
        self.zoom_state = None
        self.current_well = well
        self.scene.clear()

        plate_images = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == well]
        self.current_timepoint = sorted(set(d["timepoint"] for d in plate_images))[0]
        self.display_detail_image()

        current_label = self.checked_wells.get((self.current_plate, self.current_well))
        self.doublet_checkbox.setChecked(current_label == "doublet")
        self.singlet_checkbox.setChecked(current_label == "singlet")
        self.inconclusive_checkbox.setChecked(current_label == "inconclusive")

        # Clear existing timepoint buttons
        for i in reversed(range(self.detail_timepoint_buttons.count())):
            self.detail_timepoint_buttons.itemAt(i).widget().setParent(None)
        for i in reversed(range(self.gfp_timepoint_buttons.count())):
            self.gfp_timepoint_buttons.itemAt(i).widget().setParent(None)

        # Create timepoint buttons
        self.timepoint_btns = {}
        self.gfp_timepoint_btns = {}
        for d in sorted(plate_images, key=lambda x: x["timepoint"]):
            btn = QPushButton(d["timepoint"])
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, tp=d["timepoint"]: self.update_timepoint(tp))
            self.detail_timepoint_buttons.addWidget(btn)
            self.timepoint_btns[d["timepoint"]] = btn

            if d["is_gfp"]:
                gfp_btn = QPushButton(d["timepoint"])
                gfp_btn.setCheckable(True)
                gfp_btn.setStyleSheet("color: green")
                gfp_btn.clicked.connect(lambda _, tp=d["timepoint"]: self.update_timepoint(tp, is_gfp=True))
                self.gfp_timepoint_buttons.addWidget(gfp_btn)
                self.gfp_timepoint_btns[d["timepoint"]] = gfp_btn

        self.highlight_active_timepoint()
        self.stacked_layout.setCurrentWidget(self.detail_widget)

    def toggle_checkmark(self, label, state):
        if state:
            self.checked_wells[(self.current_plate, self.current_well)] = label
        elif (self.current_plate, self.current_well) in self.checked_wells:
            del self.checked_wells[(self.current_plate, self.current_well)]
        self.update_grid()

    def update_timepoint(self, tp, is_gfp=False):
        self.zoom_state = self.graphics_view.get_transform()
        self.current_timepoint = tp
        self.display_detail_image(is_gfp=is_gfp)
        self.highlight_active_timepoint()

    def highlight_active_timepoint(self):
        for tp, btn in self.timepoint_btns.items():
            btn.setChecked(tp == self.current_timepoint)

        for tp, btn in self.gfp_timepoint_btns.items():
            btn.setChecked(tp == self.current_timepoint)

    def display_detail_image(self, is_gfp=False):
        self.scene.clear()
        matches = [d for d in self.image_data if d["plate"] == self.current_plate and d["well"] == self.current_well and d["timepoint"] == self.current_timepoint]
        if not matches:
            return

        grayscale_image = next((d for d in matches if not d["is_gfp"]), None)
        gfp_image = next((d for d in matches if d["is_gfp"]), None)

        if grayscale_image:
            img = Image.open(grayscale_image["path"]).convert("L")
            data = img.tobytes("raw", "L")
            qimg = QImage(data, img.width, img.height, QImage.Format_Grayscale8)
            pixmap = QPixmap.fromImage(qimg)
            item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(item)

        if is_gfp and gfp_image:
            img = Image.open(gfp_image["path"]).convert("L")
            data = img.tobytes("raw", "L")
            qimg = QImage(data, img.width, img.height, QImage.Format_Grayscale8)

            # Apply green color to the GFP channel
            green_overlay = QImage(qimg.size(), QImage.Format_ARGB32)
            green_overlay.fill(Qt.transparent)
            for y in range(qimg.height()):
                for x in range(qimg.width()):
                    intensity = qimg.pixel(x, y) & 0xFF
                    green_overlay.setPixel(x, y, QColor(0, intensity, 0, 128).rgba())  # Semi-transparent green

            pixmap = QPixmap.fromImage(green_overlay)
            item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(item)

        if self.zoom_state:
            self.graphics_view.set_transform(self.zoom_state)
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

    def eventFilter(self, source, event):
        if event.type() == QEvent.KeyPress and self.stacked_layout.currentWidget() == self.detail_widget:
            if event.key() == Qt.Key_A:
                self.zoom_state = self.graphics_view.get_transform()
                self.prev_timepoint()
            elif event.key() == Qt.Key_D:
                self.zoom_state = self.graphics_view.get_transform()
                self.next_timepoint()
            elif event.key() == Qt.Key_W:  # Toggle GFP on
                if self.current_timepoint in self.gfp_timepoint_btns:
                    self.update_timepoint(self.current_timepoint, is_gfp=True)
            elif event.key() == Qt.Key_S:  # Toggle GFP off
                self.update_timepoint(self.current_timepoint, is_gfp=False)
        return super().eventFilter(source, event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = PlateViewer()
    viewer.resize(1000, 800)
    viewer.show()
    sys.exit(app.exec_())
