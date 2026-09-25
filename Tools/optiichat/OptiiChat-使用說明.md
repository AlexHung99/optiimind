> 1.3.9 採深色青藍聊天版面：左側歷史對話、中央聊天卡片、下方靠左輸入與資源列。設定齒輪位於頂部右側，對話紀錄標題旁的放大鏡可搜尋。輸入框下方的「+」選圖片／PDF，旁邊的「截圖」可直接加入圖片預覽；也能拖入檔案。新對話以日期時間命名，清單完整顯示時間；舊版對話會以問答卡片呈現。可用「重新命名」或 F2 修改標題。PDF 文字自動擷取；掃描檔第一頁先依檔案大小縮小並壓縮，亦可按「選頁」指定頁面。下列舊版介面說明以 README.md 的新版操作為準。

# OptiiChat 本機 AI

雙擊 `Start-OptiiChat.cmd`。舊的 `Start-Llama32-UI.cmd` 也會開啟新版；重複開啟會喚回同一個視窗。

## 選擇已安裝模型與首次初始化

「設定 → 聊天模型」的文字與圖片模型均為下拉選單，讀取本機 Ollama 實際安裝的模型。文字選單列出可聊天的模型，圖片選單只列出支援圖片的模型；不會將純 embedding 模型當作聊天模型。按「重新整理已安裝模型」可更新清單。

新安裝的預設模型為 **llama3.2-vision:latest**，文字與圖片均可使用。已有設定時保留原本選擇；此電腦先前選擇的 Gemma 4 不會被覆寫。原選擇已移除時，改用清單中可用的預設或其他模型。

安裝後首次啟動會初始化模型：若本機完全沒有模型，透過 Ollama 官方模型庫自動下載 `llama3.2-vision`（約 7.8 GB），顯示下載進度。已有任一模型便不自動下載；連線失敗也不會誤判為空清單。下載可停止，失敗或取消後按左側「重新檢查模型」再次嘗試，Ollama 可接續已下載內容。

新電腦請先安裝 Python 3.11+ 與 Ollama，再執行 `Install-OptiiChat.cmd`。安裝腳本會建立 Python 環境，並在缺少相容執行檔時從 Ollama 官方下載 0.24.0 ZIP（約 2.1 GB）並驗證 SHA-256。這是 Python 程式包，不是獨立 EXE。Llama 3.2 Vision 使用 0.24.0 相容服務；Gemma 等其他模型使用一般 Ollama。兩個清單均取自一般 Ollama 的本機模型庫，與本工具相容服務共用模型目錄。

更新程式碼後，請從系統匣選「結束程式」再重新啟動；本機歷史對話會跨重啟保留。

## 聊天與圖片

- 此機既有文字設定為 **Gemma 4 26B**（`gemma4:26b`），GPU 模式，可從下拉選單切換。
- 此機既有圖片設定為 **Llama 3.2 Vision**（`llama3.2-vision:compat`），CPU 模式，可從下拉選單切換。
- 按輸入框旁「＋」選檔，再輸入問題、按「傳送」。支援 JPG、PNG、WEBP、BMP。
- 自動分流會連同近期圖片上下文判斷模型；追問圖片仍交給 Vision。開始新對話後將由程式自動選擇文字或圖片模型。
- Ctrl + Enter 傳送，Enter 換行。「停止回覆」可取消等待或串流。
- 每次保留近期三輪對話，只傳送最近一張圖片。對話文字會保存在本機 history 目錄；模型只接續最近三輪。
- 快速圖片模式限制為 560 px；取消勾選可提高至 1120 px。圖片先在本機去除 metadata 再傳给本機模型。

### 框選截圖

按輸入框「+」右邊的「截圖」，或在 OptiChat 中按 **Ctrl + Shift + S**。聊天視窗會暫時隱藏，用滑鼠拖曳框選螢幕範圍，放開後自動返回聊天，在輸入框顯示圖片預覽。輸入問題後按傳送即可，不需要另存圖片或手動選檔。原先輸入的文字會保留；若原本為純文字模式，附加成功後會切回自動分流。

Esc 或滑鼠右鍵可取消，取消時保留原先附加的圖片。新的截圖會取代尚未傳送的圖片。截圖只會先附加，不會自動送給模型。

支援跨螢幕的矩形範圍與反向拖曳。整張桌面快照只放在記憶體；選取區域暫存為 PNG，傳送、移除、替換圖片或正常結束程式時會刪除。若程式異常終止，Windows 暫存目錄可能留下 `OptiiChat-shot-*.png`。快捷鍵只在程式內有效，不註冊全域熱鍵。

## 設定

左側快捷列的「設定」有外觀、聊天模型、語音三頁；符合單卡 NVIDIA 12 GB 顯存建議配置才顯示 Breeze 引擎與服務參數頁。無法偵測硬體時也會隱藏。

| 模型 | CPU | GPU |
|---|---|---|
| Gemma 4 26B | `num_gpu=0` | Ollama 自動分配，層數預設 -1 |
| Llama 3.2 Vision | 相容版 Ollama 0.24.0，11435 | 相容版 Vulkan，11436，預設 4 層 |
| Windows 本機語音 | 支援 | 不適用 |
| Breeze-TTS-2 官方推論 | 不支援 | 需另行啟動 CUDA 語音服務 |

GPU 模式可以是部分層卸載，其餘仍使用 CPU/RAM。可調整 GPU 層數、上下文長度、輸出 tokens、Temperature。CPU 模式會忽略 GPU 層數。每次聊天完成以 `keep_alive=0` 釋放模型。

此機 RTX 3060 Ti 8 GB / RAM 約 48 GB：Gemma GPU 已實測回覆成功；Vision Vulkan 4 層已成功辨識紅色測試圖片，約 127 秒。這是小圖驗證，大圖和其他顯存占用仍可能導致失敗。先前較高 Vision GPU 層數曾失敗，故預設維持 CPU。

## 語音

預設為 **Windows 本機語音**，可立即使用。先在輸入框填寫文字，或留空以使用上一則完整回覆，再按下方「朗讀」。可停止、匯出 WAV，也能在設定勾選自動朗讀。

Windows 模式可選已安裝聲音、語速及音量，不提供 Voice Design／Clone。Breeze 模式會啟用專屬參數，兩種引擎不互相冒充。語音生成期間先不執行聊天，避免同時搶用記憶體。

### Breeze-TTS-2 狀態與使用

**此機 8 GB 顯存未達建議配置，已隱藏 Breeze、Voice Design／Clone 與服務參數，保留 Windows 本機朗讀。尚未安裝 Breeze 權重。** 目前沒有可連線的 Breeze 服務，因此 Voice Design／Clone 尚不能在本機實際產生聲音。

[官方模型卡](https://huggingface.co/BreezeBlue/Breeze-TTS-2)列出的環境是 Linux、Python 3.10+ 和 CUDA GPU，建議至少 12 GB 顯存；fast-all 建議 24 GB。[官方推論程式](https://github.com/breezeblue-ai/breeze-tts/blob/main/models/fast_streaming.py)會拒絕 CPU。這台 8 GB 顯卡還需負擔桌面，低於官方建議配置；因此沒有安裝無法保證運作的大型環境，也未將 Windows 語音當成 Breeze。

在已有足夠顯存的 Linux CUDA 環境中，依[官方儲存庫](https://github.com/breezeblue-ai/breeze-tts)安裝：

```bash
git clone https://github.com/breezeblue-ai/breeze-tts.git
cd breeze-tts
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install huggingface_hub
hf download BreezeBlue/Breeze-TTS-2 --local-dir ../breeze-tts-2
python -m breeze_infer.api ../breeze-tts-2 --host 127.0.0.1 --port 7860
```

上述命令為部署範例，本次未在 CUDA Linux 環境實測。若服務在另一台機器，可使用 SSH 通道映射其 7860 至此電腦，再將設定的服務網址保留為 `http://127.0.0.1:7860`。已有可存取服務網址時直接填入即可；文字及 Clone 音檔會傳給該服務。程式提供 `/health` 連線測試。

| 參數 | 行為 |
|---|---|
| design | 以「聲音描述」設計聲音，無須參考音檔 |
| clone | 參考音檔 + 正確完整逐字稿；單純複製聲音時清空描述 |
| instruction / Direction | Clone 加上描述即為聲音導演模式 |
| cfg_scale | 大於 0；介面預設 4，強化描述遵循；官方 API 預設 1 |
| seed | 固定隨機種子，介面預設 42 |

使用描述時，其語言應與要朗讀的文字一致。參考音檔上限 30 MB，應使用清楚且逐字稿一致的語音。

fast-all 與五個 fast-* 選項是**服務啟動參數**，只能在服務端重啟後生效。「複製服務啟動命令」會產生含所選旗標的命令，請替換模型目錄；儲存設定不會自動重啟遠端服務。官方 API 的 max_new_tokens=1500、max_seq_len=2048、repetition_penalty=1.1 為固定值，介面僅顯示說明。

Breeze 回傳 24 kHz、單聲道、16-bit PCM，程式封裝為 WAV 後播放。Windows WAV 採系統聲音的原生取樣率。此版等待整段生成完成才播放，可隨時取消生成。

Breeze 原始碼與模型授權不同；權重、衍生模型及自架產出限研究與非商業使用，請參閱[模型授權](https://huggingface.co/BreezeBlue/Breeze-TTS-2/blob/main/LICENSE)。

## 常駐、監控與外觀

- 預設跟隨 Windows 應用程式亮暗設定，也可固定 light／dark。切換主題保留目前對話。
- 使用 [Optiimind 官網](https://optiimind.com/)的原始 PNG 標誌、奶白／炭黑／青綠／金色。原圖来源見 `opti_assets/README.md`。
- 按右上 × 隱藏到系統匣；右鍵圖示選「開啟」、「設定」或「結束程式」。若圖示被 Windows 收在隱藏區，可由右下角展開。
- 系統匣建立失敗時改為最小化，避免找不到視窗。關閉「收至系統匣」選項後 × 會真正結束。
- CPU、RAM、GPU、VRAM 是整機使用情況，並非只有此程式。NVIDIA 無法讀取時顯示 N/A。
- 常駐不等於開機自動啟動；此版本不修改 Windows 開機啟動設定。

## 自動更新

每次啟動都從 OptiChat 的 R2 更新網域檢查清單；有新版時先下載並驗證 SHA-256、版本與檔案路徑，再套用後開啟程式。離線時繼續使用現有版本，啟動後每 15 分鐘重試。背景下載的新版會在從系統匣選「結束程式」後自動套用；單按視窗右上角 × 只是隱藏。啟動器會等待舊程序完全退出，不會在聊天途中重啟。

「設定 → 外觀與常駐」可按「立即檢查更新」；自動檢查始終啟用。設定與模型不會被更新覆寫，舊程式先備份到 `%LOCALAPPDATA%\OptiiChat\updates`。若偵測到手動修改程式，會暫停覆蓋並顯示原因。開發者請透過 Git 更新自行修改的版本。直接執行 `opti_app.py` 不會在啟動前套用更新，請使用啟動檔。

## 檔案與維護

- 主程式：`opti_app.py`；框選截圖：`opti_capture.py`；模型與語音邏輯：`opti_core.py`；下載程序：`opti_model_worker.py`；聊天串流沿用 `llama_vision_ui.py`。
- 設定：`%LOCALAPPDATA%\OptiiChat\settings.json`，按儲存才寫入。
- 生成的 WAV：`%LOCALAPPDATA%\OptiiChat\audio`。生成成功的音檔會保留，可自行整理。
- 相容 Ollama：`%LOCALAPPDATA%\Programs\Ollama-Llama32-Compat`。
- UI Python：新安裝使用 `%LOCALAPPDATA%\OptiiChat\runtime\Scripts\pythonw.exe`，也相容原環境的 `ui-venv\Scripts\pythonw.exe`；Python 套件列於 `opti-requirements.txt`。
- 共用模型：`%USERPROFILE%\.ollama\models`。
- 相容服務日誌：`%LOCALAPPDATA%\OptiiChat\server-11435.log`／`server-11436.log`；原 CPU 服務亦可能由舊啟動器啟動。
- 結束 UI 不強制停止共用 Ollama 服務。

43 項自動測試涵蓋更新驗證／本機修改保護／失敗還原、框選縮放、負座標螢幕定位、截圖取消／附加／传送／暫存清理，以及模型清單、無模型初始化、下載進度／失敗／取消、模型分流、設定保存、Design／Clone 請求、PCM/WAV、主題與系統匣、Unicode 串流與圖片上下文。截圖測試使用合成影像，未讀取真實桌面；空模型下載流程使用模擬清單與串流驗證，沒有刪除現有模型來重下載。Breeze API 音訊測試使用本機模擬服務，並不代表實際 Breeze 模型已驗證。
