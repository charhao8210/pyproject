# Code Visual Debugger

[English](README.md) | 繁體中文

Code Visual Debugger 是一套在本機執行的 Python／C++17 程式視覺化除錯工具，目標是把「在紙上模擬程式」的過程自動化，適合用小測資教學與練習。

貼上程式和測試資料，選擇這個程式在做什麼（例如 BFS），執行一次後就能一步一步看每一行做了什麼：變數怎麼變、陣列／迷宮／圖／Stack／Queue／Linked List 長什麼樣子。

## 主要功能

### 執行前：選擇演算法

- 右邊的卡片告訴 Debugger 這個程式在做什麼：Array simulation、Sorting、Stack、Queue、Linked List、BFS、DFS、Shortest path、Recursion，或 Other（讓程式自己猜，可能畫得不好）。
- 每張卡片用簡單的問題問要畫哪些變數（例如 BFS 問圖、queue、visited、距離），並依程式碼預先填好；選錯可以自己換，用不到的選「不用」。
- 選了卡片才能 Run；按 Edit code 會回到選擇畫面。

### 視覺化

- **長條圖**：陣列與排序；負數畫在零線下方，`INF` 畫成虛線 `∞`。
- **一格一格**：字串、字元陣列、長度不一的二維陣列。
- **格子**：迷宮、字元地圖與二維表格，標出目前格、visited、frontier、牆壁與距離；一般表格附列／欄索引。
- **圖**：節點可拖曳，樹由上往下排，邊上標權重，正在檢查的邊會亮起；有向／無向可手動切換。BFS／DFS 的 queue／stack 畫在圖或格子上方。
- **Stack**（直立，top 在上）、**Queue**（左邊出、右邊進）、**Linked List**（`值 | •` 方塊加箭頭，`head ↓ ∅` 代表 None／nullptr）。
- **遞迴樹**。
- View 選單可以換畫法或換要畫的變數，不用重新執行（標 `(runs again)` 的會重跑一次）。
- Reading／Changed／New 標記代表這一行讀到、值改變、新加入的格子。滑鼠停在圖例或標記上會顯示說明，`/help` 頁面有完整使用說明與名詞表。

### 逐步檢視

- 黃色那一行是「接下來要執行的這一行」；圖、變數和 stdout 都是這一行執行完之後的樣子（停在 `vis[v] = true` 時，v 已經打勾）。
- `變數 ▾` 勾選要看的變數，畫在圖的右邊：所有單一值合成一張卡片，每個陣列或容器各一張，只寫數值。
- 只讀一次的輸入值（例如 `n`、`m`）固定顯示在圖的上方。
- 時間軸：滑桿、`←`／`→` 上一步／下一步、`Space` 自動播放（0.25×–2×）、`|‹`／`›|` 跳到目前迴圈的前後。
- RE 停在出錯的那一行；TLE 或超過步數上限時，停止前的步驟都保留。編譯或語法錯誤會在程式碼裡標紅。

### 編輯器

- 語法上色、行號；貼上另一種語言的程式時會自動切換語言（可按「改回」）。
- 兩種語言的程式碼和測試資料都存在瀏覽器裡，重新開啟頁面還在。
- 亮色／暗色主題；每個區塊都能收起，拖曳分隔線可調整大小。

## 系統需求

基本的 Python 模式需要：

- Python 3.11 以上版本
- Git（若要從 GitHub 下載專案）
- 可安裝 Python 套件的網路連線

C++ 模式另外需要：

- `g++`
- `gdb`
- 兩個命令都必須能從啟動伺服器的終端機直接執行

> [!NOTE]
> 如果只使用 Python 模式，不需要安裝 `g++` 或 `gdb`。

## 安裝教學

### 第一步：先檢查目前環境

Windows 請開啟 PowerShell；macOS 或 Linux 請開啟終端機。依序輸入：

```text
git --version
python --version
g++ --version
gdb --version
```

macOS 或 Linux 如果找不到 `python`，再試一次：

```text
python3 --version
```

檢查結果的判斷方式：

| 指令 | 什麼時候需要 | 正常結果 |
| --- | --- | --- |
| `git --version` | 使用 Git clone 下載時 | 顯示 Git 版本；若要下載 ZIP，可以沒有 Git |
| `python --version` | 一定需要 | 必須是 Python 3.11 以上 |
| `g++ --version` | 只有 C++ 模式需要 | 顯示 GNU g++ 版本 |
| `gdb --version` | 只有 C++ 模式需要 | 顯示 GNU gdb 版本 |

> [!IMPORTANT]
> 只使用 Python 模式時，只要確認 Python 3.11 以上即可。`g++` 或 `gdb` 顯示「找不到指令」不會影響 Python 模式。

### Windows：最簡單的安裝方式

#### 1. 下載專案

以下兩種方式選一種即可。

**方法 A：使用 Git clone**

適合已經可以執行 `git --version` 的使用者。在 PowerShell 輸入：

```powershell
git clone -b mvp https://github.com/charhao8210/pyproject.git
cd pyproject
```

**方法 B：下載 ZIP**

1. 開啟 [GitHub 專案頁面的 mvp 分支](https://github.com/charhao8210/pyproject/tree/mvp)（目前版本在 `mvp` 分支）。
2. 按綠色 **Code** 按鈕。
3. 選擇 **Download ZIP**。
4. 將 ZIP 解壓縮。
5. 進入解壓縮後的資料夾，確認裡面看得到 `README.md` 與 `requirements.txt`。
6. 在檔案總管上方的路徑欄輸入 `powershell`，按 Enter。新的 PowerShell 會直接位於該資料夾。

#### 2. 再確認 Python

```powershell
python --version
```

如果顯示 Python 3.11、3.12、3.13 或更新版本，就可以繼續。如果找不到 `python` 或版本低於 3.11，請先依照 [Python 官方 Windows 安裝說明](https://docs.python.org/3/using/windows.html) 安裝新版 Python，完成後關閉並重新開啟 PowerShell。

#### 3. 建立虛擬環境

```powershell
python -m venv .venv
```

虛擬環境會把本專案的套件與電腦上其他 Python 專案分開。

#### 4. 安裝套件

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

#### 5. 啟動程式

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

看到 Uvicorn 啟動訊息後，使用瀏覽器開啟：

<http://127.0.0.1:8000>

結束伺服器時，在 PowerShell 按 `Ctrl+C`。

上面的做法不需要啟用虛擬環境，因此不會遇到 PowerShell 阻擋 `Activate.ps1` 的問題。下次要使用時，只需要進入專案資料夾，再執行第 5 步的啟動指令。

### Windows：啟用 C++ 模式

以下步驟只在你需要執行 C++ 程式時才需要。

先在 PowerShell 檢查：

```powershell
g++ --version
gdb --version
```

如果兩個指令都能顯示版本，代表電腦已經有可用的工具鏈，請先直接啟動專案測試，**不需要另外安裝 MSYS2**。

如果其中一個指令找不到，Windows 建議使用 MSYS2 安裝 GNU 工具鏈。

#### 為什麼需要 MSYS2？

Windows 本身沒有內建 GNU `g++` 與 `gdb`。本專案的 C++ 模式會：

1. 使用 `g++` 將貼上的 C++17 程式編譯成暫存執行檔。
2. 使用 `gdb` 逐行執行程式並讀取變數。
3. 將 GDB 結果轉換成網頁上的視覺化步驟。

MSYS2 只是取得這兩個工具的簡單方法，不是專案執行時的特殊伺服器，也不是 Python 模式的必要套件。其他 GNU／MinGW 工具鏈只要能讓 `g++` 與 `gdb` 從 PATH 直接執行，也可以使用。

#### 1. 安裝 MSYS2

從 [MSYS2 官方網站](https://www.msys2.org/) 下載並安裝，建議保留預設安裝位置 `C:\msys64`。

#### 2. 更新 MSYS2

從開始功能表開啟 **MSYS2 UCRT64**，執行：

```bash
pacman -Syu
```

如果更新程序要求關閉終端機，重新開啟 **MSYS2 UCRT64**，再執行一次相同命令。

#### 3. 安裝 GCC 與 GDB

在 **MSYS2 UCRT64** 終端機執行：

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-gdb
```

#### 4. 將工具鏈加入 PATH

把以下資料夾加入 Windows 使用者的 `Path` 環境變數：

```text
C:\msys64\ucrt64\bin
```

加入後請關閉並重新開啟 PowerShell，再檢查：

```powershell
g++ --version
gdb --version
```

兩個命令都能顯示版本後，重新啟動本專案的 Uvicorn 伺服器即可使用 C++ 模式。

若只想在目前的 PowerShell 視窗暫時加入 PATH，可以執行：

```powershell
$env:Path = "C:\msys64\ucrt64\bin;$env:Path"
```

### Ubuntu／Debian Linux

Python 模式先安裝基本工具：

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git
```

如果還要使用 C++ 模式，再安裝：

```bash
sudo apt install g++ gdb
```

接著下載、安裝並啟動專案：

```bash
git clone -b mvp https://github.com/charhao8210/pyproject.git
cd pyproject
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload
```

最後開啟 <http://127.0.0.1:8000>。

### macOS

Python 模式的安裝方式：

```bash
git clone -b mvp https://github.com/charhao8210/pyproject.git
cd pyproject
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload
```

macOS 內建的 `g++` 通常實際上是 Clang，使用的是 libc++；本專案目前的 C++ 變數解析依賴 GNU GDB 與 libstdc++ 內部結構，因此 macOS 的 C++ 模式不屬於直接支援的安裝方式。建議在 macOS 使用 Python 模式，或改在具備 GNU `g++`／`gdb` 的 Linux 環境執行 C++ 模式。

## 使用方式

1. 右上角 Language 選 `Python` 或 `C++`。
2. 把程式貼進 Source code。
3. 程式會讀輸入的話，把資料貼進 Test data（stdin）。
4. 在右邊「這個程式在做什麼？」選一張卡片，確認下方要畫的變數。
5. 按 `Run as …`（Python 約 1–3 秒，C++ 約 1–30 秒）。
6. 用 `→`／`←` 或時間軸逐步查看；要改程式或換演算法就按 Edit code。

## 執行測試

已啟用虛擬環境時：

```bash
python -m pytest -q
```

Windows 未啟用虛擬環境時：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

如果系統找不到 `g++` 或 `gdb`，需要 C++ 工具鏈的測試會自動跳過；Python 與前端相關測試仍會執行。

## API

除網頁介面外，也可以直接呼叫：

- `POST /api/candidates`：只看程式碼，列出每張卡片每個欄位可以選的變數（`{"language": "cpp", "code": "..."}`）。
- `POST /api/debug`：執行程式，回傳每一步的快照。

`/api/debug` 範例請求：

```json
{
  "language": "python",
  "code": "a = [3, 1, 2]\na.sort()\nprint(a)",
  "stdin": "",
  "choice": {"algorithm": "array", "variables": {"array": "a"}}
}
```

`language` 可用 `python` 或 `cpp`。`choice` 可省略，省略時由程式自己猜要畫什麼（等同 Other）。回應包含 `status`（`completed`／`exception`／`step_limit`／`timeout`）、`algorithm`（畫法與 View 選單的清單），以及按時間排列的 `steps`：每一步的行號、區域／全域變數、呼叫堆疊、目前為止的輸出、例外，和後端算好的 `visualization`。

## 運作架構

```text
瀏覽器
  │ POST /api/candidates  選卡片時列出候選變數
  │ POST /api/debug       執行並取得每一步快照
  ▼
FastAPI ── 語言分派
  │
  ├── Python：AST 檢查 → 隔離子行程（-I -S、暫存目錄）
  │      └── sys.settrace() 記錄每一步，序列化變數並保留物件身分
  │
  ├── C++17：g++ -g -O0 編譯 → GDB 逐行追蹤
  │      ├── 分析原始碼的宣告與作用域，再用 DWARF 確認變數讀得到
  │      ├── 解析 STL 容器；沒被寫入的值沿用上一步，加快追蹤
  │      └── 無緩衝 stdout，輸出對齊印出它的那一步
  │
  ├── 分析器：依選的演算法（或自動猜測）替每一步算好視覺化資料
  │      └── 長條、格子、圖、Stack、Queue、Linked List、遞迴樹
  ▼
Vanilla JavaScript 前端：程式碼、視覺化、勾選的變數、stdout、時間軸
```

瀏覽器不解讀程式語意，只畫後端算好的 JSON。「上一步」是切換到先前保存的快照，不是讓程式反向執行。

## 常見問題

### PowerShell 顯示「無法辨識 python」

重新安裝或設定 Python，完成後關閉並重新開啟 PowerShell，再執行：

```powershell
python --version
```

### PowerShell 不允許執行 Activate.ps1

不一定要啟用虛擬環境，可以直接執行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### C++ 模式顯示找不到 g++ 或 gdb

先確認：

```powershell
g++ --version
gdb --version
```

若其中一個無法執行，請確認已安裝 MSYS2 UCRT64 對應套件、`C:\msys64\ucrt64\bin` 已加入 PATH，並重新開啟 PowerShell 與 Uvicorn。

### 網頁無法開啟

確認啟動 Uvicorn 的終端機仍在執行，並查看終端機是否顯示錯誤。預設網址是 <http://127.0.0.1:8000>；如果 8000 連接埠已被占用，可以改用：

```bash
python -m uvicorn app.main:app --reload --port 8765
```

再開啟 <http://127.0.0.1:8765>。

## 已知限制

- 給小測資用：一次最多顯示 5,000 步。Python 程式最多跑 50,000 步、3 秒（畫面會寫共跑了幾步、怎麼結束）；C++ 最多 30 秒，迴圈裡的每一行最多停 1,000 次，之後照常執行但不再停，畫面會標出是哪幾行。
- Python 只能 import `sys`（`stdin`、`exit`、`setrecursionlimit`）、`collections`（`deque`、`defaultdict`、`Counter`）、`heapq`、`bisect`、`math`；不能用 `open`、`eval`、`exec`、async、執行緒、檔案 I/O、網路或第三方函式庫。
- C++ 依賴 GCC、GDB 與 libstdc++ 內部結構，不支援 MSVC STL 或 libc++。可解析 `vector`（含 `vector<bool>`）、`string`、原生陣列、`std::array`、`pair`、`queue`／`stack`／`deque`、`priority_queue`、`set`／`multiset`／`map`／`multimap`（元素是內建型別或 pair）；`unordered_*` 只顯示「contents not decoded」，三維陣列不會讀取。
- 容器最多讀 50 項、巢狀 4 層，字串 1,000 字元，輸出 100,000 字元。
- 選 Other 時演算法是從程式碼猜的，可能畫錯；圖的有向／無向也是猜的，可在圖上方的選單改。
- Python 內建的 C 實作（例如 `list.sort()`）看不到內部比較步驟，只看得到排序前後。
- 沒有使用者中斷點、監看運算式或修改變數的功能。

## 安全性提醒

本專案是教學工具，**不是安全沙箱**。Python 程式在有時間限制的隔離子行程與暫存目錄中執行，並受 AST 檢查、受限 built-ins 與步驟上限保護；C++ 程式則是直接編譯後在 GDB 下執行。這些措施只能降低意外風險，請勿公開部署並用來執行不受信任的程式碼。

## 官方安裝參考

- [Python：在 Windows 使用 Python](https://docs.python.org/3/using/windows.html)
- [Python：建立虛擬環境](https://docs.python.org/3/library/venv.html)
- [Python Packaging：使用 pip 與虛擬環境](https://packaging.python.org/guides/installing-using-pip-and-virtual-environments/)
- [MSYS2：安裝與開始使用](https://www.msys2.org/)
- [MSYS2：UCRT64 GCC 套件](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gcc?repo=ucrt64)
- [MSYS2：UCRT64 GDB 套件](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gdb?repo=ucrt64)
