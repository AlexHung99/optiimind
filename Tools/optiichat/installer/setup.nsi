Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
Name "OptiChat ${VERSION}"
OutFile "${OUTPUT}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\OptiiChat"
SetCompressor /SOLID lzma
Icon "${APP_ICON}"
UninstallIcon "${APP_ICON}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "OptiChat"
VIAddVersionKey "FileDescription" "OptiChat Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Optiimind"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "安裝 OptiChat 本機 AI。$\r$\n$\r$\n已包含 Python 與介面套件，安裝後會建立桌面捷徑。首次啟動會引導準備 Ollama；大型模型另行下載。$\r$\n$\r$\n每次啟動會從 R2 檢查並安裝新版；離線時仍可使用現有版本，恢復連線後重試。$\r$\n$\r$\n此版本尚未申請程式碼簽章。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_RUN_TEXT "開啟 OptiChat"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "TradChinese"

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "OptiChat 需要 64 位元 Windows。" /SD IDOK
    Abort
  ${EndIf}
!ifdef TEST_ROOT
  StrCpy $INSTDIR "${TEST_ROOT}"
!else
  StrCpy $INSTDIR "$LOCALAPPDATA\OptiiChat"
  System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\OptiiChat.Desktop.Instance") p.r0'
  ${If} $0 != 0
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_ICONSTOP "請先從右下角系統匣結束 OptiChat，再執行安裝。" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
!endif
FunctionEnd

Section "OptiChat"
  SetOutPath "$INSTDIR\python"
  File /r /x "__pycache__" /x "*.pyc" /x "Scripts" /x "bin" /x "bundle-ready.json" "${PYTHON_SOURCE}\*"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\app"
  File /r /x "__pycache__" "${APP_SOURCE}\*"
!ifdef TEST_ROOT
  nsExec::ExecToLog '"$INSTDIR\python\python.exe" "$PLUGINSDIR\app\opti_install.py" --install-bundled --destination "$INSTDIR\app" --no-shortcut'
!else
  nsExec::ExecToLog '"$INSTDIR\python\python.exe" "$PLUGINSDIR\app\opti_install.py" --install-bundled'
!endif
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "程式安裝未完成。請查看安裝詳細資訊；原有設定及模型保留。" /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  File /oname=app-icon.ico "${APP_ICON}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
!ifndef TEST_ROOT
  CreateShortcut "$SMPROGRAMS\OptiChat.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\opti_bootstrap.py"' "$INSTDIR\app-icon.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OptiiChat" "DisplayName" "OptiChat"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OptiiChat" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OptiiChat" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OptiiChat" "DisplayIcon" "$INSTDIR\app-icon.ico"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OptiiChat" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OptiiChat" "NoRepair" 1
!endif
SectionEnd

Function LaunchApp
!ifndef TEST_ROOT
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\app\opti_bootstrap.py"'
!endif
FunctionEnd

Function un.onInit
  SetShellVarContext current
!ifdef TEST_ROOT
  StrCmp $INSTDIR "${TEST_ROOT}" valid
!else
  StrCmp $INSTDIR "$LOCALAPPDATA\OptiiChat" valid
!endif
  Abort
valid:
  System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\OptiiChat.Desktop.Instance") p.r0'
  ${If} $0 != 0
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_ICONSTOP "請先從系統匣結束 OptiChat。" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  ; Only dedicated application directories; settings, audio and model files remain.
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\app-icon.ico"
  Delete "$INSTDIR\Uninstall.exe"
!ifndef TEST_ROOT
  Delete "$DESKTOP\OptiChat.lnk"
  Delete "$SMPROGRAMS\OptiChat.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OptiiChat"
!endif
  RMDir "$INSTDIR"
SectionEnd
