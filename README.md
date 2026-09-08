# Disk Cleaner

Disk Cleaner is a Streamlit application for exploring disk usage and finding directories that contain large amounts of photos and videos. It provides interactive treemaps, filters, CSV/JSON exports, and an automatically generated JSON report.

The application is implemented in [disk_analyzer.py](disk_analyzer.py) and supports Windows, macOS, and Linux.

## Features

- Analyze one directory or scan all detected drives.
- Display directory sizes as an interactive Plotly treemap.
- Configure scan depth from 1 to 10 levels.
- Ignore directories below a configurable size threshold.
- Find directories with a configurable percentage of photo/video content.
- Detect common image and video formats recursively.
- Skip symbolic links and continue past inaccessible files or directories.
- Open a selected directory in the system file explorer.
- Export disk usage and media results as CSV.
- Download or save a complete JSON report.

## Requirements

- Python 3.10 or newer
- A supported operating system: Windows, macOS, or Linux
- The packages listed in [requirements.txt](requirements.txt)

## Installation

### Windows PowerShell

```powershell
git clone <repository-url>
cd win-space-analyser
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run this once for the current user or activate the environment from Command Prompt instead:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### macOS or Linux

```bash
git clone <repository-url>
cd win-space-analyser
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run the application

Start Streamlit from the project directory:

```bash
streamlit run disk_analyzer.py
```

Then open the URL shown in the terminal, normally [http://localhost:8501](http://localhost:8501).

Run the application with `streamlit run`; do not use `python disk_analyzer.py` as the primary launch command.

## Usage

1. Choose **Single folder** or **Auto (all drives)** in the sidebar.
2. For a single-folder scan, enter an existing directory path.
3. In Auto mode, select the drives to scan.
4. Set **Max Depth**, **Minimum Size**, and media thresholds.
5. Click **Analyze folder** or **Scan selected drives**.
6. Explore the **Disk Usage**, **Photos and Videos**, and **Report** tabs.
7. Use the download buttons to export CSV or JSON data.

### Scan modes

**Single folder** analyzes disk usage for one directory. **Auto** scans all selected drives for both disk usage and media content. Large drives can take a long time to scan, especially with a high maximum depth.

### Media analysis

Media analysis recognizes common image formats such as JPG, PNG, GIF, TIFF, HEIC, RAW, SVG, and AVIF, plus video formats such as MP4, MKV, AVI, MOV, WMV, WebM, MPEG, and VOB. The media tab can filter results by media percentage and total media size and can hide matching parent directories.

## Configuration

| Setting | Default | Description |
| --- | ---: | --- |
| Root directory | `C:\Users\muchs` on Windows | Directory used by Single folder mode. |
| Max Depth | `5` | Maximum directory depth to inspect. |
| Minimum Size (MB) | `1.0` | Smaller directories are omitted from the treemap. |
| Minimum photo/video share | `30%` | Minimum percentage of recursive directory size made up of media. |
| Minimum media size (MB) | `0` | Minimum total media size for media results. |

## Reports and exports

After a scan, the application keeps the latest results in Streamlit session state and automatically writes a report to the current working directory. Report files use this pattern:

```text
disk_report_YYYYMMDD_HHMMSS.json
```

The JSON report contains:

- scan mode and root paths;
- scan configuration;
- summary totals;
- treemap directory data;
- media directory data.

CSV exports are available from the Disk Usage and Photos and Videos tabs.

## Project structure

```text
win-space-analyser/
├── disk_analyzer.py     # Streamlit application and scanning logic
├── requirements.txt     # Python dependencies
├── README.md            # Project documentation
└── LICENSE              # License file
```

## Technical notes

- File sizes are logical sizes from `st_size`, not allocated disk space.
- Symbolic links are skipped to avoid recursion loops and duplicate traversal.
- Permission and filesystem errors are handled per entry where possible.
- Directory sizes are calculated with `os.scandir` and cached for leaf scans.
- The application currently has no automated test suite or packaging configuration.

## Development

To check Python syntax without starting the UI:

```bash
python -m py_compile disk_analyzer.py
```

Contributions should keep user-facing text in English and preserve the existing Streamlit workflow.

## License

See [LICENSE](LICENSE).
