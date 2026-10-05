# Code Visual Debugger

[English](README.md) | 繁體中文

[更新說明與後續改善方向](CHANGELOG.md)

Code Visual Debugger 是一套在本機執行的 Python／C++ 程式視覺化除錯工具。你可以選擇語言、貼上程式碼、輸入測試資料，執行一次後使用上一步／下一步逐步查看程式狀態。

每個執行步驟會保留目前程式碼行、重要區域／全域變數、物件身分、函式呼叫堆疊、累積輸出與例外。系統會嘗試辨識演算法，預設聚焦目前操作；DFS 遞迴的已完成分支會折疊成摘要，需要時再展開。

## 主要功能

- 支援 Python 與 C++17 程式。
- 使用逐行、重要事件、函式呼叫、函式返回、資料變更與跳過呼叫，瀏覽已保存的執行快照。
- 顯示區域變數、全域變數、物件身分與函式呼叫堆疊。
- 顯示截至目前步驟的標準輸出。
- 支援 `input()`、`sys.stdin.read()` 與 C++ 標準輸入。
- 視覺化陣列、DP／矩陣、圖、遞迴呼叫路徑、並查集、線段樹。
- 新增 Heap、滑動視窗、單調堆疊／deque、Fenwick／BIT、字串比對／KMP、Trie 六種模式。
- 可手動配對變數角色、切換聚焦／跟隨位置，以及調整擷取範圍。
- 發生 RE、TLE 或超過步驟限制時，仍保留停止前已收集的步驟。
- Python 支援受限的 `heapq`、`bisect`、`collections.deque/defaultdict/Counter` 與 `math` 匯入。
- C++ 可解析支援的純量、字串、原生陣列、vector、deque、queue／stack、priority_queue、set／map 結構。

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

Windows 也支援專案內的完整工具鏈：`.tools/msys64/ucrt64`。程式會優先使用 PATH 中的工具，找不到時再搜尋此目錄下的 `bin/g++.exe` 與 `bin/gdb.exe`，並讓編譯器、除錯器及被除錯程式取得必要 DLL。若這個目錄已備妥，可直接使用 C++ 模式；不要只複製兩個 EXE，必須保留完整套件與相依檔案。`.tools` 不會提交到 Git。更新應用程式碼後，請重新啟動 Uvicorn。

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

1. 在右上角語言選單選擇 `Python` 或 `C++`。
2. 將程式貼到程式碼編輯區。
3. 如果程式會讀取輸入，在 **輸入** 欄位填入測試資料。
4. 按 **執行**。也可以先從 **選擇範例** 載入本機範例與測試資料，再按執行。
5. 使用時間軸、變數、視覺化圖與輸出區觀察程式如何變化。**自動** 選單可選畫法，旁邊的變數選單可指定要畫的資料。

圖的標題只顯示資料類型、變數及大小；目前讀取或變更顯示一行摘要。展開摘要可看完整公式、候選值與依賴。長演算法名稱、辨識依據和長條尺度放在 **⚙ 顯示設定**；**▾／▸** 收合或展開區塊。未擷取、範圍外及沿用狀態仍直接提示。

### DFS 與大型資料的閱讀方式

預設勾選 **聚焦**（Focus）與 **跟隨**（Follow）。DFS／遞迴顯示目前呼叫路徑，已完成分支折疊成摘要；展開摘要可以查看已記錄的呼叫，點選呼叫可跳到它的進入或最後步驟。**呼叫鏈** 只看目前呼叫堆疊。返回只代表呼叫已返回，系統不會把每次返回都當成剪枝或找到解。

Focus 讓目前讀取、寫入與相關路徑更醒目，其他資料淡化或折疊。DP 顯示座標與已記錄的依賴，圖顯示相關鄰居與佇列，排序保持固定比例，並查集顯示父鏈，線段樹可顯示查詢覆蓋與已擷取的 lazy tag。關閉 Focus 可看完整的可用資料；關閉 Follow 可固定畫面位置，方便自行檢查。

### 時間軸與跳步

| 選項 | 用途 |
| --- | --- |
| 逐行 | 移到相鄰執行快照 |
| 重要事件 | 在已記錄的呼叫、返回、變更、操作與停止事件之間跳轉 |
| 函式呼叫／函式返回 | 移到下一個或上一個符合的呼叫／返回事件 |
| 資料變更 | 跳到已記錄的資料變化 |
| 跳過呼叫 | 有記錄結束位置時，跳到目前呼叫的結束 |

跳步模式也會套用到 **播放**；滑桿仍可存取個別快照。`←`／`→` 移動，`Space` 播放或暫停，`|‹`／`›|` 跳到目前迴圈的前後。

### 手動配對變數

辨識錯誤或變數命名不常見時，開啟 **⚙ 顯示設定**，選擇 **演算法模式**，指定主要資料與對應角色，再按 **套用**。例如滑動視窗可配對「主要資料」、「左界」、「右界」、「總和／統計」；圖可配對佇列、距離／入度與父節點；KMP 可配對文字、模式字串與 Prefix table；線段樹可配對 lazy tag 和查詢左右界。Escape 可關閉設定並回到齒輪按鈕。

配對內容是程式中已記錄的變數名稱，不是監看運算式。留在 **自動** 會使用自動辨識。套用設定會用目前的程式與輸入重新執行；模式仍需要相容的資料形狀與程式結構。

### 新增模式與範例

| 模式 | 畫面重點 | 範例檔案 |
| --- | --- | --- |
| Heap / Priority queue | 同步陣列索引與父子樹、已擷取的 top | [sample8_heap.py](samples/sample8_heap.py) |
| 滑動視窗 | 左右界、有效區間、已記錄的總和／統計 | [sample9_sliding_window.py](samples/sample9_sliding_window.py) |
| 單調堆疊 / deque | 容器順序、可用的來源索引、兩次擷取間的變化 | [sample10_monotonic_stack.py](samples/sample10_monotonic_stack.py) |
| Fenwick / BIT | 每個索引涵蓋的區間與本步存取位置 | [sample11_fenwick.py](samples/sample11_fenwick.py) |
| 字串比對 / KMP | 文字與模式對齊、實際比較、已擷取的 prefix／failure table | [sample12_kmp.py](samples/sample12_kmp.py) |
| Trie | 前綴階層、邊上的字元、已記錄的結束標記、可折疊分支 | [sample13_trie.py](samples/sample13_trie.py) |

Heap 範例使用手寫 Python 操作，因此能追蹤使用者程式中的比較與交換。實際 `heapq` 也能執行，但不會重建函式庫內部的 sift；內建排序也只顯示能觀察到的狀態。Heap 的儲存順序不是依序 pop 的排序結果。

### 擷取範圍與未知資料

「每個容器擷取」可選 **50／100／200／500 項**，預設 50；Python「巢狀深度」可選 **2／3／4／6／8 層**，預設 4。API 接受 10–500 項與 Python 深度 2–8。C++ 一維容器也使用項目上限；表格固定最多 **30 列 × 40 欄**，不使用 Python 深度設定。

Python 預設時間上限為三秒。提高擷取設定會按比例增加記錄資料的時間預算，最多十五秒；5000 步上限仍然保留。C++ 保持十秒上限。

提高上限並套用設定會重新執行，不會補出舊快照沒有收集的資料。分頁、折疊與完整視圖都只瀏覽已擷取的內容；未擷取的值、超出範圍的索引與離開作用域的資料會明確標示。未知格子不會被假設成零，沒有追蹤證據的操作也不會被補畫。

## 執行測試

已啟用虛擬環境時：

```bash
python -m pytest -q
```

Windows 未啟用虛擬環境時：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

測試會偵測 PATH 與 Windows 專案內 `.tools/msys64/ucrt64` 的完整工具鏈。只有兩處都無法取得 `g++`／`gdb` 時，需要工具鏈的測試才會跳過；Python 與前端相關測試仍會執行。

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
  "stdin": "21\n",
  "capture_items": 50,
  "capture_depth": 4,
  "bindings": {}
}
```

`language` 可使用 `python` 或 `cpp`。`bindings` 可指定角色，例如 `{"mode":"window","primary":"nums","left":"left","right":"right","total":"total"}`。回應包含原始碼、標準輸入、執行狀態、演算法判斷與按時間排列的 `steps`；`GET /api/examples` 可取得內建範例。

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
  │      ├── 資料結構與各種演算法模式
  │      ├── 手動變數配對
  │      └── 已記錄的操作與跳步索引
  │
  ▼
Vanilla JavaScript 前端
  ├── 程式碼行檢視器
  ├── 變數與資料結構
  ├── 聚焦的圖、樹與呼叫路徑
  ├── 逐行／事件／呼叫／返回／變更跳步
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

- Python 匯入限於 `sys.stdin`、公開的 `heapq`／`bisect` 操作、`collections.deque/defaultdict/Counter` 與 `math` 數學函式／常數；可使用模組匯入、明確成員匯入與別名。其他模組、私有成員、萬用字元與相對匯入不允許；成員須存在於正在執行的 Python 版本。
- 不支援 async、執行緒、多行程、檔案 I/O、網路、GUI、NumPy、pandas 或第三方函式庫。
- 沒有使用者中斷點、監看運算式、變數修改、`pdb` 整合或控制流程圖。
- 演算法辨識採用啟發式規則，介面標為「guessed from the code」；可用變數配對修正，但仍需要相容的已擷取資料。
- `list.sort()`、C 實作的 `heapq` 與 C++ 函式庫不會公開完整內部操作。只能呈現可觀察的輸入／結果；比較、交換、sift、剪枝與找到解都需要已記錄的程式或狀態證據。
- 單次追蹤最多保存 5,000 個快照，標準輸出最多 100,000 字元；容器與深度上限如上，較大的樹也有繪製／版面上限。
- C++ 模式依賴 GCC、GDB 與 libstdc++ 內部結構，不支援 MSVC STL 或 libc++ 的容器內部解析。
- C++ 可解析支援的純量、字串、原生陣列、vector（含 bool、pair、string、巢狀／鄰接陣列）、全域變數，以及 deque、預設 deque 儲存的 queue／stack、vector 儲存的 priority_queue、set／multiset、map／multimap。unordered 容器、不支援的元素或其他 adaptor 儲存方式仍顯示未解碼。
- 大型原生陣列會分片擷取；C++ 巢狀表格與 `adj[N]` 最多 30 × 40。
- 預設 Python 時限三秒、C++ 十秒。C++ 容器越多、資料越大，每步需要的 GDB 命令越多；超時仍回傳已保存的部分追蹤。

## 安全性提醒

本專案是教學工具，**不是安全沙箱**。使用者程式會在有時間限制的獨立子行程與暫存工作目錄中執行，並受到 AST 檢查、受限 built-ins 與步驟上限保護；這些措施只能降低意外風險，不能當作執行惡意程式碼的安全邊界。請勿把它直接公開部署並用來執行不受信任的程式碼。

## 官方安裝參考

- [Python：在 Windows 使用 Python](https://docs.python.org/3/using/windows.html)
- [Python：建立虛擬環境](https://docs.python.org/3/library/venv.html)
- [Python Packaging：使用 pip 與虛擬環境](https://packaging.python.org/guides/installing-using-pip-and-virtual-environments/)
- [MSYS2：安裝與開始使用](https://www.msys2.org/)
- [MSYS2：UCRT64 GCC 套件](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gcc?repo=ucrt64)
- [MSYS2：UCRT64 GDB 套件](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gdb?repo=ucrt64)
