# Code Visual Debugger

[English](README.md) | 繁體中文

Code Visual Debugger 是一套在本機執行的 Python／C++ 程式視覺化除錯工具。你可以選擇語言、貼上程式碼、輸入測試資料，執行一次後使用上一步／下一步逐步查看程式狀態。

每個執行步驟都會顯示目前程式碼行、重要區域變數、全域變數、物件關係、函式呼叫堆疊、累積輸出，以及例外或執行錯誤。系統也會嘗試辨識陣列、矩陣、圖、遞迴、二分搜尋、排序與動態規劃等常見演算法，切換成適合的視覺化方式。

## 主要功能

- 支援 Python 與 C++17 程式。
- 使用上一步／下一步瀏覽不可變的執行快照。
- 顯示區域變數、全域變數、物件身分與函式呼叫堆疊。
- 顯示截至目前步驟的標準輸出。
- 支援 `input()`、`sys.stdin.read()` 與 C++ 標準輸入。
- 視覺化陣列、矩陣、圖、物件參照與遞迴呼叫樹。
- 發生 RE、TLE 或超過步驟限制時，仍保留停止前已收集的步驟。
- C++ 模式可解析常見純量、字串、原生陣列與多種 `std::vector` 結構。

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
git clone https://github.com/charhao8210/pyproject.git
cd pyproject
```

**方法 B：下載 ZIP**

1. 開啟 [GitHub 專案頁面](https://github.com/charhao8210/pyproject)。
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
git clone https://github.com/charhao8210/pyproject.git
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
git clone https://github.com/charhao8210/pyproject.git
cd pyproject
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload
```

macOS 內建的 `g++` 通常實際上是 Clang，使用的是 libc++；本專案目前的 C++ 變數解析依賴 GNU GDB 與 libstdc++ 內部結構，因此 macOS 的 C++ 模式不屬於直接支援的安裝方式。建議在 macOS 使用 Python 模式，或改在具備 GNU `g++`／`gdb` 的 Linux 環境執行 C++ 模式。

## 使用方式

1. 在右上角選擇 `Python` 或 `C++`。
2. 將程式貼到程式碼編輯區。
3. 如果程式會讀取輸入，在 Test data 欄位填入測試資料。
4. 按下執行按鈕。
5. 使用上一步／下一步查看每個執行快照。
6. 從變數、資料結構、Call Stack 與輸出區觀察程式如何變化。

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

```text
POST /api/debug
```

範例請求：

```json
{
  "language": "python",
  "code": "value = int(input())\nprint(value * 2)",
  "stdin": "21\n"
}
```

`language` 可使用 `python` 或 `cpp`。回應會包含原始碼、標準輸入、執行狀態、演算法判斷結果，以及按時間排列的 `steps` 快照。

## 運作架構

```text
瀏覽器
  │ POST /api/debug
  ▼
FastAPI ── 語言分派
  │
  ├── Python 隔離子行程
  │      ├── sys.settrace() 收集執行事件
  │      ├── 序列化變數與物件關係
  │      └── 產生 JSON 快照
  │
  ├── C++17 編譯與 GDB 逐行追蹤
  │      ├── 分析宣告與作用域
  │      ├── 讀取變數及 STL 結構
  │      └── 對齊標準輸出與執行步驟
  │
  ├── 演算法與資料結構辨識
  │      ├── 矩陣／網格
  │      ├── 陣列
  │      ├── 圖
  │      └── 遞迴
  │
  ▼
Vanilla JavaScript 前端
  ├── 程式碼行檢視器
  ├── 變數與資料結構
  ├── 可拖曳的 SVG 物件關係圖
  ├── 函式呼叫堆疊
  └── 標準輸出與 RE／TLE 狀態
```

瀏覽器只負責呈現後端產生的 JSON 快照，不會自行解讀 Python 執行語意。「上一步」是切換到先前保存的快照，不是讓 Python 反向執行。

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

- Python 模式只允許受限制的 `sys` 輸入介面，不支援一般 import。
- 不支援 async、執行緒、多行程、檔案 I/O、網路、GUI、NumPy、pandas 或第三方函式庫。
- 沒有使用者中斷點、監看運算式、變數修改、`pdb` 整合或控制流程圖。
- 演算法辨識採用啟發式規則；不熟悉或不明確的程式會回到一般執行畫面。
- Python 內建的 C 實作，例如 `list.sort()`，不會公開內部比較步驟，因此只能看到排序前後狀態。
- 單次追蹤最多保存 5,000 個快照；容器、巢狀深度與輸出長度也有上限。
- C++ 模式依賴 GCC、GDB 與 libstdc++ 內部結構，不支援 MSVC STL 或 libc++ 的容器內部解析。
- C++ 容器越多、資料越大，每個步驟需要的 GDB 命令就越多，也越容易達到三秒限制。

## 安全性提醒

本專案是教學工具，**不是安全沙箱**。使用者程式會在有時間限制的獨立子行程與暫存工作目錄中執行，並受到 AST 檢查、受限 built-ins 與步驟上限保護；這些措施只能降低意外風險，不能當作執行惡意程式碼的安全邊界。請勿把它直接公開部署並用來執行不受信任的程式碼。

## 官方安裝參考

- [Python：在 Windows 使用 Python](https://docs.python.org/3/using/windows.html)
- [Python：建立虛擬環境](https://docs.python.org/3/library/venv.html)
- [Python Packaging：使用 pip 與虛擬環境](https://packaging.python.org/guides/installing-using-pip-and-virtual-environments/)
- [MSYS2：安裝與開始使用](https://www.msys2.org/)
- [MSYS2：UCRT64 GCC 套件](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gcc?repo=ucrt64)
- [MSYS2：UCRT64 GDB 套件](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gdb?repo=ucrt64)
