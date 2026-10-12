# 배포본 빌드

개발자가 실행 파일을 만드는 절차입니다. 프로그램을 사용하려면 [다운로드 안내](README.md#다운로드)를 따르세요.

PyInstaller로 Python, QUIC 라이브러리, 웹 화면 파일을 실행 파일과 함께 묶습니다.
배포본 사용자는 Python을 따로 설치하지 않아도 됩니다.
Windows용은 Windows에서, Mac용은 macOS에서 빌드해야 합니다. 빌드와 실행을 확인한 환경은 Windows x64와 macOS arm64입니다.

아래 명령은 프로젝트 최상위 폴더에서 실행하세요.

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

## 생성되는 파일과 배포 시 주의점

실행 파일은 `dist/`에, 배포용 ZIP과 SHA-256 파일은 `release/`에 생성됩니다.
Windows는 `FreeP2P.exe`와 `_internal` 폴더를 함께 배포해야 합니다. Mac은 `FreeP2P.app` 전체를 배포하세요.
웹 화면 파일도 배포본에 포함되므로 실행 위치에 별도의 `web` 폴더를 둘 필요는 없습니다.

Mac ZIP은 `ditto`로 만들어 앱 내부의 심볼릭 링크와 실행 권한을 보존합니다.
Mac 앱에는 PyInstaller의 로컬 ad-hoc 서명이 적용됩니다. Developer ID 서명이나 Apple 공증은 하지 않습니다.
Windows 실행 파일도 개발자 인증서로 서명하지 않습니다. 처음 실행할 때 표시되는 경고는 [실행 경고 안내](docs/SECURITY_WARNINGS.md)를 참고하세요.

배포 전에는 `git add`에 공개할 파일을 지정한 뒤 `python tools/audit_public.py`를 실행하세요.
이 도구는 스테이징된 파일에서 비밀 정보 패턴, 공개하면 안 되는 경로, 문서 링크를 검사합니다.
자동 검사가 찾지 못하는 정보도 있을 수 있으므로 실제 연결 코드와 개인 네트워크 정보가 없는지 직접 확인해야 합니다.

기존 버전에서 업데이트할 때는 FreeP2P 화면의 **앱 종료**를 누른 뒤 새 배포본을 실행하세요.

## 배포본 검사 범위

위의 `tools/check_release.py`는 PATH에서 시스템 Python 경로를 제외하고 `PYTHONHOME`과 `PYTHONPATH`를 지운 환경에서 배포 앱 두 개를 실행합니다.
웹 화면 파일, API 인증, 중복 실행 처리, QUIC 연결, TCP 512 KiB 왕복 전송, 참가 인원 변경, 정상 종료를 확인합니다.

개발자 PC에서 실행하는 검사입니다. 새로 설치한 운영체제에서의 실행, 인터넷에서 다운로드한 직후의 Gatekeeper·SmartScreen 경고 처리, 실제 Minecraft 플레이는 별도로 확인해야 합니다.
현재까지 확인한 결과와 한계는 [검증 범위](TEST_RESULTS.md)에 정리했습니다.

## 아이콘과 안내 이미지 수정

앱 아이콘의 원본은 `assets/icon.svg`입니다. 아이콘을 바꾸려면 개발 환경에 `playwright`, `Pillow`, Playwright Chromium을 설치하고 `python tools/create_icon.py`를 실행하세요.
Mac에서는 이어서 `bash tools/create_mac_icon.sh`를 실행해 `.icns` 파일을 만듭니다.

가이드 이미지는 Playwright와 Chromium을 설치한 환경에서 `python tools/capture_guide.py`로 다시 만듭니다.
이 스크립트는 가상 이름과 연결할 수 없는 예시 코드만 사용합니다.
