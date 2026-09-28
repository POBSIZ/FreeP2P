# 배포본 빌드

최종 사용자는 Python을 설치하지 않습니다. 아래는 개발자용 절차입니다.
PyInstaller로 Python, QUIC 암호화 라이브러리, 웹 리소스를 함께 묶습니다.
각 운영체제에서 별도로 빌드해야 합니다. 현재 검증 대상은 Windows x64와 macOS arm64입니다.

## Windows

```powershell
python -m venv .build-venv
.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.build-venv\Scripts\python.exe tools/build_release.py
.build-venv\Scripts\python.exe tools/check_release.py dist/FreeP2P/FreeP2P.exe
```

## macOS

```bash
python3 -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements-build.txt
.build-venv/bin/python tools/build_release.py
.build-venv/bin/python tools/check_release.py dist/FreeP2P.app/Contents/MacOS/FreeP2P
```

결과는 `release/`에 ZIP과 SHA-256 파일로 저장됩니다.
앱 아이콘은 `assets/icon.svg`를 원본으로 사용합니다. 아이콘 변경 시 개발 환경에
`playwright`, `Pillow`와 Playwright Chromium을 설치하고 `python tools/create_icon.py`를 실행하세요.
Mac에서는 이어서 `bash tools/create_mac_icon.sh`로 `.icns`를 만듭니다.
가이드 이미지는 `python tools/capture_guide.py`로 재생성합니다(가상 데이터만 사용).
배포 전 `git add`로 공개할 파일을 명시한 뒤 `python tools/audit_public.py`로
스테이징된 파일의 비밀 패턴·제외 경로·문서 링크를 검사하세요. 자동 검사만으로 모든 유출을 찾지는 못합니다.
Mac ZIP은 `ditto`로 생성하여 앱 번들의 심볼릭 링크와 실행 권한을 보존합니다.
Mac 빌드는 PyInstaller의 로컬 ad-hoc 서명을 사용하며 Developer ID 서명/공증은 하지 않습니다.
Windows도 개발자 인증서 서명 없이 빌드합니다. 서명 없는 배포의 최초 실행 안내는 README를 참고하세요.

실행 파일과 `_internal` 폴더 또는 `.app` 전체를 함께 배포해야 합니다.
`web` 디렉터리는 번들에 내장되며 현재 작업 디렉터리에 의존하지 않습니다.
업데이트할 때는 웹의 **앱 종료** 후 새 배포본으로 교체하세요.

검증 스크립트는 시스템 Python 경로를 제거한 환경에서 배포 실행 파일 2개를 구동하고,
웹 리소스, 인증, 중복 실행 처리, QUIC 연결, TCP 512 KiB 왕복 전송, 인원 설정과 정상 종료를 확인합니다.
개발자 PC에서 실행한 검사이며 깨끗한 OS 설치 환경이나 인터넷 다운로드 후의 Gatekeeper/SmartScreen
확인 과정을 검증한 것은 아닙니다. 실제 게임 플레이 테스트도 별도로 필요합니다.
