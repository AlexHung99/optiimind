# OptiiChat

Windows 本機 AI 聊天工作室：Ollama 文字／圖片聊天、框選截圖、語音朗讀、系統匣常駐、亮暗主題與自動更新。

- **介紹與下載：** https://optiimind.com/Tools/optiichat/
- **程式碼：** 本目錄
- **目前版本：** 1.0.0

## 安裝

1. 安裝 Windows 64 位元版 [Python 3.11+](https://www.python.org/downloads/windows/) 與 [Ollama](https://ollama.com/download/windows)。
2. 從介紹頁下載 ZIP，解壓縮至可寫入的資料夾。
3. 執行 `Install-OptiiChat.cmd`。它會建立 `%LOCALAPPDATA%\OptiiChat\runtime` 的 Python 環境，安裝套件，並將程式安裝至 `%LOCALAPPDATA%\OptiiChat\app`。
4. 缺少 Vision 相容服務時，腳本從 Ollama 官方 GitHub 下載 0.24.0 Windows ZIP（約 2.1 GB），驗證官方 SHA-256，安裝 CPU／Vulkan 相容檔案。若本機已有相容服務則略過。
5. 日後執行 `Start-OptiiChat.cmd`。完全沒有 Ollama 模型時自動下載 `llama3.2-vision`（約 7.8 GB）；已有模型時使用下拉選單選擇。

這是 Python 程式包，不是獨立 EXE。請預留下載、解壓、Python 套件及模型空間。模型硬體需求各不相同；CPU 圖片推論可能需數分鐘。安裝腳本需要連網，不要求將模型傳到第三方服務。

## 使用

- 設定 → 聊天模型：選已安裝模型及 CPU／GPU。圖片選單只列支援 vision 的模型。
- 上方「截圖」或程式內 `Ctrl+Shift+S` 框選，放開自動附加；Esc／右鍵取消。
- `Ctrl+Enter` 傳送。關閉視窗預設收至系統匣；從系統匣選「結束程式」才真正離開。
- Windows 語音可直接朗讀與匯出 WAV。Breeze-TTS-2 僅提供 API 串接，需要另行啟動官方 CUDA 服務；不包含模型權重。
- 完整說明見 [OptiiChat-使用說明.md](OptiiChat-使用說明.md)。

## 自動更新

預設每天檢查一次此 GitHub 儲存庫的 `update.json`，背景下載更新 ZIP、驗證 SHA-256 和檔案清單。下次由啟動檔啟動時才套用，不強制重啟聊天。可在設定關閉自動檢查，或使用「立即檢查更新」。

更新只更換發行包的程式檔案；使用者設定、語音輸出與模型保留。寫入前備份舊檔，寫入失敗時嘗試還原；偵測到本機修改時停止覆蓋。備份與更新紀錄位於 `%LOCALAPPDATA%\OptiiChat\updates`。來源以 HTTPS GitHub 儲存庫與 SHA-256 驗證，**沒有額外程式碼簽章**。

Git clone 的開發者若修改程式，應以 Git 更新；自動更新不會覆寫這些變更。更新套件可能更新 Python 相依套件，模型本身不會被自動更換。

## 發行新版（維護者）

1. 修改程式與 `opti_version.py` 的三段式版本號，例如 `1.0.1`。
2. 以 UI Python 環境執行：
   ```powershell
   python -m unittest test_opti_update test_opti_chat test_llama_vision_ui -v
   python opti_release.py
   ```
3. 提交程式碼、`package-files.json`、`downloads/OptiiChat-版本.zip`、`update.json` 至此儲存庫 `main`。
4. 保留舊版下載包。更新檢查使用新 manifest，介紹頁下載按鈕也會讀取它。

`opti_release.py` 只打包明列的程式、測試、說明與品牌素材，排除設定、暫存、使用者音檔、模型權重及 Git 資訊。若新增新的檔案類型，請同步維護 `opti_update.safe_name` 的允許清單。

## 資料與相容性

- 一般 Ollama：本機 `11434`；Llama 3.2 Vision 相容服務：CPU `11435`／Vulkan `11436`。
- 使用 `OLLAMA_MODELS` 環境變數或 Ollama 預設模型目錄。
- 設定／音訊：`%LOCALAPPDATA%\OptiiChat`；聊天紀錄只在記憶體。
- 網路用於安裝相依套件、模型下載、GitHub 更新，以及使用者自行指定的 Breeze 服務。
- 官網 Logo 來源見 [opti_assets/README.md](opti_assets/README.md)。Breeze 權重與自架產出受其研究及非商業授權限制；本儲存庫不散布該模型。

31 項自動測試涵蓋聊天串流、截圖、模型初始化、語音串接與更新驗證／還原。測試不代表所有硬體組合皆可執行所有模型。
