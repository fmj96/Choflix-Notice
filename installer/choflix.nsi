; Choflix Notice - 윈도우 설치 프로그램 (NSIS)
;
;   makensis -DVERSION=1.5.0 -DSOURCE_DIR=..\dist\ChoflixNotice installer\choflix.nsi
;
; SOURCE_DIR 은 PyInstaller 가 만든 폴더(ChoflixNotice.exe 와 _internal 이 든 곳)다.
; 결과물은 저장소 루트에 ChoflixNotice-Setup-<VERSION>.exe 로 떨어진다.
;
; 사용자 단위(per-user) 설치다. 관리자 권한을 요구하지 않는다.
;   - 잠긴 사무용 PC 에도 설치된다.
;   - 자동 실행은 HKCU 에 쓰는데, 관리자로 승격하면 '승격에 쓴 계정'의 HKCU 가
;     되어 정작 로그인한 사용자에게는 자동 실행이 걸리지 않는다. 설정 파일이
;     저장되는 %APPDATA% 도 마찬가지다. 그래서 승격하지 않는다.

Unicode true

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef SOURCE_DIR
  !define SOURCE_DIR "..\dist\ChoflixNotice"
!endif

!define APPNAME   "Choflix Notice"
!define APPEXE    "ChoflixNotice.exe"
!define APPID     "ChoflixNotice"
!define PUBLISHER "fmj96"
!define HOMEPAGE  "https://github.com/fmj96/Choflix-Notice"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"
!define RUNKEY    "Software\Microsoft\Windows\CurrentVersion\Run"

Name "${APPNAME} ${VERSION}"
OutFile "..\ChoflixNotice-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "Software\${APPID}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName"     "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} 설치 프로그램"
VIAddVersionKey "FileVersion"     "${VERSION}"
VIAddVersionKey "ProductVersion"  "${VERSION}"
VIAddVersionKey "LegalCopyright"  "(c) 2026 ${PUBLISHER}"
VIAddVersionKey "CompanyName"     "${PUBLISHER}"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON   "..\assets\icon.ico"
!define MUI_UNICON "..\assets\icon.ico"

!define MUI_WELCOMEPAGE_TEXT "${APPNAME} 설치를 시작합니다.$\r$\n$\r$\n\
정해진 시각에 안내 음성을 자동으로 내보내는 방송 스케줄러입니다.$\r$\n$\r$\n\
※ 이미 실행 중이라면 설치 과정에서 자동으로 종료됩니다.$\r$\n\
   방송이 진행 중이면 중단되니 확인 후 진행하세요.$\r$\n$\r$\n\
※ 예약 목록과 설정은 프로그램 폴더가 아니라 사용자 폴더에 저장되므로$\r$\n\
   덮어 설치해도 기존 예약은 그대로 유지됩니다."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPEXE}"
!define MUI_FINISHPAGE_RUN_TEXT "${APPNAME} 실행"
!define MUI_FINISHPAGE_LINK "사용법과 최신 버전 보기"
!define MUI_FINISHPAGE_LINK_LOCATION "${HOMEPAGE}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "English"

; 설치/제거 전에 실행 중인 프로그램을 닫는다. 열려 있으면 파일을 덮어쓸 수 없다.
; tasklist 결과를 파싱해 분기하려면 문자열 검색 매크로가 필요한데 그만한 값어치가
; 없다. taskkill 은 대상이 없으면 조용히 실패하므로 그냥 부르고 결과를 무시한다.
!macro KillApp
  DetailPrint "실행 중인 ${APPNAME} 을(를) 닫는 중..."
  nsExec::ExecToLog 'taskkill /IM "${APPEXE}"'
  Pop $0
  Sleep 1500
  nsExec::ExecToLog 'taskkill /F /IM "${APPEXE}"'
  Pop $0
  Sleep 500
!macroend

Section "${APPNAME} (필수)" SecCore
  SectionIn RO
  !insertmacro KillApp

  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*.*"
  File "..\LICENSE"
  File "..\README.md"

  WriteRegStr HKCU "Software\${APPID}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\${APPID}" "Version"    "${VERSION}"

  ; 설정 > 앱 목록에 등록 (사용자 단위)
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayName"     "${APPNAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "Publisher"       "${PUBLISHER}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\${APPEXE}"
  WriteRegStr   HKCU "${UNINSTKEY}" "URLInfoAbout"    "${HOMEPAGE}"
  WriteRegStr   HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr   HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" "$0"

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut  "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${APPEXE}"
  CreateShortcut  "$SMPROGRAMS\${APPNAME}\${APPNAME} 제거.lnk" "$INSTDIR\uninstall.exe"

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "바탕 화면에 아이콘 만들기" SecDesktop
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPEXE}"
SectionEnd

Section /o "윈도우 시작 시 자동 실행" SecAutoStart
  ; 프로그램의 설정 탭이 쓰는 값과 완전히 같다. 양쪽이 어긋나지 않는다.
  WriteRegStr HKCU "${RUNKEY}" "${APPID}" '"$INSTDIR\${APPEXE}" --tray'
SectionEnd

LangString DESC_SecCore      ${LANG_KOREAN}  "프로그램 본체입니다. 반드시 설치됩니다."
LangString DESC_SecDesktop   ${LANG_KOREAN}  "바탕 화면에 실행 아이콘을 만듭니다."
LangString DESC_SecAutoStart ${LANG_KOREAN}  "윈도우에 로그인하면 트레이에 자동으로 실행됩니다. 무인 방송 PC 에 유용합니다."
LangString DESC_SecCore      ${LANG_ENGLISH} "The application itself. Always installed."
LangString DESC_SecDesktop   ${LANG_ENGLISH} "Create a shortcut on the desktop."
LangString DESC_SecAutoStart ${LANG_ENGLISH} "Start minimized to the tray when Windows starts."

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore}      $(DESC_SecCore)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop}   $(DESC_SecDesktop)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAutoStart} $(DESC_SecAutoStart)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

Function un.onInit
  !insertmacro MUI_UNGETLANGUAGE
FunctionEnd

Section "Uninstall"
  !insertmacro KillApp

  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME} 제거.lnk"
  RMDir  "$SMPROGRAMS\${APPNAME}"

  DeleteRegValue HKCU "${RUNKEY}" "${APPID}"
  DeleteRegKey   HKCU "${UNINSTKEY}"
  DeleteRegKey   HKCU "Software\${APPID}"

  RMDir /r "$INSTDIR\_internal"
  Delete   "$INSTDIR\${APPEXE}"
  Delete   "$INSTDIR\LICENSE"
  Delete   "$INSTDIR\README.md"
  Delete   "$INSTDIR\uninstall.exe"
  RMDir    "$INSTDIR"

  ; 예약 목록과 설정은 %APPDATA% 에 따로 있다. 지우면 되돌릴 수 없으니 물어본다.
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "예약 목록과 설정도 함께 지울까요?$\r$\n$\r$\n아니오를 누르면 그대로 남습니다.$\r$\n($APPDATA\${APPID})" \
    IDNO SkipData
    RMDir /r "$APPDATA\${APPID}"
  SkipData:
SectionEnd
