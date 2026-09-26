# OptiChat

Windows 本機 AI 工具：Ollama 文字／圖片聊天、本機 Agent、框選截圖、語音朗讀、系統匣常駐、亮暗主題與自動更新。

- **介紹與下載：** https://optiimind.com/Tools/optiichat/
- **程式碼：** 本目錄
- **目前版本：** 1.3.28

## 安裝

1. 從介紹頁下載 `OptiChat-Setup-1.3.28.exe`，執行安裝精靈；不需要自行安裝 Python。安裝包已包含 1.3.28，日後啟動仍會自動更新。
2. 安裝包含獨立 Python 3.14.3、介面、PDF、Excel、Word 及朗讀套件，放在 `%LOCALAPPDATA%\OptiiChat\python`；程式在同一資料夾下的 `app`。為保留舊版設定與更新相容性，內部資料夾名稱沿用 OptiiChat。
3. 自動建立桌面與開始功能表「OptiChat」捷徑。雙擊即可開啟。
4. 初次啟動若缺少 Ollama，會自動下載官方安裝檔、驗證 Ollama Inc. 程式碼簽章並安裝；缺少 Vision 相容服務時會下載官方 0.24.0 Windows ZIP（約 2.1 GB），驗證官方 SHA-256，並安裝 CPU／Vulkan 檔案。下載失敗可在準備視窗重試。
5. 首次使用若缺少 `llama3.2-vision`，即使已有其他模型，也會在聊天介面自動下載它（約 7.8 GB），並預設用於文字與圖片。已有 OptiChat 設定時保留原本選擇；連線或磁碟空間不足時顯示錯誤，可稍後重試。

安裝程式目前**未經程式碼簽章**；Windows 可能顯示發行者未知。安裝本身不需要系統管理員權限，Ollama 官方安裝程式的提示以其本身為準。請預留模型空間；CPU 圖片推論可能需數分鐘。

可從 Windows「已安裝的應用程式」移除 OptiChat；移除程式與內含 Python，保留設定、音訊、Ollama 與模型。更新或重新安裝前先從系統匣結束程式。ZIP 原始碼安裝仍保留，需自行準備 Python 3.11+，執行 `Install-OptiiChat.cmd`；缺少 Ollama 時也會自動安裝。

## PDF

把 PDF 拖到聊天區／輸入框，或按輸入框旁的「＋」選檔，即在背景解析並顯示附件，原有草稿會保留。文字型 PDF 直接擷取文字；完全沒有文字層時，自動將第一頁縮小為圖片，交給圖片模型辨識。附件旁的「選頁」可改用指定頁面，適合掃描文件與圖表；不會自動辨識整份掃描 PDF。輸入問題後按傳送。

程式先檢查大小（上限 100 MB）。PDF 原檔壓縮通常不會加快文字擷取，且可能降低品質；因此文字直接解析，掃描頁則依大小縮小像素並以 JPEG 壓縮後才送入本機模型。20 MB 以上的掃描檔首圖最長邊 896 px，其餘 1120 px；原始 PDF 不會被改動。

文字擷取最多 200 頁／60,000 字，實際送出再依模型 Context 截取並標示「部分內容」。可提高 Context 或改選特定頁面。頁面圖片一次一頁，密碼保護的 PDF 請先自行解鎖。附件在本機處理，按傳送後才交給模型；送出後另存一份 PDF 到該對話的本機紀錄，雙擊對話中的 PDF 附件可由 Windows 預設閱讀器開啟。換附件／新對話會清理程式自己的暫存圖片，原始 PDF 保留。

## 使用

- 主視窗採深色青藍聊天版面：左側歷史對話、中間對話卡片、上方狀態列、下方靠左輸入與 CPU／GPU 資源列。對話紀錄、聊天及設定分頁只在內容超出可視範圍時顯示捲軸。右上角齒輪開啟設定，左邊的驚嘆號開啟「關於 OptiChat」，可前往官網或下載頁；對話紀錄旁的放大鏡可搜尋標題、提問、回覆與附件名稱，命中內容時會顯示摘要；點選結果會開啟對話並捲到第一則命中訊息。左側清單顯示完整日期時間標題；舊版對話也會以問答卡片呈現。可在設定改為亮色或跟隨 Windows。
- 左側對話紀錄上方可切換「對話／Agent」分頁。Agent 使用設定中的文字模型；選擇工作資料夾、輸入目標後，可列出／搜尋一般文字檔、讀取 PDF 文字層與 Excel／Word，並編輯文字檔、Excel 儲存格、Word 段落。編輯前會顯示內容請使用者確認，並另存新檔、保留原件。每一步的工具結果與最終答覆都顯示在獨立時間軸，任務紀錄存於本機 `%LOCALAPPDATA%\OptiiChat\agents`，可從左側重新開啟、改名或刪除；執行中可停止，切回對話分頁不會中斷。不執行命令，也不包含 MCP 或外部 Skill 整合。
- AI 回覆標頭以金色顯示簡短模型家族名稱（例如 Llama、Gemma）；完整模型名稱仍保留在對話資料中。
- 對話卡片中的提問、回覆及附件名稱可用滑鼠框選，按 `Ctrl+C` 或右鍵「複製」。文字區為唯讀，長篇回覆自動換行並隨內容增高。
- 設定視窗開啟時置中於主視窗，分頁和表單跟隨主程式的亮／暗色系。設定 → 聊天模型：選已安裝模型及 CPU／GPU。圖片選單只列支援 vision 的模型。
- 設定 → 下載模型：可開啟 [Ollama 模型庫](https://ollama.com/search)，輸入模型名稱（例如 `llama3.2-vision` 或 `model:tag`）後在背景下載，查看目前檔案進度並可取消。完成後模型清單會更新，再到「聊天模型」選擇；只支援 embedding 的模型不會出現在聊天選單。下載不會自動更改目前使用的模型。
- 左側「＋ 新對話」開始新聊天；歷史清單以首次對話時間命名，對紀錄按右鍵可重新命名或刪除（刪除前會確認），F2 也可改名。紀錄存在本機 `%LOCALAPPDATA%\OptiiChat\history`，重啟後仍可讀取。新送出的圖片與截圖會保存縮圖及可檢視的圖片副本；點擊對話中的圖片可在程式內放大觀看。PDF 顯示檔案圖示與名稱，雙擊可用 Windows 預設閱讀器開啟。刪除對話時會一併移除該對話的縮圖和附件副本。舊版紀錄若只保存縮圖，仍可點擊查看縮圖；未保存原檔的舊 PDF 需重新附加。附件副本不能用於重新分析，重新提問時仍需附加檔案。
- 按輸入框旁「+」選圖片／PDF，或直接拖入聊天區。旁邊的「截圖」或程式內 `Ctrl+Shift+S` 可框選畫面，放開後圖片會顯示在輸入框預覽；Esc／右鍵取消。
- 輸入框會隨文字及自動換行從 3 行增高至最多 6 行；再多的內容在輸入框內捲動。`Ctrl+Enter` 傳送。關閉視窗預設收至系統匣；首次關閉會提示圖示可能位於 Windows 右下角的「^」隱藏圖示區。若系統匣啟動失敗，視窗會留在工作列供重新開啟。從系統匣選「結束程式」才真正離開。
- 啟動時偵測 NVIDIA 顯存；未達單卡 12 GB 建議配置或無法偵測時，隱藏 Breeze、Voice Design／Clone 與服務參數頁，改用 Windows 朗讀。原有聲音描述與參考音檔設定保留。符合硬體條件仍須另外啟動相容的 Breeze 服務。
- 下方的手動朗讀、停止語音與匯出 WAV 按鈕目前隱藏；設定內仍可開啟回覆後自動朗讀。Breeze-TTS-2 僅提供 API 串接，需要另行啟動官方 CUDA 服務；不包含模型權重。
- 完整說明見 [OptiiChat-使用說明.md](OptiiChat-使用說明.md)。

## 自動更新

每次啟動都向 OptiChat R2 網域讀取 `update.json`，有新版就下載 ZIP、驗證 SHA-256 和檔案清單，套用後才啟動。程式執行中每 15 分鐘重試，背景下載的更新會在系統匣「結束程式」後自動套用；按視窗右上角 × 只會隱藏。離線時仍可使用現有版本，恢復連線後繼續檢查。自動更新不可關閉，設定中保留手動「立即檢查更新」。

更新只更換發行包的程式檔案；使用者設定、語音輸出與模型保留。寫入前備份舊檔，寫入失敗時嘗試還原；偵測到本機修改時停止覆蓋。備份與更新紀錄位於 `%LOCALAPPDATA%\OptiiChat\updates`。來源限定 HTTPS `optiichat-update.optiimind.com`，並以 SHA-256 驗證，**沒有額外程式碼簽章**。

EXE 內含的 Python 執行環境不隨小版本 ZIP 更新；若未來更換 Python，需下載新版 EXE。套件需求變更時，更新器使用內含 pip 安裝。

Git clone 的開發者若修改程式，應以 Git 更新；自動更新不會覆寫這些變更。更新套件可能更新 Python 相依套件，模型本身不會被自動更換。

## 發行新版（維護者）

1. 修改程式與 `opti_version.py` 的三段式版本號，例如 `1.0.1`。
2. 以 UI Python 環境執行：
   ```powershell
   python -m unittest test_opti_update test_opti_chat test_llama_vision_ui test_opti_agent -v
   python opti_release.py
   ```
3. 先將 `downloads/OptiiChat-版本.zip` 上傳到 `optiichat-downloads` R2 bucket，驗證公開 URL 的 SHA-256，再將 `r2-update.json` 上傳為 R2 的 `update.json`。manifest 必須最後發佈。
4. 提交程式碼、`package-files.json`、ZIP 及 `r2-update.json`。GitHub `update.json` 保留過渡版，供仍使用舊版更新器的用戶先切換到 R2。

`opti_release.py` 只打包明列的程式、測試、說明與品牌素材，排除設定、暫存、使用者音檔、模型權重及 Git 資訊。若新增新的檔案類型，請同步維護 `opti_update.safe_name` 的允許清單。

## 建置 EXE（維護者）

使用官方 NSIS 3.12 可攜式工具與 Windows x64 CPython 3.14.3。先安裝 `opti-requirements.txt`，執行測試與 `python opti_release.py`，再執行：

```powershell
python installer/build.py --makensis C:\tools\nsis-3.12\makensis.exe
```

建置時加上 `--download-base-url https://optiichat-update.optiimind.com`。上傳 EXE 到對應的 R2 bucket 後，確認公開網址的檔案大小與 SHA-256 和 `installer.json` 一致，再發佈網站的 `installer.json`。下載頁會使用該 manifest 的 `url`。

工具只複製 Python 標準發行目錄，排除原有 site-packages，再依鎖定版本從 PyPI 安裝套件，不包含個人環境、設定或模型。輸出 EXE、`installer.json` 與 `.installer-build` 暫存。提交 EXE 與 manifest，暫存不提交。Python 與套件授權檔保留在執行環境內。

`--test` 編譯隔離測試安裝版本，不建立使用者捷徑或登錄入口，安裝至 `.installer-build/install-smoke`。

## 資料與相容性

- 一般 Ollama：本機 `11434`；Llama 3.2 Vision 相容服務：CPU `11435`／Vulkan `11436`。
- 使用 `OLLAMA_MODELS` 環境變數或 Ollama 預設模型目錄。
- 設定／音訊：`%LOCALAPPDATA%\OptiiChat`；聊天紀錄與 Agent 任務分別儲存在 `history`、`agents`。
- 網路用於安裝相依套件、模型下載、R2 更新，以及使用者自行指定的 Breeze 服務。
- 官網 Logo 來源見 [opti_assets/README.md](opti_assets/README.md)。Breeze 權重與自架產出受其研究及非商業授權限制；本儲存庫不散布該模型。

80 項自動測試涵蓋聊天串流、截圖、歷史對話、Agent 文書工具與分頁、模型初始化、語音串接及更新驗證／還原。測試不代表所有硬體組合皆可執行所有模型。
