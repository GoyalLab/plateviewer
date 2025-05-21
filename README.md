# 96-Well Plate Viewer (PyQt)

This desktop application allows you to browse 96-well image datasets from high-content microscopy (e.g., Incucyte) using an intuitive plate-based interface.

---

## Features

* Plate overview with clickable wells arranged in standard 8×12 layout
* Thumbnail previews of the most recent image per well
* Full-resolution zoomable view per well with timepoint toggling
* Well annotation options: **Singlet \[1]**, **Doublet \[2]**, **Inconclusive \[3]**
* Colored ring indicators on plate view based on annotations
* Keyboard shortcuts for fast navigation

---

## File Format Requirements

Each image filename must include:

* The word `plate` (case-insensitive), followed by a plate identifier (e.g., `PLATE01`)
* A well ID in the format `A1`–`H12`
* A timepoint in the format `00d00h00m`

**Example:**

```
20250117_MEM1003_plate01_A7_1_12d23h59m.tif
```

Other filename content is allowed, but the three components above must be present.

---

## Usage Instructions

### 1. Launch the App

```bash
python plate_viewer.py
```

### 2. Select Image Folder

* When prompted, select the folder containing your `.tif` images.
* The app will take some time to load up, as it is processing many large image files.

### 3. Browse Plates

* Use the dropdown menu at the top to switch between plates.
* Click any well to open its zoomed-in view.

### 4. Navigate Timepoints

* Use the timepoint buttons above the image.
* Or press the keyboard:

  * **A** → Previous timepoint
  * **D** → Next timepoint

### 5. Navigate Between Wells

* Use the **← Previous** and **Next →** buttons below the image.

### 6. Label Wells

* Use the labeled checkboxes in well view:

  * 🟩 **Singlet** → press **1**
  * 🟥 **Doublet** → press **2**
  * 🟧 **Inconclusive** → press **3**
* The selected well gets annotated with a colored outline in plate view.

### 7. Return to Plate View

* Click **Back to Plate View** to go back.

---

## Performance Tip

The app supports multiple plates, but **initial load time increases** with dataset size.

**Recommended: Load only 1–2 plates at a time for best speed.**

---

## Dependencies

* Python 3.7+
* PyQt5
* Pillow

### Install with pip:

```bash
pip install PyQt5 Pillow
```

---

## Author

Developed by [@madelinemelzer](https://github.com/madelinemelzer)
