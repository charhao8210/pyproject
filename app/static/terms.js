// Every word the debugger shows, and what it means. The main page shows these on hover
// (`data-term="Visited"`); the help page (/help) lists them all. One list for both.
(function () {
    const TERMS = [
        // Visualizer marks
        {group: "視覺化圖的標記", term: "Visited", tip: "已經走過的格子或節點：visited / vis 陣列為 true，或距離表已經有值（-1、INF 代表還沒走到）。牆壁永遠不算。"},
        {group: "視覺化圖的標記", term: "Frontier", tip: "還在 queue 或 stack 裡、等著被處理的格子。"},
        {group: "視覺化圖的標記", term: "Current", tip: "程式現在所在的格子或節點，例如 node、u、row/col 指到的位置。"},
        {group: "視覺化圖的標記", term: "Reading", tip: "這一步被當作索引的位置，例如 i、j、mid、l、r 指到的那一格。只標在程式真的用這個變數索引的陣列上。"},
        {group: "視覺化圖的標記", term: "Written", tip: "被這一行寫入、值改變的格子（橘框）。"},
        {group: "視覺化圖的標記", term: "New", tip: "這一行新加進容器的元素（push、push_back、append），只在這一步標成淺藍色，下一步恢復一般顏色。"},
        {group: "視覺化圖的標記", term: "Blocked", tip: "牆壁（# 或 *），不能走。"},
        {group: "視覺化圖的標記", term: "In queue", tip: "現在在 queue、stack 或 priority_queue 裡的節點（虛線外圈）。上方那行依序列出整個佇列，第一個最先被取出。"},
        {group: "視覺化圖的標記", term: "Route", tip: "程式正在組出的答案路徑（例如 route、path 陣列），用藍色粗線依序連起來；回溯時連到目前的 now。"},
        {group: "視覺化圖的標記", term: "Edge being checked", tip: "目前節點正在檢查的那條邊（黃色粗線）。"},
        {group: "視覺化圖的標記", term: "directed", tip: "有向圖：每條邊只存了一個方向（例如只有 adj[a].push_back(b)），所以畫箭頭。兩點之間有多條邊時會畫成分開的弧線。"},
        {group: "視覺化圖的標記", term: "undirected", tip: "無向圖：每條邊兩個方向都存了（adj[a] 和 adj[b] 都有），所以每條邊只畫一次、不畫箭頭。"},
        {group: "視覺化圖的標記", term: "Edge direction", tip: "邊的方向是從資料猜的：每條邊兩個方向都存了就當成無向圖。但有向圖也可能剛好兩個方向都有（1→2 和 2→1），猜錯時在這裡改成 directed 或 undirected。"},
        {group: "視覺化圖的標記", term: "pairs read as", tip: "帶權重的鄰接表存的是 pair，這裡寫出哪一個被當成節點、哪一個被當成權重。是從程式碼（例如 w = e.first、auto [v, w]）判斷的。"},
        {group: "視覺化圖的標記", term: "∞", tip: "INF（例如 1e9、0x3f3f3f3f）這種「還沒算出來」的佔位值。畫成虛線短柱，不參與長條高度的縮放；滑鼠停在上面可看實際數字。"},
        {group: "視覺化圖的標記", term: "off the grid", tip: "這組座標在格子外面（例如往牆外試探的 nr = -1），所以圖上沒有標記。"},
        {group: "視覺化圖的標記", term: "clipped", tip: "資料太大，只畫出前面一部分。長陣列只讀取前 50 項，標題會寫「0–49 of 80 items」。"},
        {group: "視覺化圖的標記", term: "last known state", tip: "這個變數現在不在範圍內（例如在別的函式裡），圖上顯示的是它最後一次看得到的樣子。"},
        {group: "視覺化圖的標記", term: "Running now", tip: "正在執行的那一次函式呼叫。"},
        {group: "視覺化圖的標記", term: "On the call path", tip: "還沒結束、正在等子呼叫回傳的呼叫。"},
        {group: "視覺化圖的標記", term: "Waiting on a call", tip: "還沒結束、正在等子呼叫回傳的呼叫。"},
        {group: "視覺化圖的標記", term: "Returned", tip: "已經結束的呼叫；箭頭後面是它回傳的值。"},
        // Variables panel
        {group: "Variables 區", term: "Used on this line", tip: "黃色名字：黃色那一行（還沒執行）會用到的變數。"},
        {group: "Variables 區", term: "Changed by the last line", tip: "橘色：上一行執行後，值改變了的變數。"},
        {group: "Variables 區", term: "First appearance", tip: "整列淺藍色：這個變數第一次出現（剛被宣告）。"},
        {group: "Variables 區", term: "now -> next", tip: "例如 7 -> mid+1 = 7+1 = 8：左邊是現在的值，右邊是黃色那一行執行完之後的值，中間是它怎麼算出來的。"},
        {group: "Variables 區", term: "same list as", tip: "↪ 後面是這個變數指向的物件：same list as a 代表和 a 是同一個 list（例如 b = a）；matrix[1] 代表它就是 matrix 的第 1 列（例如 row = matrix[1]）。改其中一個，另一個也會跟著變。滑鼠停在上面時，會把那個位置在圖上和 Variables 裡框起來。"},
        {group: "Variables 區", term: "integer", tip: "斜體的 integer / floating / text：找不到這個變數的宣告，所以只顯示值的種類，不猜它是 int 還是 long long。"},
        {group: "Variables 區", term: "Function", tip: "Variables 標題旁邊的名字：現在所在的函式。lambda 會顯示存放它的變數名稱（例如 dfs）。"},
        // Header and timeline
        {group: "上方與時間軸", term: "guessed from the code", tip: "演算法名稱是從程式碼的樣子猜的，可能猜錯。猜錯時可以用 View 選單換一種畫法。"},
        {group: "上方與時間軸", term: "View", tip: "選擇要怎麼畫：Auto 是自動選的畫法，其他選項可以指定要畫哪個變數、用哪種圖。"},
        {group: "上方與時間軸", term: "Input values", tip: "圖上方的 n = 5 這一列：只讀一次、之後不會再變的輸入值。讀進來的那一步會先用淺藍色標出。"},
        {group: "上方與時間軸", term: "line", tip: "事件 line：停在一般的一行程式，黃色那行還沒執行。"},
        {group: "上方與時間軸", term: "call", tip: "事件 call：剛進入一個函式。"},
        {group: "上方與時間軸", term: "return", tip: "事件 return：函式要回傳了。"},
        {group: "上方與時間軸", term: "exception", tip: "事件 exception（RE，執行錯誤）：程式在這裡出錯停止，例如除以零、陣列越界、assert 失敗。"},
        {group: "上方與時間軸", term: "stopped", tip: "事件 stopped（TLE）：超過時間限制（Python 3 秒、C++ 10 秒）或超過 5000 步，程式被停下來，前面的步驟都還在。"},
        {group: "上方與時間軸", term: "Loop jump", tip: "|‹ 回到這個迴圈開始之前，›| 跳到這個迴圈結束之後；不在迴圈裡時不能按。"},
    ];

    const byTerm = new Map(TERMS.map((entry) => [entry.term, entry.tip]));

    // `In q`, `In pq`, `In stack`: the queue's own name follows "In".
    function lookup(term) {
        if (byTerm.has(term)) return byTerm.get(term);
        if (/^In \S+$/.test(term)) return byTerm.get("In queue");
        return null;
    }

    window.DebuggerTerms = {list: TERMS, lookup};
})();
