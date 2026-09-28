# FreeP2P 0.1.0 — 첫 공개 테스트 릴리스

Python 설치 없이 Minecraft Java LAN 월드를 P2P로 연결하는 실험적인 도구입니다.
실행하면 웹 제어 화면이 열립니다. 게임 트래픽 중계 서버는 사용하지 않습니다.

## 다운로드

- Windows x64: `FreeP2P-0.1.0-windows-x64.zip` 전체 압축 해제 후 `FreeP2P.exe` 실행.
  `_internal` 폴더도 함께 보관하세요.
- Mac M 시리즈: `FreeP2P-0.1.0-darwin-arm64.zip` 압축 해제 후 `FreeP2P.app` 실행.
- 각 ZIP의 `.sha256` 파일을 함께 제공합니다. `Source code` 파일은 실행용 배포본이 아닙니다.

## 먼저 읽어 주세요

- [이미지로 보는 설치·사용 가이드](https://github.com/POBSIZ/FreeP2P/blob/main/docs/USER_GUIDE.md)
- [Windows / Mac 보안 경고와 앱별 실행 허용 안내](https://github.com/POBSIZ/FreeP2P/blob/main/docs/SECURITY_WARNINGS.md)
- [문제 해결](https://github.com/POBSIZ/FreeP2P/blob/main/docs/TROUBLESHOOTING.md)

![실행 방법 안내](https://raw.githubusercontent.com/POBSIZ/FreeP2P/main/docs/images/download.png)

## 포함 기능

- 공개 STUN과 수동 코드 교환을 통한 UDP 홀 펀칭, 암호화된 QUIC 터널.
- 호스트 UDP 소켓 하나에 여러 참가자 연결, 웹에서 최대 참가자 수 변경.
- Python·필요 라이브러리·웹 UI 내장, 전용 exe/app 아이콘.
- 중복 실행 시 기존 웹 화면 다시 열기, 웹의 앱 종료 버튼.
- 번들 라이선스 고지와 빠른 시작 안내.

## 제한과 검증

개발자 인증서 서명/Apple 공증이 없는 배포본으로 최초 실행 경고 또는 차단이 발생할 수 있습니다.
모든 NAT에서 연결되지 않으며 실패 시 릴레이로 전환하지 않습니다.
Intel Mac과 Windows ARM 전용 빌드는 제공하지 않습니다.

Windows x64와 Mac arm64에서 배포 실행 파일의 QUIC/TCP 512 KiB 왕복 전송, 웹 리소스,
중복 실행, 정상 종료를 확인했고 기존 자동 테스트 18개가 통과했습니다.
**실제 Minecraft 월드 입장, 깨끗한 OS 최초 설치 및 다운로드 보안 경고 흐름은 아직 검증하지 않았습니다.**
연결 코드·웹 제어 토큰·원시 로그는 공개하지 마세요.
