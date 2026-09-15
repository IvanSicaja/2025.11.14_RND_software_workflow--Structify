📌 **Project Title:** **Structify — Folder Structure Manager, Comparator & Replicator**  
📅 **Project Timeline:** **November 2025 – Present [Active Development & Maintenance]**  
🎥 YouTube Demo: TBD  
📦 GitHub Source Code: <https://github.com/Smart-Code-ACADEMY/2025.11.24_RND_software_workflow--Scenify>  

---

📍 My Personal Profiles ⬇︎  
🎥 Video Portfolio: To be added  
📦 GitHub Profile: <https://github.com/IvanSicaja>  
👔 LinkedIn: <https://www.linkedin.com/in/ivan-si%C4%8Daja-832682222>  
🎥 YouTube: <https://www.youtube.com/@ivan_sicaja>  

---

### 💡 Core Challenge This Project Resolves:

Designing and engineering a desktop workflow for scanning, visualizing, comparing, editing, replicating, exporting, and safely renaming directory structures while preserving hierarchical relationships and reducing repetitive filesystem-management work.

---

### 🔧 Core Skills Tree Used To Build The Project - Skills and Tech Stack:
*(Project-Specific Structured Overview)*
```text
│
├── Software Engineering
│ ├── Software / Frameworks / Libraries
│ │ ├── Python
│ │ ├── PyQt6
│ │ ├── JSON
│ │ ├── Python os
│ │ ├── Python subprocess
│ │ ├── Python uuid
│ │ └── Git / GitHub
│ │
│ └── Skills
│   ├── Desktop GUI application development
│   ├── Object-oriented software design
│   ├── Event-driven application architecture
│   ├── Custom editor component development
│   ├── Filesystem traversal & hierarchy processing
│   ├── Persistent application configuration
│   ├── Cross-platform folder opening
│   ├── Error handling & user feedback
│   └── Workflow-oriented desktop automation
│
├── System Integration Engineering
│ ├── Software / Frameworks / Libraries
│ │ ├── PyQt6
│ │ ├── Python os
│ │ ├── JSON
│ │ └── Native operating-system file operations
│ │
│ └── Skills
│   ├── GUI-to-filesystem integration
│   ├── Directory scanning integration
│   ├── Structure-to-filesystem replication
│   ├── File & folder rename integration
│   ├── TXT structure import / export
│   ├── Application-state persistence
│   ├── Cross-platform system integration
│   └── End-to-end directory workflow integration
│
├── File-System Automation & Validation
│ ├── Software / Frameworks / Libraries
│ │ ├── Python os.walk
│ │ ├── Python os.rename
│ │ ├── Python os.makedirs
│ │ ├── Python uuid
│ │ └── PyQt6 validation dialogs
│ │
│ └── Skills
│   ├── Recursive directory traversal
│   ├── Folder & file structure extraction
│   ├── Hierarchical structure reconstruction
│   ├── Structure replication
│   ├── Line-by-line structure validation
│   ├── Safe two-phase batch renaming
│   ├── Rename rollback handling
│   ├── Path existence validation
│   └── Filesystem error recovery
│
└── Research & Development Engineering
  ├── Software / Frameworks / Libraries
  │ └── Integrated within sections above
  │
  └── Skills
    ├── Directory workflow architecture
    ├── Hierarchical data representation
    ├── Structure comparison strategy development
    ├── Safe filesystem-operation design
    ├── Workflow automation prototyping
    ├── User workflow optimization
    └── Technical debugging & reliability improvement
```

---

### 📋 Core System Capabilities - List Only:

- **Directory structure scanning**
- **Recursive and root-level scanning**
- **Folder-only and file-only filtering**
- **Dual structure previews**
- **Editable structure previews**
- **Line-numbered structure editor**
- **Synchronized preview scrolling**
- **Structure comparison**
- **Line-by-line name comparison**
- **Color-coded difference visualization**
- **Directory structure replication**
- **TXT structure export**
- **TXT structure import**
- **Persistent source-path settings**
- **Batch file and folder renaming**
- **Two-phase safe rename workflow**
- **Automatic rename rollback on failure**
- **Absolute-path tracking**
- **Hierarchical path reconstruction**
- **Cross-platform folder opening**...

---

### 🧠️ How It Works - Core System Capabilities Workflow:

The project combines different software-engineering areas (**desktop GUI development, filesystem traversal, directory hierarchy processing, structure comparison, directory replication, batch renaming, validation, persistent configuration, error recovery...**)  
The core of the application is **Python**, **PyQt6**, and native **filesystem operations**.

The application is also equipped with:

- **Dual directory structure scanners**
- **Editable structure previews**
- **Structure comparison workflows**
- **Directory replication**
- **TXT import / export**
- **Safe batch renaming**
- **Persistent configuration**...

**Directory structure scanning:**  
Structify scans a selected source directory either at the **root level only** or recursively through all subfolders. Users can independently choose whether the resulting structure contains **folder names, file names, or both**. The hierarchy is converted into an indentation-based text representation while absolute filesystem paths are retained internally where required.

**Dual structure workflow:**  
Two independent source panels allow separate directory structures to be scanned, imported, viewed, and edited side by side. Each panel uses a custom line-numbered editor with normalized formatting, fixed line height, consistent font settings, and automatic removal of blank lines.

**Structure comparison:**  
The two directory structures can be compared through a dedicated comparison workflow. Structify evaluates entries by hierarchy level and identifies elements that exist on both sides or only within one structure.

**Line-by-line validation:**  
An additional comparison mode evaluates corresponding lines directly. Matching names, different names, and lines existing on only one side are visually distinguished through different background colors, providing immediate feedback before filesystem changes are applied.

**Synchronized navigation:**  
Optional synchronized scrolling connects both structure previews. Scrolling one side proportionally updates the second preview, simplifying inspection of large directory structures.

**Directory structure replication:**  
Either preview can be used as a template for creating a new directory hierarchy in a selected destination folder. Structify interprets indentation levels as hierarchical relationships and creates the corresponding folders using native filesystem operations.

**TXT import and export:**  
Directory structures can be exported into dated `.txt` files and later imported into either preview. When an export filename already exists, the application supports **overwrite, numbered-copy creation, or cancellation**.

**Batch renaming:**  
The left preview represents current filesystem names while the right preview can represent the desired names. Structify compares corresponding lines and prepares rename operations only where names differ. Both previews must contain the same number of non-empty lines before the rename workflow can proceed.

**Safe rename execution:**  
Batch renaming uses a **two-phase operation**. Existing files and folders are first renamed to unique temporary names and are then assigned their final target names. If the second phase fails, Structify attempts to restore the original filesystem name automatically.

**Path resolution:**  
Absolute paths captured during scanning are used whenever available, allowing items to be addressed reliably even when identical folder names exist at different locations within a hierarchy. If the preview has been manually modified, Structify can reconstruct paths from indentation as a fallback.

**Persistent application state:**  
Structify stores the last selected source paths, recursive-scan preferences, folder / file filters, and editor font configuration inside a local JSON configuration file and reloads valid settings during subsequent application sessions.

---

### ⚠️ Note:

Batch renaming directly modifies file and folder names on the filesystem. Structify therefore validates both previews, displays all planned rename operations before execution, uses temporary intermediate names to reduce naming conflicts, and attempts an automatic rollback if a final rename operation fails.

---

### 📸 Project Snapshots:

<p align="center">
TBD
</p>

<p align="center">
TBD
</p>

<p align="center">
TBD
</p>

<p align="center">
TBD
</p>

<p align="center">
TBD
</p>

<p align="center">
TBD
</p>

<p align="center">
TBD
</p>

---

### 🎥 Video Demonstration:

<p align="center">
TBD
</p>

---

### 📣 Hashtags Section:

**#Structify #DirectoryStructure #FolderStructure #Python #PyQt6 #DesktopApplication #FileSystemAutomation #DirectoryManagement #SystemIntegration #SoftwareEngineering #WorkflowAutomation #StructureComparison #DirectoryReplication #BatchRenaming #FileManagement #Validation #ErrorRecovery #ConfigurationManagement #ResearchAndDevelopment**

<!-- Technical source: -->
<!-- README rebuild rules and required project input: -->