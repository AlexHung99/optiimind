# OptiChat

Windows 本機 AI 聊天工作室：Ollama 文字／圖片聊天、框選截圖、語音朗讀、系統匣常駐、亮暗主題與自動更新。

- **介紹與下載：** https://optiimind.com/Tools/optiichat/
- **程式碼：** 本目錄
- **目前版本：** 1.3.0

## 安裝

1. 從介紹頁下載 `OptiChat-Setup-1.3.0.exe`，執行安裝精靈；不需要自行安裝 Python。
2. 安裝包含獨立 Python 3.14.3、介面、PDF 及朗讀套件，放在 `%LOCALAPPDATA%\OptiiChat\python`；程式在同一資料夾下的 `app`。為保留舊版設定與更新相容性，內部資料夾名稱沿用 OptiiChat。
3. 自動建立桌面與開始功能表「OptiChat」捷徑。雙擊即可開啟。
4. 初次啟動若尚未安裝 Ollama，會顯示官方下載入口；完成 Ollama 安裝後按「繼續」。缺少 Vision 相容服務時會下載官方 0.24.0 Windows ZIP（約 2.1 GB），驗證官方 SHA-256，並安裝 CPU／Vulkan 檔案。
5. 完全沒有模型時，在聊天介面自動下載 `llama3.2-vision`（約 7.8 GB）。已有模型與設定會保留。

安裝程式目前**未經程式碼簽章**；Windows 可能顯示發行者未知。安裝本身不需要系統管理員權限，Ollama 官方安裝程式的提示以其本身為準。請預留模型空間；CPU 圖片推論可能需數分鐘。

可從 Windows「已安裝的應用程式」移除 OptiChat；移除程式與內含 Python，保留設定、音訊、Ollama 與模型。更新或重新安裝前先從系統匣結束程式。ZIP 原始碼安裝仍保留，需自行準備 Python 3.11+ 與 Ollama，執行 `Install-OptiiChat.cmd`。

## PDF

把 PDF 拖到聊天區／輸入框，或按輸入框旁的「＋」選檔，即在背景解析並顯示附件，原有草稿會保留。文字型 PDF 直接擷取文字；完全沒有文字層時，自動將第一頁縮小為圖片，交給圖片模型辨識。附件旁的「選頁」可改用指定頁面，適合掃描文件與圖表；不會自動辨識整份掃描 PDF。輸入問題後按傳送。

程式先檢查大小（上限 100 MB）。PDF 原檔壓縮通常不會加快文字擷取，且可能降低品質；因此文字直接解析，掃描頁則依大小縮小像素並以 JPEG 壓縮後才送入本機模型。20 MB 以上的掃描檔首圖最長邊 896 px，其餘 1120 px；原始 PDF 不會被改動。

文字擷取最多 200 頁／60,000 字，實際送出再依模型 Context 截取並標示「部分內容」。可提高 Context 或改選特定頁面。頁面圖片一次一頁，密碼保護的 PDF 請先自行解鎖。附件在本機處理，按傳送後才交給模型；換附件／新對話會清理程式自己的暫存圖片，原始 PDF 保留。

## 使用

- 主視窗採深色青藍聊天版面：左側快捷列與歷史對話、中間對話卡片、上方狀態及操作列、下方輸入與 CPU／GPU 資源列。可在設定改為亮色或跟隨 Windows。
- 設定 → 聊天模型：選已安裝模型及 CPU／GPU。圖片選單只列支援 vision 的模型。
- 左側「＋ 新對話」開始新聊天；歷史清單以首次對話時間命名，可選取並按「重新命名」（或 F2）修改。紀錄存在本機 `%LOCALAPPDATA%\OptiiChat\history`，重啟後仍可讀取。歷史圖片只保存文字註記，不保存圖片副本；重新分析圖片時需重新附加。
- 按輸入框旁「＋」選圖片／PDF，或直接拖入聊天區。上方「截圖」或程式內 `Ctrl+Shift+S` 框選，放開自動附加；Esc／右鍵取消。
- `Ctrl+Enter` 傳送。關閉視窗預設收至系統匣；從系統匣選「結束程式」才真正離開。
- 啟動時偵測 NVIDIA 顯存；未達單卡 12 GB 建議配置或無法偵測時，隱藏 Breeze、Voice Design／Clone 與服務參數頁，改用 Windows 朗讀。原有聲音描述與參考音檔設定保留。符合硬體條件仍須另外啟動相容的 Breeze 服務。
- Windows 語音可直接朗讀與匯出 WAV。Breeze-TTS-2 僅提供 API 串接，需要另行啟動官方 CUDA 服務；不包含模型權重。
- 完整說明見 [OptiiChat-使用說明.md](OptiiChat-使用說明.md)。

## 自動更新

預設每天檢查一次此 GitHub 儲存庫的 `update.json`，背景下載更新 ZIP、驗證 SHA-256 和檔案清單。下次由啟動檔啟動時才套用，不強制重啟聊天。可在設定關閉自動檢查，或使用「立即檢查更新」。

更新只更換發行包的程式檔案；使用者設定、語音輸出與模型保留。寫入前備份舊檔，寫入失敗時嘗試還原；偵測到本機修改時停止覆蓋。備份與更新紀錄位於 `%LOCALAPPDATA%\OptiiChat\updates`。來源以 HTTPS GitHub 儲存庫與 SHA-256 驗證，**沒有額外程式碼簽章**。

EXE 內含的 Python 執行環境不隨小版本 ZIP 更新；若未來更換 Python，需下載新版 EXE。套件需求變更時，更新器使用內含 pip 安裝。

Git clone 的開發者若修改程式，應以 Git 更新；自動更新不會覆寫這些變更。更新套件可能更新 Python 相依套件，模型本身不會被自動更換。

## 發行新版（維護者）

1. 修改程式與 `opti_version.py` 的三段式版本號，例如 `1.0.1`。
2. 以 UI Python 環境執行：
   ```powershell
   python -m unittest test_opti_update test_opti_chat test_llama_vision_ui -v
   python opti_release.py
   ```
3. 提交程式碼、`package-files.json`、`downloads/OptiiChat-版本.zip`、`update.json` 至此儲存庫 `main`。
4. 保留舊版下載包。更新檢查使用新 manifest，EXE 下載按鈕另外讀取 `installer.json`。

`opti_release.py` 只打包明列的程式、測試、說明與品牌素材，排除設定、暫存、使用者音檔、模型權重及 Git 資訊。若新增新的檔案類型，請同步維護 `opti_update.safe_name` 的允許清單。

## 建置 EXE（維護者）

使用官方 NSIS 3.12 可攜式工具與 Windows x64 CPython 3.14.3。先安裝 `opti-requirements.txt`，執行測試與 `python opti_release.py`，再執行：

```powershell
python installer/build.py --makensis C:\tools\nsis-3.12\makensis.exe
```

若安裝檔改由 Cloudflare R2 提供，建置時加上 `--download-base-url https://下載用的.optiimind.com`，並替換為實際啟用的自訂網域。上傳 EXE 到對應的 R2 bucket 後，確認公開網址的檔案大小與 SHA-256 和 `installer.json` 一致，再發佈 manifest。下載頁會使用 `installer.json` 的 `url`，因此只有完成上傳與驗證後才切換網址。

工具只複製 Python 標準發行目錄，排除原有 site-packages，再依鎖定版本從 PyPI 安裝套件，不包含個人環境、設定或模型。輸出 EXE、`installer.json` 與 `.installer-build` 暫存。提交 EXE 與 manifest，暫存不提交。Python 與套件授權檔保留在執行環境內。

`--test` 編譯隔離測試安裝版本，不建立使用者捷徑或登錄入口，安裝至 `.installer-build/install-smoke`。

## 資料與相容性

- 一般 Ollama：本機 `11434`；Llama 3.2 Vision 相容服務：CPU `11435`／Vulkan `11436`。
- 使用 `OLLAMA_MODELS` 環境變數或 Ollama 預設模型目錄。
- 設定／音訊：`%LOCALAPPDATA%\OptiiChat`；聊天紀錄只在記憶體。
- 網路用於安裝相依套件、模型下載、GitHub 更新，以及使用者自行指定的 Breeze 服務。
- 官網 Logo 來源見 [opti_assets/README.md](opti_assets/README.md)。Breeze 權重與自架產出受其研究及非商業授權限制；本儲存庫不散布該模型。

38 項自動測試涵蓋聊天串流、截圖、模型初始化、語音串接與更新驗證／還原。測試不代表所有硬體組合皆可執行所有模型。
